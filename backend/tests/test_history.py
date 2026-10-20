"""TB-10 历史、续作与删除：接缝测试（唯一接缝 = 进程内 HTTP；模型走 fake）。

对应规格 User Stories 26~28 与工单 19 的窄路径：
- **历史列表**：创作 / 分析分类、状态、时间，分页（limit/offset），排除已删除任务，
  并给出导航徽标用的分计数；
- **打开详情并续作**：详情自带复原所需的一切（种子输入 / 各轮次 / 消息 / 方案 / 待确认事项）
  与「下一步动作」，**支持停在拷问中途的任务**（回到原轮次继续）；重建客户端后仍可续作；
- **删除**：先返回影响范围（对话条数、方案、成品文件数），确认后才执行；软删除留痕；
- **负测**：模型调用失败后，已保存的对话与方案完好无损。

语义质量不做自动化断言——只断言状态、持久化数据与 API 返回的影响范围。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.api.deps import get_model_client
from app.main import create_app

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
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
    """发起主题创作并返回任务 id（脚本按调用顺序给出）。"""
    scripted.set_sequence(*results)
    response = client.post("/api/grilling/tasks", json={"idea": IDEA})
    assert response.status_code == 201
    return response.json()["task"]["id"]


# --- 历史列表 -------------------------------------------------------------------


def test_history_lists_tasks_by_category_with_counts(client: TestClient) -> None:
    """历史列表按分类过滤，并给出导航徽标用的分计数（排除已删除任务）。"""
    client.post("/api/tasks", json={"kind": "creation", "title": "写一篇产品介绍"})
    client.post("/api/tasks", json={"kind": "analysis", "title": "读一份 PDF"})
    client.post("/api/tasks", json={"kind": "creation", "title": "写一份周报"})

    response = client.get("/api/history")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["title"] for item in body["items"]] == ["写一份周报", "读一份 PDF", "写一篇产品介绍"]
    assert body["counts"] == {"all": 3, "creation": 2, "analysis": 1}

    creation_only = client.get("/api/history", params={"kind": "creation"}).json()
    assert creation_only["total"] == 2
    assert {item["kind"] for item in creation_only["items"]} == {"creation"}
    # 分计数是全局视角，不随过滤条件变化（导航徽标显示总体规模）
    assert creation_only["counts"] == {"all": 3, "creation": 2, "analysis": 1}


def test_history_items_carry_status_and_activity_metadata(client: TestClient) -> None:
    """历史条目带状态点与元信息行所需的字段（状态 / 时间 / 对话条数 / 轮次数）。"""
    client.post("/api/tasks", json={"kind": "creation", "title": "A"})
    client.post("/api/tasks", json={"kind": "analysis", "title": "B"})

    item = client.get("/api/history", params={"kind": "analysis"}).json()["items"][0]

    assert item["status"] == "in_progress"
    assert item["kind"] == "analysis"
    assert "T" in item["created_at"]
    assert "T" in item["updated_at"]
    assert item["dialogue_messages"] == 0
    assert item["rounds"] == 0


def test_history_filters_by_status(client: TestClient) -> None:
    """状态过滤生效（进行中 / 已完成）。"""
    task = client.post("/api/tasks", json={"kind": "creation", "title": "A"}).json()
    client.post("/api/tasks", json={"kind": "creation", "title": "B"})

    completed = client.post(f"/api/tasks/{task['id']}/status", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    in_progress = client.get("/api/history", params={"status": "in_progress"}).json()
    assert [item["title"] for item in in_progress["items"]] == ["B"]

    done = client.get("/api/history", params={"status": "completed"}).json()
    assert [item["title"] for item in done["items"]] == ["A"]


def test_history_paginates_with_limit_and_offset(client: TestClient) -> None:
    """分页：limit / offset 生效，total 始终是过滤后的总数。"""
    for index in range(5):
        client.post("/api/tasks", json={"kind": "creation", "title": f"T{index}"})

    page = client.get("/api/history", params={"limit": 2, "offset": 1}).json()

    assert page["total"] == 5
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert [item["title"] for item in page["items"]] == ["T3", "T2"]


def test_history_rejects_invalid_paging_parameters(client: TestClient) -> None:
    """非法分页参数被校验拒绝（不静默返回全量）。"""
    assert client.get("/api/history", params={"limit": 0}).status_code == 422
    assert client.get("/api/history", params={"offset": -1}).status_code == 422


def test_history_rejects_unknown_kind(client: TestClient) -> None:
    """未知分类 → 422。"""
    assert client.get("/api/history", params={"kind": "whatever"}).status_code == 422


def test_history_excludes_deleted_tasks_and_survives_restart(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """删除后的任务不再出现在历史列表；重建客户端（重启续作）后列表仍可读。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
    )
    before = grilling_client.get("/api/history").json()
    assert before["total"] == 1

    assert (
        grilling_client.delete(f"/api/tasks/{task_id}", params={"confirm": True}).status_code
        == 200
    )

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        after = rebuilt.get("/api/history").json()

    assert after["total"] == 0
    assert after["items"] == []
    assert after["counts"] == {"all": 0, "creation": 0, "analysis": 0}


