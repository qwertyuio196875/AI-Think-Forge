"""TB-3 收敛 → 结构化方案 → 确认闸门：接缝测试（唯一接缝 = 进程内 HTTP；模型走 fake）。

对应工单 12 的窄路径与规格 User Stories 6~10：
- 简单任务少轮收敛：前沿为空即停止并产出结构化方案草稿；
- 复杂任务动态追问：下一轮问题按上一轮回答重算，而非固定问题集；
- 未确认不得生成：生成入口在方案未确认时被服务端拒绝（负测）；
- 方案确认：draft → confirmed 的状态迁移与 confirmed_at 落库；
- 确认后状态可被下游读取：生成入口放行、方案状态可复原。

语义质量不做自动化断言（规格 Testing Decisions）——只断言状态、持久化与闸门。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.main import create_app

IDEA = "帮我准备一份面向新员工的产品培训"

# 结构化方案草稿：结构灵活（不强求固定章节），未确认推测只落在「待确认事项」。
PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 核心观点\n从场景切入，而非功能罗列。\n\n"
    "## 章节\n1. 产品定位　2. 核心场景　3. 常见问题\n\n"
    "## 执行步骤\n先定大纲，再补案例。\n\n"
    "## 关键约束\n篇幅 10 页以内。\n\n"
    "## 风险\n案例不足会显得空泛。\n\n"
    "## 待确认事项\n- 是否需要配套练习？（未确认的推测）\n\n"
    "## 输出要求\nWord 文档。"
)


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    """按输出契约拼装脚本化前沿应答。"""
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


def _answer(client: TestClient, task_id: int, round_no: int, answers: list[str]) -> None:
    response = client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": round_no, "answers": answers},
    )
    assert response.status_code == 200


# --- 简单任务少轮收敛 ----------------------------------------------------------


def test_simple_task_converges_into_draft_plan(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """简单任务：一轮问答后前沿为空即收敛，产出结构化方案草稿（draft）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["新员工", "10 页以内"])

    response = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert response.status_code == 200
    body = response.json()
    assert body["converged"] is True
    assert body["next_round"] is None
    plan = body["plan"]
    assert plan["task_id"] == task_id
    assert plan["status"] == "draft"
    assert plan["confirmed_at"] is None
    assert plan["content_md"] == PLAN_MD
    # 方案与轮次关联：由触发收敛的那一轮（第 1 轮）产生
    assert plan["round_no"] == 1

    # 无前沿可问 → 不再产生新的 assistant 提问消息
    dialogue = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()
    assert [r["round_no"] for r in dialogue["rounds"]] == [1]


def test_draft_plan_is_readable(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """收敛后方案可经 GET 读回（草稿态）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["答"])

    created = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance").json()["plan"]

    fetched = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]
    assert fetched.json()["content_md"] == PLAN_MD


def test_plan_missing_returns_404(grilling_client: TestClient) -> None:
    """尚无方案的读取与确认 → 404。"""
    started = grilling_client.post("/api/grilling/tasks", json={"idea": "还没收敛"})
    task_id = started.json()["task"]["id"]

    assert grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").status_code == 404
    assert (
        grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 404
    )


# --- 复杂任务动态追问 ----------------------------------------------------------


def test_next_round_is_recomputed_from_prior_answers(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """复杂任务：下一轮问题按上一轮回答重算，而非固定问题集。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("目标读者", "写给谁？", "新员工"), ("篇幅", "多长？", "10 页")),
        _frontier_json(("案例来源", "用哪些真实案例？", "内部项目"), ("练习形式", "要不要练习？", "不做")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["新员工", "10 页以内"])

    response = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert response.status_code == 200
    body = response.json()
    assert body["converged"] is False
    next_round = body["next_round"]
    assert next_round["round_no"] == 2
    # 第二轮问题来自新一次模型调用（随上轮回答变化），而非沿用第一轮
    assert [q["title"] for q in next_round["frontier"]] == ["案例来源", "练习形式"]

    # 动态重算的证据：第二轮的提示词里带上了第一轮的问与答（已确定决策）
    second_call = scripted_model_client.calls[1]
    sent = " ".join(m["content"] for m in second_call["messages"])
    assert "目标读者" in sent and "新员工" in sent
    assert "篇幅" in sent and "10 页以内" in sent

    # 第二轮问题落库，可复原
    dialogue = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()
    assert [r["round_no"] for r in dialogue["rounds"]] == [1, 2]
    assert [q["title"] for q in dialogue["rounds"][1]["frontier"]] == ["案例来源", "练习形式"]


def test_advance_before_any_answer_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """尚无任何轮次问答时推进 → 422（没有可据以重算的上一轮）。"""
    started = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})
    task_id = started.json()["task"]["id"]

    response = grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    assert response.status_code == 422


# --- 方案确认：draft → confirmed 的状态迁移 ------------------------------------


def test_confirm_transitions_draft_to_confirmed_and_records_time(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """显式确认：状态 draft → confirmed，并记录 confirmed_at（落库可复原）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["答"])
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    response = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_at"]

    # 重复确认保持幂等，confirmed_at 不漂移
    again = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").json()
    assert again["confirmed_at"] == confirmed["confirmed_at"]


def test_confirm_missing_task_returns_404(grilling_client: TestClient) -> None:
    """对不存在任务的确认 → 404。"""
    assert (
        grilling_client.post("/api/grilling/tasks/9999/plan/confirm").status_code == 404
    )


def test_confirmed_plan_survives_restart(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    db_path: Path,
) -> None:
    """确认后重建 app 与客户端再读：状态 confirmed、confirmed_at 仍在（重启续作）。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["答"])
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")
    confirmed = grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").json()

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        reread = rebuilt.get(f"/api/grilling/tasks/{task_id}/plan")

    assert reread.status_code == 200
    assert reread.json() == confirmed


# --- 硬闸门：确认前拒绝任何生成请求 -------------------------------------------


def test_generation_before_confirmation_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案处于 draft（未确认）时，生成入口必须拒绝——不能只靠前端不显示按钮。"""
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["答"])
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    response = grilling_client.post(f"/api/tasks/{task_id}/generations")

    assert response.status_code == 409


def test_generation_without_plan_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """连方案都没有的任务请求生成 → 拒绝（409）。"""
    started = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})
    task_id = started.json()["task"]["id"]

    response = grilling_client.post(f"/api/tasks/{task_id}/generations")

    assert response.status_code == 409


def test_generation_for_missing_task_returns_404(grilling_client: TestClient) -> None:
    """不存在任务的生成请求 → 404。"""
    assert grilling_client.post("/api/tasks/9999/generations").status_code == 404


def test_generation_gate_opens_after_confirmation(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """确认后闸门放行：下游读到「已确认」，不再被 409 拦截。

    生成管线本身归 TB-5/TB-6，本单只保证闸门判定；放行后以 501 明确「能力待落地」。
    """
    task_id = _start(
        grilling_client,
        scripted_model_client,
        _frontier_json(("Q", "正文", "推荐")),
        _empty_frontier_json(),
        PLAN_MD,
    )
    _answer(grilling_client, task_id, 1, ["答"])
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")
    grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    response = grilling_client.post(f"/api/tasks/{task_id}/generations")

    assert response.status_code == 501