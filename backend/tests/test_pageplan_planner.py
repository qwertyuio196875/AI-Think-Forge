"""页面规划算法（工单 25 / ADR-0004）纯函数测试。

钉住验收：
- **说多少页就是多少页**：`plan_pages` 返回的 `pages` 长度恒等于 `target_pages`，
  封面占一页且计入总数；
- **页数不足按权重合并、不砍章节**：少页时把权重最低的章并进相邻章，章节标题仍在
  合并页标题里出现，绝不投弃；
- **富余拆分重点章节**：多页时权重最高的章拆成多页；
- **区间校验**：[3, 60] 之外抛 `PagePlanError`。

本模块不碰库、不调模型，输入输出都是不可变 dataclass。
"""

from __future__ import annotations

import pytest

from app.pageplan.planner import (
    MAX_TARGET_PAGES,
    MIN_TARGET_PAGES,
    PAGE_KIND_CONTENT,
    PAGE_KIND_COVER,
    Chapter,
    PagePlanError,
    plan_pages,
)


def _chapters(*weights) -> list[Chapter]:
    """按 (标题, 权重) 或 (标题) 构造章节清单，标题从「一章」起。"""
    result = []
    for i, weight in enumerate(weights, start=1):
        result.append(Chapter(seq=i, title=f"第 {i} 章", weight=weight))
    return result


# --- 说多少页就是多少页 -------------------------------------------------------


def test_plan_pages_returns_exactly_target_pages_with_cover() -> None:
    result = plan_pages(target_pages=8, chapters=_chapters(3, 5))
    assert result.actual_pages == 8
    assert len(result.pages) == 8
    # 封面占第 1 页并计入总数。
    assert result.pages[0].kind == PAGE_KIND_COVER
    assert result.pages[0].index == 1
    assert result.pages[0].chapter_seqs == ()


def test_single_chapter_even_paging() -> None:
    """3 章、目标 4 页：恰好每章一页（3 正文 + 封面），无合并无拆分。"""
    result = plan_pages(target_pages=4, chapters=_chapters(1, 1, 1))
    assert result.actual_pages == 4
    assert len([p for p in result.pages if p.kind == PAGE_KIND_CONTENT]) == 3
    # 每章各一页，各自归属自己的章节。
    seqs = [p.chapter_seqs for p in result.pages if p.kind == PAGE_KIND_CONTENT]
    assert seqs == [(1,), (2,), (3,)]


# --- 页数不足：按权重合并、不砍章节 -------------------------------------------


def test_fewer_pages_merges_lowest_weight_chapter() -> None:
    """6 章、目标 3 页（2 正文 + 封面）：2 个合并过头寸的正文页，6 章全部保留。"""
    result = plan_pages(target_pages=3, chapters=_chapters(1, 1, 1, 1, 1, 1))
    assert result.actual_pages == 3
    pages = [p for p in result.pages if p.kind == PAGE_KIND_CONTENT]
    assert len(pages) == 2
    # 6 章全部出现在合并页的 chapter_seqs 里（不砍任何章）。
    merged = [seq for p in pages for seq in p.chapter_seqs]
    assert sorted(merged) == [1, 2, 3, 4, 5, 6]


def test_merging_keeps_lowest_weight_chapter_title_in_merged_page() -> None:
    """被合并的轻权重章节标题要在合并页标题里出现（内容不丢）。"""
    result = plan_pages(target_pages=3, chapters=_chapters(3, 100, 3))
    pages = [p for p in result.pages if p.kind == PAGE_KIND_CONTENT]
    # 权重最低的是第 1 / 3 章；第 2 章权重最高保持独立。合并页标题应含被并章名。
    assert len(pages) == 2
    # 至少有一个合并页同时关联两章。
    assert any(len(p.chapter_seqs) == 2 for p in pages)
    assert any("第 1 章" in p.title or "第 3 章" in p.title for p in pages)


def test_merging_never_drops_any_chapter() -> None:
    """任意目标页数下，所有章节 seq 都出现在内容页里（不顺序截断）。"""
    for target in (3, 4, 5, 7, 10):
        result = plan_pages(target_pages=target, chapters=_chapters(1, 2, 3, 4, 5, 6))
        merged = [seq for p in result.pages for seq in p.chapter_seqs]
        assert sorted(set(merged)) == [1, 2, 3, 4, 5, 6], f"target={target}"


# --- 富余：拆分重点章节 -------------------------------------------------------


def test_more_pages_splits_heaviest_chapter() -> None:
    """3 章、目标 6 页（5 正文 + 封面）：权重最高的那章拆成多页。"""
    result = plan_pages(target_pages=6, chapters=_chapters(10, 5, 3))
    assert result.actual_pages == 6
    pages = [p for p in result.pages if p.kind == PAGE_KIND_CONTENT]
    assert len(pages) == 5
    # 权重最高的第 1 章被拆成多页。
    split = [p for p in pages if p.chapter_seqs == (1,)]
    assert len(split) > 1


def test_every_chapter_has_at_least_one_page_when_expanding() -> None:
    result = plan_pages(target_pages=12, chapters=_chapters(4, 80, 4, 4, 4))
    merged = [seq for p in result.pages for seq in p.chapter_seqs]
    assert set(merged) == {1, 2, 3, 4, 5}
    # 富余时不应有合并页（每章至少一页），weight 最高的第 2 章被拆分。
    assert len({p.chapter_seqs for p in result.pages if p.kind == PAGE_KIND_CONTENT}) >= 5


# --- 区间校验 ----------------------------------------------------------------


@pytest.mark.parametrize("target", [MIN_TARGET_PAGES - 1, 0, -1, MAX_TARGET_PAGES + 1, 99])
def test_target_pages_out_of_range_raises(target: int) -> None:
    with pytest.raises(PagePlanError):
        plan_pages(target_pages=target, chapters=_chapters(1, 1, 1))


@pytest.mark.parametrize("target", [MIN_TARGET_PAGES, 8, 12, 16, 20, 30, MAX_TARGET_PAGES])
def test_target_pages_in_range_is_accepted(target: int) -> None:
    result = plan_pages(target_pages=target, chapters=_chapters(1, 2, 3, 4))
    assert result.actual_pages == target


def test_empty_chapters_raises() -> None:
    with pytest.raises(PagePlanError):
        plan_pages(target_pages=6, chapters=[])


# --- 权重缺失退化为均分 -------------------------------------------------------


def test_missing_weights_fall_back_to_equal_split() -> None:
    result = plan_pages(target_pages=3, chapters=_chapters(None, None, None))
    assert result.actual_pages == 3
    pages = [p for p in result.pages if p.kind == PAGE_KIND_CONTENT]
    assert len(pages) == 2
    merged = [seq for p in pages for seq in p.chapter_seqs]
    assert set(merged) == {1, 2, 3}