# --- 打开详情并续作 -------------------------------------------------------------


def test_history_detail_reports_pending_round_and_next_action(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """停在拷问中途（前沿已提出、尚未作答）→ 详情指出待作答轮次与下一步动作。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
    )

    detail = grilling_client.get(f"/api/history/{task_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["task"]["id"] == task_id
    assert body["dialogue"]["seed_input"] == IDEA
    assert body["last_round_no"] == 1
    assert body["awaiting"] == "answers"
    pending = body["pending_round"]
    assert pending["round_no"] == 1
    assert [q["title"] for q in pending["frontier"]] == ["目标读者", "篇幅"]
    assert pending["answers"] == []
    assert body["plan"] is None
    assert body["open_items"] == []
    assert body["unresolved_open_items"] == 0
    assert body["deleted_at"] is None


def test_resume_stuck_mid_grilling_after_rebuilding_client(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """演示路径：拷问中途关掉系统 → 重开（重建客户端）→ 回到原轮次继续。

    重建后的客户端只有既有 `messages` 可依（不新建任何状态），照样能从第 1 轮续上第 2 轮。
    """
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
    )

    resumed_model = ScriptedModelClient(
        result=_frontier_json(("案例来源", "用哪些真实案例？", "内部项目"))
    )
    resumed_app = create_app(db_path=db_path, mount_frontend=False)
    resumed_app.dependency_overrides[get_model_client] = lambda: resumed_model

    with TestClient(resumed_app) as resumed:
        detail = resumed.get(f"/api/history/{task_id}").json()
        assert detail["awaiting"] == "answers"
        assert detail["pending_round"]["round_no"] == 1

        # 回到原轮次继续：提交第 1 轮回答 → 推进出第 2 轮
        answered = resumed.post(
            f"/api/grilling/tasks/{task_id}/answers",
            json={"round_no": 1, "answers": ["新员工", "10 页以内"]},
        )
        assert answered.status_code == 200
        advanced = resumed.post(f"/api/grilling/tasks/{task_id}/advance")

    assert advanced.status_code == 200
    assert advanced.json()["next_round"]["round_no"] == 2
    assert resumed_model.calls[0]["model"] == "deepseek-flash"


def test_history_detail_advances_from_answered_round_to_plan_confirmation(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """已作答但尚未推进 → awaiting=advance；收敛出草稿方案 → awaiting=plan_confirm；
    方案确认后 → awaiting=generation（下一步动作随持久化状态走）。"""
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

    awaiting_advance = grilling_client.get(f"/api/history/{task_id}").json()
    assert awaiting_advance["awaiting"] == "advance"
    assert awaiting_advance["pending_round"] is None
    assert awaiting_advance["last_round_no"] == 1

    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")
    awaiting_confirm = grilling_client.get(f"/api/history/{task_id}").json()
    assert awaiting_confirm["awaiting"] == "plan_confirm"
    assert awaiting_confirm["plan"]["status"] == "draft"

    grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")
    awaiting_generation = grilling_client.get(f"/api/history/{task_id}").json()
    assert awaiting_generation["awaiting"] == "generation"
    assert awaiting_generation["plan"]["status"] == "confirmed"


def test_history_detail_carries_open_items_and_their_count(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """详情带上待确认事项与未处置计数，供详情页标示「还有什么未确定」。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": [None, "10 页以内"]},
    )

    body = grilling_client.get(f"/api/history/{task_id}").json()

    assert [item["text"] for item in body["open_items"]] == ["目标读者"]
    assert body["unresolved_open_items"] == 1


