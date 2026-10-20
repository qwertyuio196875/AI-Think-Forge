"""前沿问题的解析与序列化。

模型输出契约（见提示词资产 grilling_v2.md）：
    {"frontier": [{"title", "body", "recommended_answer", "why", "alternatives"}, ...]}

解析刻意做防御性处理：容忍模型偶尔包裹说明文字或 Markdown 代码围栏；结构不合法
（尤其缺 `recommended_answer`）一律抛 `FrontierParseError`，由 API 层转为可读错误，
绝不把半成品问题塞进对话。

`why` 与 `alternatives` 是 `grilling-v2` 的新增字段：**提示词要求模型给出，
解析层对缺失容错**（由 `FrontierQuestion` 的字段校验器归一为 `None` / `[]`）。
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.grilling.prompts import MAX_FRONTIER_QUESTIONS
from app.models.grilling import FrontierQuestion


class FrontierParseError(ValueError):
    """模型输出无法解析为合法的前沿问题集。"""


def _extract_json_object(text: str) -> str:
    """从可能夹带说明文字或代码围栏的输出中截出最外层 JSON 对象。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise FrontierParseError("输出中找不到完整的 JSON 对象（可能被截断）")
    return text[start : end + 1]


def parse_frontier(text: str) -> list[FrontierQuestion]:
    """把模型输出解析为前沿问题集；超过每轮上限时按上限截断。"""
    payload = _extract_json_object(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        # 截断的 JSON 往往在最后一个字符附近报「Expecting ',' delimiter」；
        # 明确提示截断，避免用户误以为是模型“不会写 JSON”。
        hint = "（模型输出可能被长度上限截断，请重试）" if exc.pos >= len(payload) - 2 else ""
        raise FrontierParseError(f"JSON 解析失败：{exc}{hint}") from exc

    if not isinstance(data, dict) or "frontier" not in data:
        raise FrontierParseError("输出缺少 frontier 字段")
    raw = data["frontier"]
    if not isinstance(raw, list):
        raise FrontierParseError("frontier 必须是数组")

    try:
        questions = [FrontierQuestion(**item) for item in raw]
    except (TypeError, ValidationError) as exc:
        raise FrontierParseError(f"问题结构不合法：{exc}") from exc
    return questions[:MAX_FRONTIER_QUESTIONS]


def frontier_to_content(questions: list[FrontierQuestion]) -> str:
    """把问题集序列化为 assistant 消息的 content（结构化 JSON）。"""
    return json.dumps({"frontier": [q.model_dump() for q in questions]}, ensure_ascii=False)


def frontier_from_content(content: str) -> list[FrontierQuestion]:
    """从 assistant 消息 content 还原问题集（用于复原对话流）。"""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise FrontierParseError(f"消息内容不是合法 JSON：{exc}") from exc
    return [FrontierQuestion(**item) for item in data.get("frontier", [])]