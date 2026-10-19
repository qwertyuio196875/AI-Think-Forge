"""TB-4 方案对话式修订：接缝测试（进程内 HTTP；模型走 fake）。

对应规格 User Story 8/9 与工单 13 窄路径：
- 对已生成方案**继续对话 → 方案更新**；
- 返回**差异提示**（哪些部分被改动）；
- **旧版本留痕可查**（修订前内容 / 修订后内容 / 修订时间）；
- 修订后方案回到 draft（原确认不再覆盖新内容），生成闸门重新关闭。

语义质量不做自动化断言——只断言内容变化、差异提示、留痕与闸门。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.main import create_app

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 核心观点\n从场景切入，而非功能罗列。\n\n"
    "## 关键约束\n篇幅 10 页以内。\n\n"
    "## 风险\n案例不足会显得空泛。\n\n"
    "## 待确认事项\n- 是否需要配套练习？\n\n"
    "## 输出要求\nWord 文档。"
)

REVISED_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n初级工程师。\n\n"
    "## 核心观点\n从场景切入，而非功能罗列。\n\n"
    "## 关键约束\n篇幅 10 页以内。\n\n"
    "## 待确认事项\n- 是否需要配套练习？\n\n"
    "## 执行步骤\n先定大纲，再补案例。\n\n"
    "## 输出要求\nWord 文档。"
)

INSTRUCTION = "目标读者改成初级工程师"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _empty_frontier_json() -> str:
    return json.dumps({"frontier": []}, ensure_ascii=False)


def _start_with_plan(client: TestClient, scripted: ScriptedModelClient) -> int:
    """走一轮问答收敛并产出方案草稿，返回任务 id。"""
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    started = client.post("/api/grilling/tasks", json={"idea": IDEA})
    assert started.status_code == 201
    task_id = started.json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["新员工", "10 页以内"]},
    )
    advanced = client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert advanced.status_code == 200
    assert advanced.json()["plan"]["content_md"] == PLAN_MD
    return task_id


# --- 修订：内容变化 + 差异提示 + 留痕 -------------------------------------------


def test_revision_updates_plan_and_returns_change_summary(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """对方案说一句话 → 方案更新，并返回「哪些部分被改动」的差异提示。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    original = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").json()
    scripted_model_client.set_result(REVISED_MD)

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )

    assert response.status_code == 200
    body = response.json()
    # 修订后内容确实变化
    assert body["plan"]["content_md"] == REVISED_MD
    assert body["plan"]["content_md"] != original["content_md"]
    assert body["plan"]["id"] == original["id"]
    assert body["plan"]["status"] == "draft"

    revision = body["revision"]
    assert revision["instruction"] == INSTRUCTION
    assert revision["previous_content_md"] == PLAN_MD  # 修订前内容
    assert revision["content_md"] == REVISED_MD  # 修订后内容
    assert revision["created_at"]  # 修订时间

    # 差异提示：读者被改、风险被删、执行步骤新增
    changes = {(change["kind"], change["heading"]) for change in revision["change_summary"]}
    assert ("modified", "读者") in changes
    assert ("removed", "风险") in changes
    assert ("added", "执行步骤") in changes
    assert ("modified", "目标") not in changes  # 未改动的部分不得误报


def test_revision_is_readable_from_plan_endpoint(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案更新落库：GET 方案读到的是修订后的内容。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    scripted_model_client.set_result(REVISED_MD)

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )

    fetched = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan")
    assert fetched.status_code == 200
    assert fetched.json()["content_md"] == REVISED_MD


def test_old_versions_are_kept_and_queryable(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """旧版本不可丢：修订历史可查，逐条保留修订前 / 修订后内容与时间。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    scripted_model_client.set_result(REVISED_MD)
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )

    history = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan/revisions")

    assert history.status_code == 200
    body = history.json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["previous_content_md"] == PLAN_MD
    assert entry["content_md"] == REVISED_MD
    assert entry["instruction"] == INSTRUCTION
    # 当前方案正文即最后一条修订的「修订后内容」
    assert (
        grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").json()["content_md"]
        == entry["content_md"]
    )


def test_successive_revisions_accumulate_history(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """多次修订逐条留痕，链条首尾相接（后一条的修订前 = 前一条的修订后）。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    third_md = REVISED_MD.replace("初级工程师", "初级工程师（含实习生）")

    scripted_model_client.set_result(REVISED_MD)
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )
    scripted_model_client.set_result(third_md)
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions",
        json={"instruction": "再放宽到含实习生"},
    )

    items = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan/revisions").json()["items"]
    assert [item["previous_content_md"] for item in items] == [PLAN_MD, REVISED_MD]
    assert [item["content_md"] for item in items] == [REVISED_MD, third_md]


def test_revision_history_empty_before_any_revision(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """尚未修订 → 历史为空（不是 404）。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)

    body = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan/revisions").json()
    assert body == {"items": [], "total": 0}


# --- 修订的提示词：带上当前方案、指令、已定与未定 -------------------------------


def test_revision_prompt_carries_prior_plan_and_instruction(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """修订经模型执行：提示词里必须有当前方案正文与用户修订指令。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    scripted_model_client.set_result(REVISED_MD)
    scripted_model_client.calls.clear()

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )

    sent = " ".join(
        message["content"] for message in scripted_model_client.calls[0]["messages"]
    )
    assert PLAN_MD in sent or "新入职员工。" in sent
    assert INSTRUCTION in sent
    assert "待确认事项" in sent  # 未定项在修订时同样不得写成已定需求


def test_revision_of_confirmed_plan_reopens_the_gate(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """已确认方案被修订 → 回到 draft（原确认不再覆盖新内容），生成闸门重新关闭。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    confirmed = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").json()
    assert confirmed["status"] == "confirmed"
    assert grilling_client.post(f"/api/tasks/{task_id}/generations").status_code == 201
    scripted_model_client.set_result(REVISED_MD)

    revised = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    ).json()

    assert revised["plan"]["status"] == "draft"
    assert revised["plan"]["confirmed_at"] is None
    assert grilling_client.post(f"/api/tasks/{task_id}/generations").status_code == 409


# --- 边界 -----------------------------------------------------------------------


def test_revision_without_plan_returns_404(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """尚未收敛出方案就请求修订 → 404。"""
    scripted_model_client.set_result(_frontier_json(("Q", "正文", "推荐")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )

    assert response.status_code == 404


def test_revision_for_missing_task_returns_404(grilling_client: TestClient) -> None:
    """不存在任务的修订 → 404。"""
    response = grilling_client.post(
        "/api/grilling/tasks/9999/plan/revisions", json={"instruction": INSTRUCTION}
    )
    assert response.status_code == 404


def test_revision_requires_non_empty_instruction(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """空指令 → 422（修订必须有用户消息）。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": "  "}
    )

    assert response.status_code == 422


def test_revision_survives_restart(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """修订留痕落库：重建 app 与客户端后仍可查（重启续作）。"""
    task_id = _start_with_plan(grilling_client, scripted_model_client)
    scripted_model_client.set_result(REVISED_MD)
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": INSTRUCTION}
    )
    before = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan/revisions").json()

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        after = rebuilt.get(f"/api/grilling/tasks/{task_id}/plan/revisions").json()

    assert after == before
    assert after["items"][0]["previous_content_md"] == PLAN_MD