def test_history_detail_for_missing_task_returns_404(client: TestClient) -> None:
    """详情读不存在的任务 → 404。"""
    assert client.get("/api/history/9999").status_code == 404


# --- 删除：先返回影响范围，确认后才执行 -----------------------------------------


def test_deletion_impact_reports_dialogue_plan_and_deliverable_files(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """影响范围：对话条数 / 轮次 / 方案与修订记录 / 待确认事项 / 成品文件数（规格 US 27）。"""
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
    # 再做一次对话式修订：影响范围要如实带上方案版本记录
    scripted_model_client.set_result(PLAN_MD + "\n\n## 执行步骤\n先定大纲。")
    revised = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": "补上执行步骤"}
    )
    assert revised.status_code == 200

    response = grilling_client.get(f"/api/tasks/{task_id}/deletion-impact")

    assert response.status_code == 200
    impact = response.json()
    assert impact["task_id"] == task_id
    assert impact["title"] == IDEA
    assert impact["kind"] == "creation"
    assert impact["status"] == "in_progress"
    # 种子输入 1 条 + 第 1 轮提问 1 条 + 第 1 轮回答 2 条
    assert impact["dialogue_messages"] == 4
    assert impact["rounds"] == 1
    assert impact["plans"] == 1
    assert impact["plan_revisions"] == 1
    assert impact["open_items"] == 1
    # 该任务尚未生成成品：如实为 0（不伪造影响范围）
    assert impact["deliverable_files"] == 0
    assert "对话 4 条" in impact["summary"]
    assert "方案 1 份" in impact["summary"]
    assert "修订记录 1 条" in impact["summary"]
    assert "成品文件 0 个" in impact["summary"]


def test_deletion_impact_for_missing_task_returns_404(client: TestClient) -> None:
    """对不存在的任务取影响范围 → 404。"""
    assert client.get("/api/tasks/9999/deletion-impact").status_code == 404


def test_delete_without_confirmation_is_refused_with_impact(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """未确认即删除 → 409，且响应明示影响范围；任务**未被删除**。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
    )

    response = grilling_client.delete(f"/api/tasks/{task_id}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "对话 2 条" in detail  # 影响范围明示（规格 US 27）
    assert "确认" in detail  # 并说明如何继续
    assert grilling_client.get(f"/api/tasks/{task_id}").json()["status"] == "in_progress"


def test_delete_after_confirmation_soft_deletes_and_keeps_data(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """确认删除 → 置为已删除并留痕；对话与方案仍在库中（软删除不物理清库）。"""
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
    dialogue_before = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()
    plan_before = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").json()

    response = grilling_client.delete(f"/api/tasks/{task_id}", params={"confirm": True})

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == "deleted"
    assert body["already_deleted"] is False
    assert body["deleted_at"]
    assert body["impact"]["dialogue_messages"] == 3

    # 数据一条未少：删除只是留痕标记
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json() == dialogue_before
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").json() == plan_before
    # 历史视图不再列出，但留痕可查
    assert grilling_client.get("/api/history").json()["total"] == 0
    trashed = grilling_client.get("/api/history", params={"status": "deleted"}).json()
    assert [item["id"] for item in trashed["items"]] == [task_id]

    # 重建客户端后留痕仍在（重启续作）
    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        detail = rebuilt.get(f"/api/history/{task_id}").json()
    assert detail["task"]["status"] == "deleted"
    assert detail["deleted_at"] == body["deleted_at"]
    assert detail["awaiting"] == "deleted"


def test_delete_is_idempotent_and_keeps_first_deletion_time(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """重复删除不报错、也不漂移删除时间（幂等）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
    )
    first = grilling_client.delete(f"/api/tasks/{task_id}", params={"confirm": True}).json()

    again = grilling_client.delete(f"/api/tasks/{task_id}", params={"confirm": True})

    assert again.status_code == 200
    assert again.json()["already_deleted"] is True
    assert again.json()["deleted_at"] == first["deleted_at"]


