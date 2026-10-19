"""文本类资料的解析（TXT / MD / DOCX）：正文、标题与基本结构。

选型与判据来自调研笔记 A1 / A5（`02-parsing-and-opendesign.md`）：

- TXT 编码顺序 `utf-8-sig` → `gb18030` → `charset-normalizer`，并把实际探测到的
  编码回传（前端可提示「检测到 GB18030」）。先严格解码、失败后才上探测器。
- MD 标题走 `markdown-it-py` 的 token 流，**不用正则**——正则会把代码围栏内的
  `#` 误判为标题。
- DOCX 用 `python-docx` 读 `paragraph.style.name` 判标题；作者手写加粗放大而不用
  内置样式时退回启发式，并在解析产物里标注 `heading_source`（style / heuristic / none）。
  图片、SmartArt、图表内文字、文本框浮动内容不进 `paragraphs`，读不到 → 归入未识别。

本模块只负责「能不能从文件里读出结构化的块」；「读不出来」一律显式返回
`unrecognized`，**绝不用空字符串冒充解析成功**（调研 A6）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import charset_normalizer
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from markdown_it import MarkdownIt

# 本单接受的后缀（PDF / PPTX 属 TB-8；URL 属 TB-9）。
SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".docx"})

# 编码探测顺序（A5）：先严格解码，失败后才让探测器兜底。
STRICT_ENCODINGS = ("utf-8-sig", "gb18030")

# 启发式标题判据（A1 边界 2）：短、加粗、显式字号且不以句读结尾。
_HEURISTIC_MAX_CHARS = 80
_HEURISTIC_MIN_PT = 14.0
_SENTENCE_ENDINGS = tuple("。！？；，,.;:!?")
_HEADING_STYLE = re.compile(r"heading\s+([1-9])", re.IGNORECASE)


class ParseError(ValueError):
    """文件无法解析（可读原因；调用方据此给出明确提示，不丢已存数据）。"""


@dataclass(frozen=True)
class ParsedBlock:
    """解析出的一个内容块（正文段 / 标题 / 表格行 / 代码块）。"""

    text: str
    # None = 正文；0 = Title（A1：level 0 是 Title）；1~9 = Heading N。
    heading_level: int | None = None
    # 定位信息（写进 `document_chunks.locator_json` 与总结引用）。
    locator: dict[str, Any] = field(default_factory=dict)
    heading_source: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    """一份资料的解析结果。`blocks` 为空时必须由调用方转成 `unrecognized`。"""

    format: str
    blocks: list[ParsedBlock]
    encoding: str | None = None
    heading_source: str = "none"
    images: int = 0
    tables: int = 0


def parse_document(path: str | Path, file_format: str) -> ParsedDocument:
    """按格式解析文件；读不出来抛 `ParseError`（不是「空内容成功」）。"""
    file_path = Path(path)
    suffix = f".{file_format.lower().lstrip('.')}"
    if suffix not in SUPPORTED_SUFFIXES:
        raise ParseError(f"本单不支持该格式：{suffix}")

    if suffix == ".docx":
        return _parse_docx(file_path)
    return _parse_text(file_path, suffix)


# --- TXT / MD ---------------------------------------------------------------


def _parse_text(path: Path, suffix: str) -> ParsedDocument:
    """TXT / MD：先解码（带编码回传），再按格式建块。"""
    raw = path.read_bytes()
    text, encoding = decode_text(raw)

    if suffix == ".md":
        blocks, headings = _parse_markdown(text)
        heading_source = "style" if headings else "none"
    else:
        blocks = _paragraph_blocks(text, "txt")
        heading_source = "none"

    return ParsedDocument(
        format=suffix.lstrip("."),
        blocks=blocks,
        encoding=encoding,
        heading_source=heading_source,
    )


def decode_text(raw: bytes) -> tuple[str, str]:
    """按 A5 的顺序解码，返回 (文本, 实际编码名)。"""
    for encoding in STRICT_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    best = charset_normalizer.from_bytes(raw).best()
    if best is None or best.encoding is None:
        raise ParseError("无法识别文本编码；请把文件另存为 UTF-8 后重试")
    return str(best), best.encoding


def _paragraph_blocks(text: str, file_format: str) -> list[ParsedBlock]:
    """TXT：按行成块，跳过空行；位置用段落序号（1 起）。"""
    blocks: list[ParsedBlock] = []
    index = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        index += 1
        blocks.append(
            ParsedBlock(
                text=stripped,
                locator={"format": file_format, "paragraph": index},
            )
        )
    return blocks


def parse_markdown_blocks(
    text: str,
    *,
    format_name: str = "md",
    locator_extra: dict[str, Any] | None = None,
) -> tuple[list[ParsedBlock], int]:
    """Markdown 文本 → 内容块 + 标题数（公开入口，供网页正文复用同一 token 流）。

    `format_name` / `locator_extra` 让调用方把格式名与来源地址（如最终 URL）写进
    每个块的 locator，使引用位置可回溯到具体来源。
    """
    return _parse_markdown(
        text, format_name=format_name, locator_extra=locator_extra
    )


def _parse_markdown(
    text: str,
    *,
    format_name: str = "md",
    locator_extra: dict[str, Any] | None = None,
) -> tuple[list[ParsedBlock], int]:
    """MD：走 token 流建块；代码围栏里的 `#` 不会被当成标题。

    标题级别取 `heading_open.tag`（h1..h6）；正文取 `inline`，代码取 `fence` /
    `code_block`（作为普通内容保留，不丢资料）。`token.map[0]` 是 0 起行号，
    没给时退回块序号，保证 locator 始终有可读位置。
    """
    tokens = MarkdownIt("commonmark").parse(text)
    blocks: list[ParsedBlock] = []
    headings = 0
    consumed: set[int] = set()
    block_index = 0

    for index, token in enumerate(tokens):
        if index in consumed:
            continue

        locator = _markdown_locator(
            token.map, block_index, format_name, locator_extra
        )
        if token.type == "heading_open":
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            if inline is not None and inline.type == "inline":
                consumed.add(index + 1)
            content = inline.content.strip() if inline is not None else ""
            if content:
                headings += 1
                block_index += 1
                blocks.append(
                    ParsedBlock(
                        text=content,
                        heading_level=int(token.tag.lstrip("h")),
                        locator=locator,
                        heading_source="style",
                    )
                )
        elif token.type in {"paragraph_open", "list_item_open"}:
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            if inline is None or inline.type != "inline":
                continue
            consumed.add(index + 1)
            content = inline.content.strip()
            if content:
                block_index += 1
                blocks.append(ParsedBlock(text=content, locator=locator))
        elif token.type in {"fence", "code_block"}:
            content = token.content.strip("\n").strip()
            if content:
                block_index += 1
                blocks.append(
                    ParsedBlock(
                        text=content,
                        locator={**locator, "code": True},
                    )
                )
        elif token.type == "inline":
            # 表格单元格等没有 paragraph_open 包裹的内联内容：不丢。
            content = token.content.strip()
            if content:
                block_index += 1
                blocks.append(ParsedBlock(text=content, locator=locator))

    return blocks, headings


def _markdown_locator(
    line_map: list[int] | None,
    fallback_index: int,
    format_name: str = "md",
    locator_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """MD 定位：优先用 token.map 的起始行号（1 起），没有则退块序号。"""
    locator: dict[str, Any] = {"format": format_name, **(locator_extra or {})}
    if line_map:
        locator["line"] = line_map[0] + 1
    else:
        locator["block"] = fallback_index + 1
    return locator


# --- DOCX -------------------------------------------------------------------


def _parse_docx(path: Path) -> ParsedDocument:
    """DOCX：读段落 + 表格，图片数量单列（图片内文字读不到）。"""
    try:
        document = Document(str(path))
    except (PackageNotFoundError, BadZipFile, ValueError, KeyError) as exc:
        raise ParseError(
            "文件已损坏或不是有效的 .docx（模板类型文件请另存为 .docx 后重试）"
        ) from exc
    except OSError as exc:
        raise ParseError(f"无法读取文件：{exc}") from exc

    blocks: list[ParsedBlock] = []
    heading_sources: set[str] = set()
    paragraph_index = 0

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        paragraph_index += 1
        level, source = _docx_heading(paragraph, text)
        if source is not None:
            heading_sources.add(source)
        blocks.append(
            ParsedBlock(
                text=text,
                heading_level=level,
                locator={"format": "docx", "paragraph": paragraph_index},
                heading_source=source,
            )
        )

    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            row_text = " | ".join(cell.text.strip() for cell in row.cells).strip(" |")
            if not row_text:
                continue
            blocks.append(
                ParsedBlock(
                    text=row_text,
                    locator={
                        "format": "docx",
                        "table": table_index,
                        "row": row_index,
                    },
                )
            )

    if "style" in heading_sources:
        heading_source = "style"
    elif "heuristic" in heading_sources:
        heading_source = "heuristic"
    else:
        heading_source = "none"

    return ParsedDocument(
        format="docx",
        blocks=blocks,
        heading_source=heading_source,
        images=len(document.inline_shapes),
        tables=len(document.tables),
    )


def _docx_heading(paragraph, text: str) -> tuple[int | None, str | None]:
    """判标题级别与来源：内置样式优先，其次字号 / 加粗启发式（A1）。"""
    style_name = paragraph.style.name if paragraph.style is not None else ""
    normalized = (style_name or "").strip()

    if normalized.lower() == "title":
        return 0, "style"
    matched = _HEADING_STYLE.fullmatch(normalized)
    if matched:
        return int(matched.group(1)), "style"

    return _heuristic_heading(paragraph, text)


def _heuristic_heading(paragraph, text: str) -> tuple[int | None, str | None]:
    """启发式：短、加粗、显式字号且不以句读结尾 → 标题（并标注来源）。"""
    if len(text) > _HEURISTIC_MAX_CHARS or text.endswith(_SENTENCE_ENDINGS):
        return None, None

    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs:
        return None, None

    first = runs[0]
    bold = first.bold
    size = first.font.size
    if bold is None:
        bold = paragraph.style.font.bold if paragraph.style is not None else None
    if size is None:
        size = paragraph.style.font.size if paragraph.style is not None else None

    if not bold or size is None or size.pt < _HEURISTIC_MIN_PT:
        return None, None

    if size.pt >= 18:
        level = 1
    elif size.pt >= 16:
        level = 2
    else:
        level = 3
    return level, "heuristic"
