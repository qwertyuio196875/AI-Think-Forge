"""TB-2 拷问第一轮：接缝测试（唯一接缝 = 进程内 HTTP；模型走 fake）。

对应规格 §2/§4 与工单 11 的窄路径：
- 第一轮「前沿」问题集：1~N 个相互独立问题、每题附推荐答案；
- 提示词渲染必须包含用户已提供的输入（「不重复询问已知信息」）；
- 提问与回答按 round_no + 顺序正确落库、可复原；
- 「前沿为空 → 不再提问」的收敛分支可被触发；
- 每题附推荐答案由结构强制（缺字段被拒），不靠模型自觉。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.grilling import prompts
from app.main import create_app

IDEA = "帮我准备一份面向新员工的产品培训"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    """按输出契约拼装脚本化模型应答。"""
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


# --- 提示词资产（版本化 + MIT 署名 + 显式偏离）-----------------------------------


def test_prompt_asset_is_versioned_with_attribution_and_deviations() -> None:
    """提示词资产带版本号、MIT 署名，并显式记录移植偏离。"""
    assert prompts.GRILLING_PROMPT_VERSION == "grilling-v1"

    asset = prompts.load_asset()

    assert "Matt Pocock" in asset  # 署名：基于原 grilling 技能规则适配
    assert "MIT" in asset
    assert "偏离" in asset  # 偏离须显式记录（ADR-0001）
    assert "简体中文" in asset
    assert 1 <= prompts.MAX_FRONTIER_QUESTIONS <= 10


# --- 第一轮前沿 ----------------------------------------------------------------


def test_start_creates_task_and_first_round_frontier(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """一句话发起 → 建 creation 任务 + 第一轮相互独立、各带推荐答案的前沿问题集。"""
    scripted_model_client.set_result(
        _frontier_json(
            ("目标读者", "这份内容写给谁？", "新入职员工"),
            ("篇幅", "期望多长？", "10 页以内"),
        )
    )

    response = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})

    assert response.status_code == 201
    body = response.json()
    assert body["task"]["kind"] == "creation"
    assert body["task"]["status"] == "in_progress"
    assert body["task"]["title"] == IDEA

    frontier = body["round"]["frontier"]
    assert body["round"]["round_no"] == 1
    assert 1 <= len(frontier) <= prompts.MAX_FRONTIER_QUESTIONS
    # 相互独立：标题互不相同
    assert len({q["title"] for q in frontier}) == len(frontier)
    # 每题必须带推荐答案
    assert all(q["recommended_answer"].strip() for q in frontier)
    # 模型名走默认 provider（DeepSeek 主流程播种值）
    assert scripted_model_client.calls[0]["model"] == "deepseek-flash"


def test_prompt_rendering_contains_user_known_input(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """提示词必须把用户原始输入作为「已知信息」喂进去（不重复询问已知信息）。"""
    scripted_model_client.set_result(_frontier_json(("Q", "正文", "推荐")))

    grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})

    sent = " ".join(
        message["content"]
        for call in scripted_model_client.calls
        for message in call["messages"]
    )
    assert IDEA in sent
    assert "已知信息" in sent


def test_frontier_is_capped_at_max(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """模型返回超过上限的问题数时，按上限截断（数量恒在 1~N）。"""
    scripted_model_client.set_result(
        _frontier_json(*[(f"Q{i}", "正文", "推荐") for i in range(1, 8)])
    )

    frontier = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["round"][
        "frontier"
    ]

    assert len(frontier) == prompts.MAX_FRONTIER_QUESTIONS


def test_question_without_recommended_answer_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """缺推荐答案 → 结构校验失败（502），证明「每题附推荐答案」由结构强制。"""
    scripted_model_client.set_result(json.dumps({"frontier": [{"title": "T", "body": "B"}]}))

    response = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})

    assert response.status_code == 502


# --- 回答落库与复原 ------------------------------------------------------------


def test_answers_round_trip_in_order_and_survive_rebuild(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """回答按 round_no + 顺序落库，重建 app 与客户端后仍可复原。"""
    scripted_model_client.set_result(_frontier_json(("A", "qa", "ra"), ("B", "qb", "rb")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["答A", "答B"]},
    )

    assert response.status_code == 200
    dialogue = response.json()
    assert dialogue["seed_input"] == IDEA
    assert [(m["round_no"], m["role"]) for m in dialogue["messages"]] == [
        (0, "user"),
        (1, "assistant"),
        (1, "user"),
        (1, "user"),
    ]
    assert len(dialogue["rounds"]) == 1
    round_one = dialogue["rounds"][0]
    assert round_one["round_no"] == 1
    assert [q["title"] for q in round_one["frontier"]] == ["A", "B"]
    assert round_one["answers"] == ["答A", "答B"]

    # 重建 app 与客户端（不注入 fake，GET 不触模型）后再读，回答仍在
    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        reread = rebuilt.get(f"/api/grilling/tasks/{task_id}/dialogue")

    assert reread.status_code == 200
    assert reread.json() == dialogue


def test_submit_answers_count_must_match_frontier(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """回答数量与前沿问题数量不一致 → 422。"""
    scripted_model_client.set_result(_frontier_json(("A", "qa", "ra"), ("B", "qb", "rb")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    response = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["只有一条"]},
    )

    assert response.status_code == 422


def test_dialogue_for_missing_task_returns_404(grilling_client: TestClient) -> None:
    """读取不存在任务的对话 → 404。"""
    assert grilling_client.get("/api/grilling/tasks/9999/dialogue").status_code == 404


# --- 收敛：前沿为空即停止 ------------------------------------------------------


def test_empty_frontier_stops_asking(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """前沿为空 → 不再提问：不产生 assistant 提问消息，对话仅含种子输入。"""
    scripted_model_client.set_result(json.dumps({"frontier": []}))

    started = grilling_client.post("/api/grilling/tasks", json={"idea": "已经很清楚了"})
    assert started.status_code == 201
    assert started.json()["round"]["frontier"] == []

    dialogue = grilling_client.get(
        f"/api/grilling/tasks/{started.json()['task']['id']}/dialogue"
    ).json()

    assert dialogue["rounds"] == []
    assert dialogue["seed_input"] == "已经很清楚了"
    assert [m["role"] for m in dialogue["messages"]] == ["user"]