def test_deletion_impact_counts_existing_deliverable_files(
    client: TestClient, db_path: Path
) -> None:
    """成品文件数按任务如实计数（`generations` 表由 TB-5 落地）。

    删除影响范围只是读 `generations` 的行数；本测试直接写入两行成品记录验证计数口径，
    不经过生成管线（生成真的会落盘文件，属于 TB-5 自己的接缝测试）。
    """
    task_id = client.post("/api/tasks", json={"kind": "creation", "title": "A"}).json()["id"]

    # 尚未生成任何成品：如实返回 0
    assert client.get(f"/api/tasks/{task_id}/deletion-impact").json()["deliverable_files"] == 0

    with sqlite3.connect(str(db_path)) as connection:
        connection.executemany(
            "INSERT INTO generations (task_id, plan_id, format, file_path, template_used, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (task_id, 1, "docx", "data/deliverables/a.docx", "corp.docx",
                 "2026-10-19T00:00:00+00:00"),
                (task_id, 1, "html", "data/deliverables/a.html", "odeck",
                 "2026-10-19T00:00:00+00:00"),
            ],
        )
        connection.commit()

    assert client.get(f"/api/tasks/{task_id}/deletion-impact").json()["deliverable_files"] == 2


# --- 任务状态机：已完成 / 重新打开 ----------------------------------------------


