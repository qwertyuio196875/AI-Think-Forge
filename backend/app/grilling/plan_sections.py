"""成品章节解析：从方案「章节」一节解析出章节清单（工单 6 / ADR-0006）。

术语（GLOSSARY）：**方案分节**是方案里的 `##` 级段落（目标、读者、章节……）；
**成品章节**是成品正文的章，其清单只来自方案「章节」那一节里的条目。
二者不可互换——所以本模块只认「章节」这一节内部的条目，**不拿 `##` 切分结果当成品目录**。

这是下游工单 7（章节表与章节切分）与工单 9（填充闸门）的唯一入口：

    from app.grilling.plan_sections import parse_plan_sections
    sections = parse_plan_sections(plan.content_md)

`plan-v3` 提示词（`app.grilling.prompts.plan_v3.md`）把「章节」一节固定为「每章一行：
标题 + 要点 + 建议字数」。历史方案的 `content_md` 是 `plan-v2` 格式，必须仍然能读：

- 解析不出建议字数 → `suggested_length is None`，由下游按缺省权重处理；
- 解析不出章节条目（没有这一节、这一节是叙述而非条目、或整方案无可切分章节）
  → 返回**空清单**，绝不抛异常（工单 7 验收：没有可切分章节时返回空清单而不是报错）。

「解析不出」的判据是显式的，不做猜测：既不按标题层级退化切分，也不把正文段落猜成章节。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# 「章节」这一节的方案分节标题。模型偶尔会带括注（如「章节（成品目录）」），
# 只接受括注式变体，不接受「章节安排」「分章节」这类含义已经走样的标题。
_SECTION_HEADING_RE = re.compile(r"^章节([（(][^）)]*[）)])?$")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

# 条目行首的列表符号：`-` / `*` / `+` / `1.` / `1、`。
_BULLET_RE = re.compile(r"^[-*+]\s+")
_NUMBERED_RE = re.compile(r"^\d+[.、)]\s*")

# 三段的分隔符：提示词要求全角竖线，模型常写半角；两种都收。
_FIELD_SPLIT_RE = re.compile(r"[｜|]")

_FIELD_TITLE = "标题"
_FIELD_POINTS = "要点"
_FIELD_LENGTH = "建议字数"

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_DIGITS_RE = re.compile(r"\d+")

# 单行条目解析器：`(行文本, 序号) -> PlanSection | None`。
# v3 严格格式与 v2 宽松格式各一个，这样降级路径是显式的两个函数，而不是一堆 if。
_EntryParser = Callable[[str, int], "PlanSection | None"]


@dataclass(frozen=True)
class PlanSection:
    """方案「章节」一节里的一个条目——成品章节的唯一来源。

    字段命名对齐规格 §5 的成品章节表：`seq` 即序号（按条目行序生成，从 1 开始），
    `title` / `key_points` / `suggested_length` 对应标题 / 要点 / 建议字数。
    `suggested_length` 为 `None` 表示旧格式方案没写建议字数，调用方按缺省权重处理。
    """

    seq: int
    title: str
    key_points: str = ""
    suggested_length: int | None = None


def parse_plan_sections(content_md: str) -> list[PlanSection]:
    """解析方案「章节」一节的条目清单；解析不出时返回空清单（不抛异常）。"""
    if not content_md:
        return []

    lines = _chapter_section_lines(content_md)

    # 先按 plan-v3 的固定格式读；读不到任何一条时才退回旧格式的宽松读法。
    # 顺序很重要：新格式方案里偶有多余的说明性条目，不该被当成章节。
    sections = _collect(lines, parser=_parse_entry)
    if sections:
        return sections
    return _collect(lines, parser=_parse_legacy_entry)


def _collect(lines: list[str], *, parser: _EntryParser) -> list[PlanSection]:
    """按行序解析条目并补上序号；不构成条目的行直接跳过。"""
    sections: list[PlanSection] = []
    for line in lines:
        section = parser(line, len(sections) + 1)
        if section is not None:
            sections.append(section)
    return sections


def _chapter_section_lines(content_md: str) -> list[str]:
    """取出「章节」这一节的正文行（不含标题行），到下一个同级或更高级标题为止。"""
    lines: list[str] = []
    inside = False
    section_level = 0

    for raw in content_md.splitlines():
        heading = _HEADING_RE.match(raw)
        if heading is not None:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            if inside and level <= section_level:
                break
            if not inside and _SECTION_HEADING_RE.match(_strip_emphasis(text)):
                inside = True
                section_level = level
                continue
            if inside:
                # 更深的标题仍属于本节内容（例如「### 第一章」），但不构成章节条目。
                lines.append(raw)
            continue
        if inside:
            lines.append(raw)

    return lines


def _parse_entry(line: str, seq: int) -> PlanSection | None:
    """解析 plan-v3 的一行条目；不是条目（空行、说明文字、无标题）就返回 None。"""
    text = _strip_list_marker(line)
    if text is None or not _starts_with_field(text, _FIELD_TITLE):
        return None

    fields: dict[str, str] = {}
    for segment in _FIELD_SPLIT_RE.split(text):
        key, value = _split_field(segment)
        if key is not None:
            fields.setdefault(key, value)

    title = fields.get(_FIELD_TITLE, "").strip()
    if not title:
        return None

    return PlanSection(
        seq=seq,
        title=title,
        key_points=fields.get(_FIELD_POINTS, "").strip(),
        suggested_length=_parse_length(fields.get(_FIELD_LENGTH, "")),
    )


def _parse_legacy_entry(line: str, seq: int) -> PlanSection | None:
    """解析 plan-v2 的一行条目：`- 标题：要点`（没有建议字数）。

    旧格式没有字段标签，只能取「行首到第一个冒号」当标题、其余当要点；
    保守起见只认列表行——正文段落绝不猜成章节。
    """
    text = _strip_list_marker(line)
    if text is None:
        return None
    if _starts_with_field(text, _FIELD_TITLE):
        # 已经写成 v3 形状却没有建议字数，直接用 v3 解析的结果（长度为空）。
        return _parse_entry(line, seq)

    title_part, separator, points = _split_once_at_colon(text)
    if not separator:
        return None
    title = _strip_emphasis(title_part)
    if not title:
        return None

    return PlanSection(seq=seq, title=title, key_points=points.strip())


def _strip_list_marker(line: str) -> str | None:
    """去掉行首的列表符号并返回正文；不是列表行时返回 None。"""
    text = line.strip()
    if not text:
        return None
    for pattern in (_BULLET_RE, _NUMBERED_RE):
        if pattern.match(text):
            stripped = pattern.sub("", text).strip()
            return stripped or None
    return None


def _starts_with_field(text: str, label: str) -> bool:
    """判断正文是否以某个字段标签开头（全角或半角冒号都算）。"""
    return any(text.startswith(f"{label}{colon}") for colon in ("：", ":"))


def _split_once_at_colon(text: str) -> tuple[str, str, str]:
    """在第一个冒号处切成 (前, 冒号, 后)；没有冒号时返回 (text, "", "")。"""
    positions = [index for index in (text.find("："), text.find(":")) if index >= 0]
    if not positions:
        return text, "", ""
    index = min(positions)
    return text[:index], text[index], text[index + 1 :]


def _split_field(segment: str) -> tuple[str | None, str]:
    """把「标签：值」拆开；标签不是已知三段之一时返回 (None, "")。"""
    stripped = segment.strip()
    for label in (_FIELD_TITLE, _FIELD_POINTS, _FIELD_LENGTH):
        if _starts_with_field(stripped, label):
            return label, stripped[len(label) + 1 :]
    return None, ""


def _parse_length(value: str) -> int | None:
    """从「建议字数」里取整数；旧格式没写或写成非数字时返回 None。"""
    match = _DIGITS_RE.search(value.translate(_FULLWIDTH_DIGITS))
    if match is None:
        return None
    number = int(match.group())
    return number if number > 0 else None


def _strip_emphasis(text: str) -> str:
    """去掉标题里的 `**` / `*` / 反引号装饰，再判断是不是「章节」一节。"""
    return text.strip().strip("*`_ ").strip()
