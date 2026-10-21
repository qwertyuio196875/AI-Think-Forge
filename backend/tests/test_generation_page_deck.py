"""按页面规划渲染 deck 幻灯片（工单 27 / ADR-0004）。

钉住 issue #27 验收：
1. **页数 = 规划页数 + 结尾页**：`slides_for_page_plan` 把规划里每一页渲染成一张
   幻灯片（封面 → 标题页；正文页 → 章节页），末尾加一页「谢谢 / 提问环节」；
2. **归属章节正确**：内容页标题用页面规划的 title；多章合并页（`chapter_seqs` 多章）
   把多章正文拼在一页，不丢章；
3. **确定性渲染**：同一输入产出同一幻灯片序列（不调模型）；
4. **HTML 可落地验证**：`build_html_deck_from_slides` 产的 HTML 通过
   `verify_html_deliverable`（自包含、无外链、首尾 structure 正确）。

本模块只做纯函数渲染：输入是规划页列表 + 已填正文，输出是不可变 `DeckSlide` /
单文件 HTML，不碰库、不启动浏览器。
"""

from __future__ import annotations

from pathlib import Path

from app.generation.deck import (
    LAYOUT_END,
    LAYOUT_TITLE,
    build_html_deck_from_slides,
    verify_html_deliverable,
)
from app.generation.page_deck import END_SUBTITLE, END_TITLE, slides_for_page_plan
from app.pageplan.planner import PAGE_KIND_CONTENT, PAGE_KIND_COVER


def _pl(pages: list[dict]) -> list[dict]:
    return [{**page, "index": i + 1} for i, page in enumerate(pages)]


def _sections() -> list[dict]:
    return [
        {
            "seq": 1,
            "title": "产品全景",
            "content_md": "## 全景主线\n\n这是第一章正文，讲三条主线。\n\n- 主线甲\n- 主线乙",
        },
        {
            "seq": 2,
            "title": "第一次上手",
            "content_md": "## 上手五件事\n\n第一天做五件事。\n\n1. 看数据\n2. 找同事",
        },
        {
            "seq": 3,
            "title": "常见疑问",
            "content_md": "## 高频问题\n\n三个高频问题的解答。\n",
        },
    ]


# --- 验收 ①：页数 = 规划页 + 结尾页 -------------------------------------------


def test_slides_count_matches_plan_plus_end() -> None:
    pages = _pl(
        [
            {"kind": PAGE_KIND_COVER, "title": "演示", "chapter_seqs": []},
            {"kind": PAGE_KIND_CONTENT, "title": "产品全景", "chapter_seqs": [1]},
            {"kind": PAGE_KIND_CONTENT, "title": "第一次上手", "chapter_seqs": [2]},
            {"kind": PAGE_KIND_CONTENT, "title": "常见疑问", "chapter_seqs": [3]},
        ]
    )
    slides = slides_for_page_plan(
        pages=pages, sections=_sections(), task_title="演示", plan_title="演示"
    )
    assert len(slides) == len(pages) + 1  # 4 规划页 + 1 结尾
    assert slides[0].layout == LAYOUT_TITLE
    assert slides[-1].layout == LAYOUT_END
    assert slides[-1].title == END_TITLE
    assert slides[-1].subtitle == END_SUBTITLE


# --- 验收 ②：归属章节正确 -----------------------------------------------------


def test_content_page_titles_and_chapter_bodies() -> None:
    pages = _pl(
        [
            {"kind": PAGE_KIND_COVER, "title": "演示", "chapter_seqs": []},
            {"kind": PAGE_KIND_CONTENT, "title": "全景与新手上手", "chapter_seqs": [1, 2]},
        ]
    )
    slides = slides_for_page_plan(
        pages=pages, sections=_sections(), task_title="演示", plan_title="演示"
    )
    # 内容页标题来自规划（合并页标题）。
    content = slides[1]
    assert content.title == "全景与新手上手"
    # 多章正文拼在同一页：两章正文的文本都在块里。
    texts = [p.text for p in content.pieces if p.kind == "text"]
    assert any("这是第一章正文" in t for t in texts)
    assert any("第一天做五件事" in t for t in texts)
    items = [item for p in content.pieces if p.kind == "items" for item in p.items]
    assert "主线甲" in items and "看数据" in items


def test_cover_page_uses_plan_title() -> None:
    pages = _pl([{"kind": PAGE_KIND_COVER, "title": "演讲标题", "chapter_seqs": []}])
    slides = slides_for_page_plan(
        pages=pages, sections=_sections(), task_title="任务名", plan_title="演讲标题"
    )
    assert slides[0].title == "演讲标题"
    assert slides[0].layout == LAYOUT_TITLE


def test_missing_body_falls_back_to_page_title() -> None:
    """章节没正文时不给内容假造，只放页标题占位。"""
    sections = [{"seq": 1, "title": "无正文章", "content_md": ""}]
    pages = _pl([{"kind": PAGE_KIND_CONTENT, "title": "无正文章", "chapter_seqs": [1]}])
    slides = slides_for_page_plan(
        pages=pages, sections=sections, task_title="演示", plan_title="演示"
    )
    content = slides[0]
    assert any("无正文章" in p.text for p in content.pieces if p.kind == "text")


# --- 验收 ③：确定性渲染 -------------------------------------------------------


def test_slides_are_deterministic() -> None:
    pages = _pl(
        [
            {"kind": PAGE_KIND_COVER, "title": "演示", "chapter_seqs": []},
            {"kind": PAGE_KIND_CONTENT, "title": "产品全景", "chapter_seqs": [1]},
        ]
    )
    a = slides_for_page_plan(pages=pages, sections=_sections(), task_title="演示", plan_title="演示")
    b = slides_for_page_plan(pages=pages, sections=_sections(), task_title="演示", plan_title="演示")
    assert a == b


# --- 验收 ④：HTML 可落地验证 --------------------------------------------------


def test_build_html_from_plan_passes_integrity(
    tmp_path: Path,
) -> None:
    from app.generation.themes import DECK_THEMES

    pages = _pl(
        [
            {"kind": PAGE_KIND_COVER, "title": "演示", "chapter_seqs": []},
            {"kind": PAGE_KIND_CONTENT, "title": "产品全景", "chapter_seqs": [1]},
            {"kind": PAGE_KIND_CONTENT, "title": "第一次上手", "chapter_seqs": [2]},
        ]
    )
    slides = slides_for_page_plan(
        pages=pages, sections=_sections(), task_title="演示", plan_title="演示"
    )
    theme = next(iter(DECK_THEMES.values()))
    output = tmp_path / "per-plan.html"
    build = build_html_deck_from_slides(
        slides=slides,
        task_title="演示",
        plan_md="# 演示\n\n## 章节\n- 产品全景\n- 第一次上手",
        theme=theme,
        output_path=output,
    )
    assert build.slide_count == len(slides)
    verify_html_deliverable(build)  # 自包含、无外链、首尾结构正确。