def test_task_status_transitions_between_in_progress_and_completed(client: TestClient) -> None:
    """状态机补全：进行中 ↔ 已完成可迁移，且迁移刷新 updated_at。"""
    created = client.post("/api/tasks", json={"kind": "creation", "title": "A"}).json()

    completed = client.post(f"/api/tasks/{created['id']}/status", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    reopened = client.post(f"/api/tasks/{created['id']}/status", json={"status": "in_progress"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "in_progress"


def test_task_status_rejects_deleted_and_unknown_values(client: TestClient) -> None:
    """删除不经状态迁移入口（避免绕过影响范围确认）；未知取值同样被拒。"""
    task = client.post("/api/tasks", json={"kind": "creation", "title": "A"}).json()

    assert (
        client.post(f"/api/tasks/{task['id']}/status", json={"status": "deleted"}).status_code
        == 422
    )
    assert (
        client.post(f"/api/tasks/{task['id']}/status", json={"status": "whatever"}).status_code
        == 422
    )


def test_deleted_task_cannot_change_status(client: TestClient) -> None:
    """已删除任务是留痕终态：再改状态 → 409；不存在的任务 → 404。"""
    task = client.post("/api/tasks", json={"kind": "creation", "title": "A"}).json()
    client.delete(f"/api/tasks/{task['id']}", params={"confirm": True})

    response = client.post(f"/api/tasks/{task['id']}/status", json={"status": "completed"})

    assert response.status_code == 409
    assert client.post("/api/tasks/9999/status", json={"status": "completed"}).status_code == 404


# --- 负测：模型失败不丢已存对话与方案 -------------------------------------------


def test_failed_advance_keeps_dialogue_and_open_items_then_retries(
    grilling_app,
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
) -> None:
    """推进时模型调用失败 → 502；已保存的对话与待确认事项完好、无半成品方案；
    模型恢复后重试成功，且方案只产出一份（可安全重试，规格 US 28）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": [None, "10 页以内"]},
    )
    dialogue_before = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()
    open_items_before = grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()

    # 模型调用失败（网络不可达）——真实客户端 httpx 直连的失败形态
    failing = ScriptedModelClient(error=httpx.ConnectError("connection refused"))
    grilling_app.dependency_overrides[get_model_client] = lambda: failing

    failed = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert failed.status_code == 502
    assert "模型调用失败" in failed.json()["detail"]
    # 已保存的对话与待确认事项一条不少
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json() == dialogue_before
    assert (
        grilling_client.get(f"/api/grilling/tasks/{task_id}/open-items").json()
        == open_items_before
    )
    # 失败没有产出半成品方案
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").status_code == 404

    # 模型恢复后重试：从同一份数据继续，方案恰好一份
    grilling_app.dependency_overrides[get_model_client] = lambda: scripted_model_client
    scripted_model_client.set_sequence(_empty_frontier_json(), PLAN_MD)

    retried = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert retried.status_code == 200
    assert retried.json()["converged"] is True
    assert retried.json()["plan"]["content_md"] == PLAN_MD
    assert grilling_client.get(f"/api/tasks/{task_id}/deletion-impact").json()["plans"] == 1


def test_failed_plan_generation_keeps_dialogue_and_plan_is_produced_once(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """收敛时方案生成失败（模型未返回内容）→ 502；对话完好、无方案行；
    重试后方案恰好一份，不重复产出无用结果。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
    )
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["答"]}
    )
    dialogue_before = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()

    # 前沿为空（收敛）→ 轮到方案生成这一步时模型返回空
    scripted_model_client.set_sequence(_empty_frontier_json(), "   ")
    failed = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert failed.status_code == 502
    assert "方案生成失败" in failed.json()["detail"]
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json() == dialogue_before
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").status_code == 404

    scripted_model_client.set_sequence(_empty_frontier_json(), PLAN_MD)
    retried = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert retried.status_code == 200
    assert retried.json()["plan"]["status"] == "draft"
    assert grilling_client.get(f"/api/tasks/{task_id}/deletion-impact").json()["plans"] == 1


def test_failed_first_round_keeps_task_and_seed_input(
    grilling_app, grilling_client: TestClient
) -> None:
    """首轮提问失败 → 502；任务与用户已给的种子输入仍落库（不丢用户输入）。"""
    failing = ScriptedModelClient(error=httpx.ConnectError("connection refused"))
    grilling_app.dependency_overrides[get_model_client] = lambda: failing

    response = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})

    assert response.status_code == 502
    assert "模型调用失败" in response.json()["detail"]

    tasks = grilling_client.get("/api/tasks").json()
    assert tasks["total"] == 1
    detail = grilling_client.get(f"/api/history/{tasks['items'][0]['id']}").json()
    assert detail["dialogue"]["seed_input"] == IDEA
    assert detail["dialogue"]["rounds"] == []


