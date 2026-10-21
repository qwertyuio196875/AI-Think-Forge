"""命中位置的翻译（工单 21 / ADR-0005）。

分块器把解析器给出的 `locator` 原样写进 `document_chunks.locator_json`：
DOCX 是 `{format, paragraph}`、PDF 是 `{format, page, line}`、PPTX 是
`{format, slide, shape}`、MD / TXT 是 `{format, line}` 或 `{format, block}`；
跨块合并时是 `{format, start: {...}, end: {...}}`，超长块二次切分时多一个 `part`。

本模块**不重新解析文档**，只把这些既有字段翻成一句可读的位置，供引用卡片与
参考资料清单使用。位置字段的优先级就是引用卡片上的口径：页 → 幻灯片 → 段落 →
行 → 块。
"""

from __future__ import annotations

from typing import Any

from app.retrieval.models import LocatorInfo

# (字段名, 中文模板)；顺序即优先级。
_POSITION_FIELDS: tuple[tuple[str, str], ...] = (
    ("page", "第 {value} 页"),
    ("slide", "第 {value} 张幻灯片"),
    ("paragraph", "第 {value} 段"),
    ("line", "第 {value} 行"),
    ("block", "第 {value} 块"),
)

_UNKNOWN_LABEL = "未标注位置"


def describe_locator(locator: dict[str, Any] | None) -> LocatorInfo:
    """把 `locator` 翻成 `LocatorInfo`；字段缺失就给 `None` 与「未标注位置」。"""
    data = _merged_locator(locator)
    return LocatorInfo(
        format=str(data.get("format") or ""),
        label=_position_label(data),
        paragraph=_positive_int(data.get("paragraph")),
        line=_positive_int(data.get("line")),
        page=_positive_int(data.get("page")),
        slide=_positive_int(data.get("slide")),
    )


def _merged_locator(locator: dict[str, Any] | None) -> dict[str, Any]:
    """块级 locator 展开成扁平字段；`start` / `end` 只取起点并保留外层 `part`。"""
    data = dict(locator or {})
    start = data.get("start")
    if isinstance(start, dict):
        merged = {key: value for key, value in data.items() if key not in ("start", "end")}
        merged.update({key: value for key, value in start.items() if value is not None})
        if not merged.get("format"):
            merged["format"] = data.get("format")
        return merged
    return data


def _position_label(data: dict[str, Any]) -> str:
    """按优先级取第一个有效位置；超长块二次切分时补「第 N 部分」。"""
    part = _positive_int(data.get("part"))
    suffix = f"（第 {part} 部分）" if part is not None else ""
    for field, template in _POSITION_FIELDS:
        value = _positive_int(data.get(field))
        if value is not None:
            return template.format(value=value) + suffix
    return _UNKNOWN_LABEL + suffix


def _positive_int(value: Any) -> int | None:
    """只认正整数（`bool` 不算，避免 `True` 被当成第 1 段）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None
