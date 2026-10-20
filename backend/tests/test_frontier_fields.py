"""TB-4 增补：前沿问题的「为什么现在问」与「备选方向」：接缝测试（进程内 HTTP；模型走 fake）。

对应规格 User Story 5（系统主动指出模糊点、遗漏、矛盾、风险与未经确认的假设；
我不确定时给我备选方向）与编排约定「原型对齐缺口」表的 `.q-why` / `.alt` 两栏：

- 前沿问题结构新增 `why`（为什么现在问）与 `alternatives`（备选方向）；
- 输出契约为版本化提示词资产 `grilling-v2`，按 ADR-0001 显式记录这次变更（升版本，非静默走样）；
- 解析层对缺失字段**容错**（缺失不报错，落 `None` / `[]`），但提示词结构上要求模型给出。

语义质量不做自动化断言（规格 Testing Decisions）——只断言解析、落库与提示词契约。
"""

from __future__ import annotations

import json

import pytest
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.grilling import prompts
from app.grilling.frontier import FrontierParseError, parse_frontier

IDEA = "帮我准备一份面向新员工的产品培训"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    """按输出契约拼装脚本化模型应答（不含 TB-4 新增字段）。"""
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


# --- 提示词资产：升版本并显式记录变更 -------------------------------------------


def test_prompt_asset_v2_declares_why_and_alternatives() -> None:
    """前沿提示词资产升到 grilling-v2，输出契约声明 `why` 与 `alternatives`。"""
    assert prompts.GRILLING_PROMPT_VERSION == "grilling-v2"

    asset = prompts.load_asset()

    assert "why" in asset
    assert "alternatives" in asset
    assert "为什么现在问" in asset  # 原型 `.q-why` 的语义
    assert "备选方向" in asset  # 原型 `.alt` 的语义 / 规格 US 5
    assert "Matt Pocock" in asset and "MIT" in asset  # 署名不丢
    assert "偏离" in asset  # 变更须显式记录（ADR-0001）


def test_previous_prompt_version_is_kept() -> None:
    """旧版本资产保留可读（提示词版本化是「旧版本不丢」的纪律）。"""
    v1 = prompts.load_asset("grilling-v1")

    assert "frontier" in v1
    assert "why" not in v1  # v1 的输出契约尚无该字段


def test_truncated_frontier_json_reports_truncation_hint() -> None:
    """输出被长度上限截断时，错误文案提示截断而不是只报 JSON 语法错。"""
    raw = (
        '{"frontier": [{"title": "目标", "body": "第一题完整"},'
        ' {"title": "第二题", "body": "写到一半'
    )

    with pytest.raises(FrontierParseError, match="截断"):
        parse_frontier(raw)


# --- 解析与返回：新增字段 -------------------------------------------------------


def test_frontier_questions_carry_why_and_alternatives(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """模型给出的 `why` 与 `alternatives` 被解析并原样返回给前端。"""
    scripted_model_client.set_result(
        json.dumps(
            {
                "frontier": [
                    {
                        "title": "目标读者",
                        "body": "这份内容写给谁？",
                        "recommended_answer": "新入职员工",
                        "why": "目标读者是其余章节的前置条件，决定全篇语气与案例选择",
                        "alternatives": ["新入职员工", "一线主管", "全体员工"],
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    response = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})

    assert response.status_code == 201
    question = response.json()["round"]["frontier"][0]
    assert question["why"] == "目标读者是其余章节的前置条件，决定全篇语气与案例选择"
    assert question["alternatives"] == ["新入职员工", "一线主管", "全体员工"]


def test_frontier_round_trip_keeps_new_fields(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """新字段经落库（assistant 消息 JSON）后仍可复原。"""
    scripted_model_client.set_result(
        json.dumps(
            {
                "frontier": [
                    {
                        "title": "篇幅",
                        "body": "期望多长？",
                        "recommended_answer": "10 页以内",
                        "why": "篇幅决定章节取舍",
                        "alternatives": ["5 页", "10 页以内", "20 页"],
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["10 页以内"]},
    )

    round_one = grilling_client.get(f"/api/grilling/tasks/{task_id}/dialogue").json()["rounds"][0]
    question = round_one["frontier"][0]
    assert question["why"] == "篇幅决定章节取舍"
    assert question["alternatives"] == ["5 页", "10 页以内", "20 页"]


# --- 容错：缺失字段不阻断本轮 ------------------------------------------------


def test_missing_why_and_alternatives_are_tolerated(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """模型偶尔漏字段时容错：`why` 落 None、`alternatives` 落空列表，本轮照常成立。"""
    scripted_model_client.set_result(_frontier_json(("Q", "正文", "推荐")))

    response = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA})

    assert response.status_code == 201
    question = response.json()["round"]["frontier"][0]
    assert question["why"] is None
    assert question["alternatives"] == []


def test_blank_why_and_alternatives_entries_are_normalized(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """空串 `why` 归一为 None；`alternatives` 里的空条目被剔除。"""
    scripted_model_client.set_result(
        json.dumps(
            {
                "frontier": [
                    {
                        "title": "Q",
                        "body": "正文",
                        "recommended_answer": "推荐",
                        "why": "   ",
                        "alternatives": ["选项一", "", "   "],
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    question = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["round"][
        "frontier"
    ][0]

    assert question["why"] is None
    assert question["alternatives"] == ["选项一"]