def test_failed_first_round_is_recovered_by_advance_exactly_once(
    grilling_app,
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
) -> None:
    """首轮失败（502、0 轮次）→ 历史页「继续」不再是空话：advance 生成第一轮。

    这是 TB-10 遗留 a 的回归测试：`derive_resume` 对 0 轮次任务给 `awaiting="advance"`，
    而旧实现下 `advance` 返回 422——前端显示「继续」、点进去必吃 422。
    可达路径：用户未配 Key 时发起创作 → 首轮 502 → 任务留在库里 0 轮次 → 点「继续」。

    修复后：**恰好产出一轮**（不重复、不叠加），`awaiting` 随之变成真话。
    """
    failing = ScriptedModelClient(error=httpx.ConnectError("connection refused"))
    grilling_app.dependency_overrides[get_model_client] = lambda: failing

    assert grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).status_code == 502
    task_id = grilling_client.get("/api/tasks").json()["items"][0]["id"]

    # 停在「该任务尚无任何轮次」：awaiting=advance，pending_round 为空
    stalled = grilling_client.get(f"/api/history/{task_id}").json()
    assert stalled["awaiting"] == "advance"
    assert stalled["pending_round"] is None
    assert stalled["dialogue"]["rounds"] == []

    # 模型恢复后点「继续」：生成第一轮（而不是 422）
    grilling_app.dependency_overrides[get_model_client] = lambda: scripted_model_client
    scripted_model_client.set_result(_frontier_json(("目标读者", "写给谁？", "新员工")))

    advanced = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert advanced.status_code == 200
    body = advanced.json()
    assert body["converged"] is False
    assert body["next_round"]["round_no"] == 1
    assert [question["title"] for question in body["next_round"]["frontier"]] == ["目标读者"]

    # 恰好一轮：不重复、不叠加
    rounds = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()["rounds"]
    assert [round_["round_no"] for round_ in rounds] == [1]
    assert len(rounds[0]["frontier"]) == 1

    # awaiting 变成真话：现在停在「第 1 轮待作答」
    resumed = grilling_client.get(f"/api/history/{task_id}").json()
    assert resumed["awaiting"] == "answers"
    assert resumed["pending_round"]["round_no"] == 1

    # 作答 → 推进收敛：轮次仍为 1（收敛不追加轮次），方案恰好一份
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    scripted_model_client.set_sequence(_empty_frontier_json(), PLAN_MD)
    converged = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert converged.status_code == 200
    assert converged.json()["converged"] is True
    assert converged.json()["plan"]["content_md"] == PLAN_MD
    assert len(grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()["rounds"]) == 1
    assert grilling_client.get(f"/api/tasks/{task_id}/deletion-impact").json()["plans"] == 1


def test_advance_without_rounds_and_empty_frontier_converges_into_draft_plan(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """0 轮次时推进：前沿为空即收敛，产出草稿方案（由种子输入产生，round_no 记 0）。

    与「前沿为空即收敛」的既有语义一致：绝不空转，也绝不让用户卡在一个没有出路的
    「继续」上（简单任务少问，极端情况可以 0 问直接收敛——规格 US 6）。
    """
    scripted_model_client.set_sequence(
        _empty_frontier_json(),  # 发起创作：首轮即前沿为空（0 轮次）
        _empty_frontier_json(),  # 推进：等价于发起第一轮，仍无问题 → 收敛
        PLAN_MD,
    )
    started = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})
    task_id = started.json()["task"]["id"]
    assert started.json()["round"]["frontier"] == []

    response = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert response.status_code == 200
    body = response.json()
    assert body["converged"] is True
    assert body["next_round"] is None
    assert body["plan"]["content_md"] == PLAN_MD
    assert body["plan"]["status"] == "draft"
    assert body["plan"]["round_no"] == 0  # 方案由种子输入（第 0 轮）产生
    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()["rounds"] == []


def test_advance_on_task_without_any_input_still_rejected(client: TestClient) -> None:
    """没有任何输入的任务（直接建任务、无种子输入）推进仍为 422：没有可据以提问的内容。"""
    task_id = client.post("/api/tasks", json={"kind": "creation", "title": "空任务"}).json()["id"]

    response = client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert response.status_code == 422
    assert "尚无" in response.json()["detail"]


# --- schema 迁移：历史版本的库补列后照常可用 ------------------------------------


def test_existing_database_is_migrated_for_delete_trace(tmp_path: Path) -> None:
    """老库（`tasks` 无 `deleted_at`）启动时补列——历史与删除在既有库上照常可用。"""
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(str(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE tasks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                kind       TEXT NOT NULL,
                title      TEXT,
                status     TEXT NOT NULL DEFAULT 'in_progress',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO tasks (kind, title, status, created_at, updated_at) "
            "VALUES ('creation', '旧库任务', 'in_progress', ?, ?)",
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as client:
        assert client.get("/api/history").json()["total"] == 1

        deleted = client.delete("/api/tasks/1", params={"confirm": True})

        assert deleted.status_code == 200
        assert deleted.json()["deleted_at"]