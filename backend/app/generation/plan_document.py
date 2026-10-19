"""结构化方案 Markdown → 成品文档的块序列。

成品生成只做**确定性渲染**（不调用模型）：把方案正文（`plans.content_md`，Markdown）
解析为块序列，再按模板样式写入 Word。方案结构随任务类型裁剪，故解析必须容错：
识别不了的整行按正文段落处理，绝不丢内容。

标题级别上限 3：内置最小默认模板只定义 `Heading 1~3`（工单 14），更深的 `####+`
归入第 3 级，避免映射到模板里不存在的样式（调研 A2 陷阱 2）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

BlockKind = Literal["heading", "paragraph", "bullet", "numbered", "table"]

MAX_HEADING_LEVEL = 3

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.*)$")
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
_TABLE_DIVIDER = re.compile(r"^\|[\s:|-]+\|\s*$")


@dataclass(frozen=True)
class Block:
    """成品文档的一个块：标题 / 正文段落 / 列表项 / 表格。"""

    kind: BlockKind
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()


def parse_plan_blocks(content_md: str) -> list[Block]:
    """把方案正文解析为块序列（标题 / 正文 / 列表 / 表格）。"""
    blocks: list[Block] = []
    lines = content_md.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        table_rows, consumed = _read_table(lines, index)
        if table_rows:
            blocks.append(Block(kind="table", rows=table_rows))
            index += consumed
            continue

        heading = _HEADING.match(stripped)
        if heading:
            text = heading.group(2).strip()
            if text:
                blocks.append(
                    Block(kind="heading", text=text, level=min(len(heading.group(1)), MAX_HEADING_LEVEL))
                )
            index += 1
            continue

        bullet = _BULLET.match(stripped)
        if bullet:
            blocks.append(Block(kind="bullet", text=bullet.group(1).strip()))
            index += 1
            continue

        numbered = _NUMBERED.match(stripped)
        if numbered:
            blocks.append(Block(kind="numbered", text=numbered.group(1).strip()))
            index += 1
            continue

        blocks.append(Block(kind="paragraph", text=stripped))
        index += 1

    return blocks


def _read_table(lines: list[str], start: int) -> tuple[tuple[tuple[str, ...], ...], int]:
    """从 `start` 起读取连续 Markdown 表格行；不构成表格时返回空元组与 0。"""
    if not _TABLE_ROW.match(lines[start].strip()):
        return (), 0

    rows: list[tuple[str, ...]] = []
    index = start
    while index < len(lines) and _TABLE_ROW.match(lines[index].strip()):
        if not _TABLE_DIVIDER.match(lines[index].strip()):
            cells = tuple(cell.strip() for cell in lines[index].strip().strip("|").split("|"))
            rows.append(cells)
        index += 1

    if not rows:
        return (), 0
    return tuple(rows), index - start


def heading_count(blocks: list[Block]) -> int:
    """块序列里的标题数（完整性检查断言用）。"""
    return sum(1 for block in blocks if block.kind == "heading")