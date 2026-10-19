"""TB-4 待确认事项与「暂时跳过」：接缝测试（进程内 HTTP；模型走 fake）。

对应规格 User Stories 5 / 8 / 9 与术语「待确认事项」：
- 作答请求支持把某个问题标记为**暂时跳过**；被跳过的问题进入待确认事项清单，**保持未定**；
- 待确认事项清单可读可维护（状态 open → confirmed / dismissed），来源轮次正确；
- **负测（本单核心）**：用户确认动作之前，待确认事项不得作为「已定需求」进入下游——
  下游 = ①方案正文输入里的「已确定」区块；②生成闸门的判定。

语义质量不做自动化断言——只断言清单读写、提示词分类区块与闸门判定。
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
    "## 待确认事项\n- 目标读者是否限定为一线主管？\n\n"
    "## 输出要求\nWord 文档。"
)


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _empty_frontier_json() -> str:
    return json.dumps({"frontier": []}, ensure_ascii=False)


def _start(client: TestClient, scripted: ScriptedModelClient, *results: str) -> int:
    scripted.set_sequence(*results)
    response = client.post("/api/grilling/tasks", json={"idea": IDEA})
    assert response.status_code == 201
    return response.json()["task"]["id"]


def _section(text: str, heading: str, next_heading: str | None) -> str:
    """从提示词文本里截出某个区块（用于断言「已定 / 未定」的分类归属）。"""
    start = text.index(heading)
    if next_heading is None:
        return text[start:]
    return text[start : text.index(next_heading, start)]


# --- 暂时跳过：进入待确认事项 ---------------------------------------------------


def test_skipped_question_enters_open_items_with_source_round(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """某个问题被「暂时跳过」→ 进入待确认事项，来源轮次为该轮，状态 open。"""
    scripted_model_client.set_result(
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页"))
    )
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    # 第一题跳过（JSON null），第二题正常作答
    accepted = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": [None, "10 页以内"]},
    )
    assert accepted.status_code == 200

    listed = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items")

    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["text"] == "目标读者"
    assert item["round_no"] == 1  # 来源轮次正确
    assert item["status"] == "open"
    assert item["resolved_at"] is None


def test_blank_answer_counts_as_skip(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """空白作答等同「暂时跳过」（避免前端漏发 null 时静默丢问题）。"""
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["   "]},
    )

    items = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"]
    assert [item["text"] for item in items] == ["目标读者"]


def test_answered_question_does_not_enter_open_items(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """正常作答的问题不进待确认事项。"""
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["新员工"]},
    )

    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["total"] == 0


def test_open_items_for_missing_task_returns_404(grilling_client: TestClient) -> None:
    """读取不存在任务的待确认事项 → 404。"""
    assert grilling_client.get("/api/grilling/tasks/9999/open-items").status_code == 404


# --- 清单维护：状态迁移 ---------------------------------------------------------


def test_resolve_open_item_records_status_and_time(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """用户确认动作：状态 open → confirmed，记录 resolved_at（落库可复原）。"""
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": [None]}
    )
    item_id = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"][0][
        "id"
    ]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/open-items/{item_id}/resolve",
        json={"status": "confirmed"},
    )

    assert response.status_code == 200
    resolved = response.json()
    assert resolved["status"] == "confirmed"
    assert resolved["resolved_at"]

    reread = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"][0]
    assert reread == resolved


def test_dismiss_open_item_is_also_a_resolution(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """用户认定某推测不需要时置为 dismissed——同样解除「未定」状态。"""
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": [None]}
    )
    item_id = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"][0][
        "id"
    ]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/open-items/{item_id}/resolve",
        json={"status": "dismissed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


def test_resolve_with_invalid_status_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """非法状态 → 422（状态只允许 confirmed / dismissed）。"""
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": [None]}
    )
    item_id = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"][0][
        "id"
    ]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/open-items/{item_id}/resolve",
        json={"status": "open"},
    )

    assert response.status_code == 422


def test_resolve_unknown_item_returns_404(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """待确认事项不存在 → 404。"""
    scripted_model_client.set_result(_frontier_json(("Q", "正文", "推荐")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/open-items/9999/resolve",
        json={"status": "confirmed"},
    )

    assert response.status_code == 404


# --- 负测：确认动作之前不得作为「已定需求」进入下游 -----------------------------


def test_skipped_question_is_not_a_determined_decision_in_either_block(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """跳过的题不出现在「已确定决策」区块，只出现在「未定（待确认事项）」区块。

    这是下游边界 ①「方案正文的『已确定』部分」——跳过的问题不得被模型当作已定需求。
    """
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": [None, "10 页以内"]},
    )
    scripted_model_client.calls.clear()

    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    # 收敛后的第一次模型调用就是方案生成
    plan_prompt = " ".join(
        message["content"] for message in scripted_model_client.calls[0]["messages"]
    )
    determined = _section(
        plan_prompt, "## 已确定决策", "## 未定"
    )
    undecided = _section(plan_prompt, "## 未定", "## 历轮问答")

    assert "目标读者" not in determined  # 跳过 → 不是已定需求
    assert "篇幅" in determined  # 已答 → 是已定需求
    assert "目标读者" in undecided  # 只进未定区块


def test_skipped_question_does_not_enter_next_round_determined(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """跳过的题也不作为「已确定决策」喂给下一轮前沿生成（不再是隐含前置条件）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
        _frontier_json(("案例来源", "用哪些案例？", "内部项目")),
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": [None, "10 页以内"]},
    )
    scripted_model_client.calls.clear()

    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    next_round_prompt = " ".join(
        message["content"] for message in scripted_model_client.calls[0]["messages"]
    )
    determined = _section(next_round_prompt, "## 已确定决策", "## 未定")
    assert "目标读者" not in determined
    assert "篇幅" in determined


