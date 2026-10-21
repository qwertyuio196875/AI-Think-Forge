"""按页面规划渲染 deck 幻灯片（工单 27 / ADR-0004）。

页数由「章节 → 页列表」硬约束控制（`page_plans.pages_json`），而不是 `slides_from_plan`
按 H1/H2 自动切页的**兜底路径**。ADR 明确：`slides_from_plan` 只是规划缺失时使用，
主体路径是这里——把规划里每一页渲染成一张固定尺寸的 `<section>` 幻灯片，供
#28 逐页截图、#29 装配 pptx、#31 打印 PDF。

每张内容页照规划归属章节取**已填正文**（`plan_sections`），渲染只做确定性排版，
不调度模型。章节被合并（`chapter_seqs` 多章）时多章正文拼在一页；章节被拆多页时
同一章正文顺次分页。

回落到 `slides_from_plan`：当没有可用规划 / 规划无法对账时，由调用方决定是否兜底到
`app.generation.deck.slides_from_plan`。本模块只管「给规划 + 章节内容 → 幻灯片」。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.generation.deck import (
    LAYOUT_END,
    LAYOUT_LIST,
    LAYOUT_QUOTE,
    LAYOUT_TABLE,
    LAYOUT_TITLE,
    DeckPiece,
    DeckSlide,
)
from app.generation.plan_document import parse_plan_blocks
from app.pageplan.planner import PAGE_KIND_CONTENT, PAGE_KIND_COVER


@dataclass(frozen=True)
class PlanDeckError(Exception):
    """按规划渲染立不住的原因（缺章节正文 / 规划页与章节对不上）。"""

    detail: str


END_TITLE = "谢谢"
END_SUBTITLE = "提问环节"


def slides_for_page_plan(
    *,
    pages: list[dict],
    sections: list[dict],
    task_title: str,
    plan_title: str,
) -> tuple[DeckSlide, ...]:
    """把「章节 → 页列表」+ 已填正文渲染成一张张幻灯片。

    `pages`：`page_plans.pages_json` 的页列表（kind / title / chapter_seqs）。
    `sections`：`plan_sections` 的行（需含 `seq` / `title` / `content_md`）。
    封面页 → 标题页；正文页 → 章节页（归属章节按 `chapter_seqs` 取内容）。
    结尾追加一页「谢谢 / 提问环节」。
    """
    by_seq: dict[int, str] = {}
    seq_titles: dict[int, str] = {}
    for section in sections:
        body = (section.get("content_md") or "").strip()
        if body:
            by_seq[int(section["seq"])] = body
        seq_titles[int(section["seq"])] = section.get("title") or ""

    slides: list[DeckSlide] = []
    for page in pages:
        kind = page.get("kind") or PAGE_KIND_CONTENT
        if kind == PAGE_KIND_COVER:
            slides.append(
                DeckSlide(
                    layout=LAYOUT_TITLE,
                    title=page.get("title") or plan_title or task_title,
                    subtitle="",
                    notes=f"封面：{plan_title or task_title}",
                )
            )
            continue

        # 内容页：收集归属章节的正文块。
        seqs = page.get("chapter_seqs") or []
        pieces = _pieces_for_seqs(seqs, by_seq, seq_titles, page.get("title") or "")
        slides.append(
            DeckSlide(
                layout=_layout_of(pieces),
                title=page.get("title") or _seqs_title(seqs, seq_titles),
                pieces=tuple(pieces),
                notes=_notes_of(page, seqs, seq_titles),
            )
        )

    slides.append(
        DeckSlide(
            layout=LAYOUT_END,
            title=END_TITLE,
            subtitle=END_SUBTITLE,
            notes="结束页：谢谢 / 提问环节",
        )
    )
    return tuple(slides)


def _pieces_for_seqs(
    seqs: list[int],
    by_seq: dict[int, str],
    seq_titles: dict[int, str],
    page_title: str,
) -> list[DeckPiece]:
    """把一章（或合并的多章）正文解析成内容块；缺失正文用页标题兜底。"""
    pieces: list[DeckPiece] = []
    body_parts: list[str] = []
    for seq in seqs:
        if seq in by_seq:
            body_parts.append(by_seq[seq])
    raw = "\n\n".join(body_parts) if body_parts else ""

    if not raw:
        # 本章没有已填正文：放一段页标题，内容不假造。
        pieces.append(DeckPiece(kind="text", text=page_title or "（本章正文待填充）"))
        return pieces

    for block in parse_plan_blocks(raw):
        if block.kind == "heading":
            # 章节正文里可能带 `## 小标题`：降为页内小标题，不另开页。
            pieces.append(DeckPiece(kind="sub", text=block.text))
        elif block.kind in ("bullet", "numbered"):
            pieces.append(DeckPiece(kind="items", items=(block.text,)))
        elif block.kind == "table":
            pieces.append(DeckPiece(kind="table", rows=block.rows))
        else:
            pieces.append(DeckPiece(kind="text", text=block.text))
    return pieces


def _layout_of(pieces: list[DeckPiece]) -> str:
    """按内容形态选布局：有列表 / 表格分别对应；否则走正文页。"""
    if any(piece.kind == "items" for piece in pieces):
        return LAYOUT_LIST
    if any(piece.kind == "table" for piece in pieces):
        return LAYOUT_TABLE
    return LAYOUT_QUOTE


def _seqs_title(seqs: list[int], seq_titles: dict[int, str]) -> str:
    titles = [seq_titles.get(seq, f"第 {seq} 章") for seq in seqs]
    return " / ".join(t for t in titles if t)


def _notes_of(page: dict, seqs: list[int], seq_titles: dict[int, str]) -> str:
    title = page.get("title") or _seqs_title(seqs, seq_titles)
    titles = [seq_titles.get(seq, f"第 {seq} 章") for seq in seqs]
    return f"{title}（{len(seqs)} 章：{'、'.join(t for t in titles if t)}）" if titles else title