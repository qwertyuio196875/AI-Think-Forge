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
from app.pageplan.planner import PAGE_KIND_CONTENT, PAGE_KIND_COVER, PAGE_KIND_END


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
    封面页 → 标题页；正文页 → 章节页（归属章节按 `chapter_seqs` 取内容）；
    结尾页 → 结束页。

    **页数严格等于 `pages` 的条数**：结尾页由规划器作为 `PAGE_KIND_END` 一页写进规划、
    并计入目标页数（issue #25「说 16 页就是 16 页」）。因此这里既不能额外追加结尾页，
    也不能丢掉规划里的结尾页——两者都会让 deck 页数与规划对不上（issue #27 验收 ①）。
    """
    by_seq: dict[int, str] = {}
    seq_titles: dict[int, str] = {}
    for section in sections:
        body = (section.get("content_md") or "").strip()
        if body:
            by_seq[int(section["seq"])] = body
        seq_titles[int(section["seq"])] = section.get("title") or ""

    # 拆页对账：同一章若被规划拆成连续多页（`chapter_seqs` 都指向它），必须把正文
    # **顺次切分**到各页，否则每页都渲染整章、拆出来的几页内容全一样（issue #26
    # 「富余时拆分重点章节」要的是内容摊开，不是同一段复印几份）。
    spans = _chapter_spans(pages)

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

        if kind == PAGE_KIND_END:
            # 规划器写入的结尾页（计入目标页数）：渲染为结束版式，不再另加。
            slides.append(
                DeckSlide(
                    layout=LAYOUT_END,
                    title=page.get("title") or END_TITLE,
                    subtitle=END_SUBTITLE,
                    notes="结束页：谢谢 / 提问环节",
                )
            )
            continue

        # 内容页：收集归属章节的正文块（拆页时只取本页那一段）。
        seqs = page.get("chapter_seqs") or []
        ordinal = _page_ordinal_within_span(page, pages)
        pieces = _pieces_for_seqs(
            seqs,
            by_seq,
            seq_titles,
            page.get("title") or "",
            spans=spans,
            ordinal=ordinal,
        )
        slides.append(
            DeckSlide(
                layout=_layout_of(pieces),
                title=page.get("title") or _seqs_title(seqs, seq_titles),
                pieces=tuple(pieces),
                notes=_notes_of(page, seqs, seq_titles),
            )
        )

    return tuple(slides)


def _chapter_spans(pages: list[dict]) -> dict[int, int]:
    """统计每个章节在规划里占了几页（> 1 说明它被拆开了）。"""
    spans: dict[int, int] = {}
    for page in pages:
        if (page.get("kind") or PAGE_KIND_CONTENT) != PAGE_KIND_CONTENT:
            continue
        for seq in page.get("chapter_seqs") or []:
            key = int(seq)
            spans[key] = spans.get(key, 0) + 1
    return spans


def _page_ordinal_within_span(page: dict, pages: list[dict]) -> int:
    """本页是「它所属章节」的第几页（0 起）；合并页 / 未拆分页恒为 0。"""
    seqs = [int(s) for s in (page.get("chapter_seqs") or [])]
    if len(seqs) != 1:
        return 0
    target = seqs[0]
    ordinal = 0
    for candidate in pages:
        if candidate is page:
            return ordinal
        if (candidate.get("kind") or PAGE_KIND_CONTENT) != PAGE_KIND_CONTENT:
            continue
        if target in [int(s) for s in (candidate.get("chapter_seqs") or [])]:
            ordinal += 1
    return ordinal


def _slice_body(text: str, spans: dict[int, int] | None, ordinal: int, seq: int) -> str:
    """把一章正文按「该章占几页」均分成连续片段，取第 `ordinal` 段。

    只在章节被**拆页**（spans[seq] > 1）时切片；未拆分的章原样返回，行为不变。
    切分以段落为最小单位（不切断句子），保证每页拿到的是完整段落。
    """
    span = (spans or {}).get(seq, 1)
    if span <= 1:
        return text  # 未拆页：原样返回，行为与之前一致。

    paragraphs = [part for part in text.split("\n\n") if part.strip()]
    if len(paragraphs) <= 1:
        # 只有一段时无从均分：首片给正文，其余页留空（由调用方以页标题兜底），
        # 也好过把同一段在每一页重复一遍。
        return text if ordinal == 0 else ""

    # 均分成 span 份，尽量让每份段落数接近；余数从前面的份依次多给一段。
    total = len(paragraphs)
    base, extra = divmod(total, span)
    start = 0
    for index in range(span):
        size = base + (1 if index < extra else 0)
        if index == ordinal:
            return "\n\n".join(paragraphs[start : start + size])
        start += size
    return ""


def _pieces_for_seqs(
    seqs: list[int],
    by_seq: dict[int, str],
    seq_titles: dict[int, str],
    page_title: str,
    *,
    spans: dict[int, int] | None = None,
    ordinal: int = 0,
) -> list[DeckPiece]:
    """把一章（或合并的多章）正文解析成内容块；缺失正文用页标题兜底。

    `spans` / `ordinal` 处理「同一章被拆成连续多页」的情形：章节按段落均分成
    `spans[seq]` 份，本页只取第 `ordinal` 份，于是拆出来的几页内容各不相同、
    合起来仍是完整的该章正文（不丢内容、不重复内容）。
    """
    pieces: list[DeckPiece] = []
    body_parts: list[str] = []
    for seq in seqs:
        text = by_seq.get(seq)
        if text:
            body_parts.append(_slice_body(text, spans, ordinal, int(seq)))
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