def test_open_items_block_plan_confirmation_until_they_are_resolved(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """下游边界 ②「生成闸门的判定」：未处置的待确认事项在**确认方案这一步**就被拦下。

    修正约定笔记登记的 TB-4 已知缺陷：确认入口原先不检查未处置条目，会造出
    「方案已 confirmed、却因仍有 open 条目而无法生成（409）」的尴尬中间态。
    原型语义是「待确认事项已全部定下，可以确认方案」，规格 US 9 也要求未经确认的推测
    不得当作已定需求——故确认时即返回 409 并说明还有几项未定、如何处置；
    用户处置后确认通过，闸门随之放行（生成管线归 TB-5/TB-6，故以 501 收尾）。
    """
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": [None, "10 页以内"]},
    )
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    refused = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "1 项待确认事项" in detail  # 还有几项未定
    assert "目标读者" in detail  # 具体是哪几项
    assert "确认或搁置" in detail  # 如何处置
    # 方案仍是草稿：没有进入「已确认但无法生成」的中间态
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").json()["status"] == "draft"

    item_id = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"][0][
        "id"
    ]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/open-items/{item_id}/resolve",
        json={"status": "confirmed"},
    )

    confirmed = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    # 处置完毕 → 生成闸门放行（交 TB-5 的 Word 成品管线）
    assert grilling_client.post(f"/api/tasks/{task_id}/generations").status_code == 201


def test_dismissed_open_item_also_unblocks_plan_confirmation(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """「搁置」（认定不需要）与「确认」一样解除未定状态，可确认方案。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": [None]}
    )
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")
    item_id = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()["items"][0][
        "id"
    ]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/open-items/{item_id}/resolve",
        json={"status": "dismissed"},
    )

    confirmed = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"


def test_resolved_open_item_does_not_block_generation(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """无未定条目时闸门判定不受待确认事项影响（不误伤已处置的任务）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["答"]}
    )
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")
    grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    assert grilling_client.post(f"/api/tasks/{task_id}/generations").status_code == 201


# --- 重启续作 -------------------------------------------------------------------


def test_open_items_survive_restart(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """待确认事项落库：重建 app 与客户端后仍可读回（重启续作）。"""
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": [None]}
    )
    before = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        after = rebuilt.get(f"/api/grilling/tasks/{task_id}/open-items").json()

    assert after == before
    assert after["items"][0]["status"] == "open"