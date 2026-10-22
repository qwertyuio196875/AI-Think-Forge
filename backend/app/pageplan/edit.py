"""页面规划的单页增删（工单 26 / ADR-0004）。

用户可以在预览里增删单页，改的是**某一次规划的具体页列表**（以 `page_plan_id` 寻址），
改完**另存一份新的规划**（新 id、`target_pages` = 新页数）：这样：
- 历史规划不改（用户可能同时盯着 8 页 / 16 页两版）；
- 实际页数**不再强制等于最初的目标页数**（增删后的真实页数才是新规划的
  `target_pages`，也才是后续 #27 渲染 / #28 截图的对账基准）；
- 「能把重点挤到最后发现出来」——正文里被挤碎的重点章节，删页后页标题与归属仍在，
  预览一眼可见。

操作语义（都是纯函数，输入输出不可变；由调用方落库并翻错误码）：
- `add_page(pages, at_index)`：在 `at_index`（1 起，含封面；默认取该页章节归属）**之后**
  插一页。若该页是正文页，在它引用的章节下**复制一页拆分**（同一章多页，让章节摊开）；
  若该页是封面，则插一页无名正文页兜底（封面后紧跟第一章页）。
- `delete_page(pages, at_index)`：删掉 `at_index` 这一页。封面**不可删**；
  正文页直接删。删后若某章在 `chapter_seqs` 里完全消失但仍有正文未呈现——这里只做
  「删那一页」的最小操作，章节内容的再编排不归本工单（#27 渲染时会按章节剩余正文兜底）。

页码 index 是规划内的一等字段，增删后要**整体重新编号**（1..N 连续），保证前端预览
始终是连续页码、不出现空洞（删了第 3 页，第 4 页顺延为 3）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pageplan.planner import PAGE_KIND_CONTENT, PAGE_KIND_COVER


@dataclass(frozen=True)
class PageEditError(Exception):
    """单页增删不成立的原因（由服务层翻 4xx）。"""

    detail: str


def renumber(pages: list[dict]) -> list[dict]:
    """把页列表的 `index` 重新编号为连续的 1..N。"""
    return [
        {**page, "index": position} for position, page in enumerate(pages, start=1)
    ]


def add_page(pages: list[dict], *, after_index: int) -> list[dict]:
    """在 `after_index` 之后插入一页，返回重新编号后的新页列表。

    `after_index` 指向**已被封面校正过的真实页码**（调用方保证 1 ≤ after_index ≤ N）：
    - 封面（index 1）之后插入 → 在第一章正文页前加一页（复制第一章归属）；
    - 某正文页之后插入 → 在该页引用的章节下再分一页（同一章多页摊开）；
    - 插入点不合法（越界 / 空列表）→ `PageEditError`。
    """
    if not pages:
        raise PageEditError("没有可增删的页：请先完成页面规划")
    if not (1 <= after_index <= len(pages)):
        raise PageEditError(
            f"增页位置 {after_index} 越界：当前共 {len(pages)} 页（含封面）"
        )

    if after_index == 1 and pages[0].get("kind") == PAGE_KIND_COVER:
        # 封面后插一页：挂在第一章正文页上（若无正文页则兜底一页）。
        first_content = next(
            (p for p in pages if p.get("kind") == PAGE_KIND_CONTENT), None
        )
        if first_content is None:
            new_page = {"kind": PAGE_KIND_CONTENT, "title": "", "chapter_seqs": []}
            return renumber([pages[0], new_page, *pages[1:]])
        new_page = {
            "kind": PAGE_KIND_CONTENT,
            "title": first_content.get("title", ""),
            "chapter_seqs": list(first_content.get("chapter_seqs") or []),
        }
        return renumber([pages[0], new_page, *pages[1:]])

    anchor = pages[after_index - 1]
    if anchor.get("kind") != PAGE_KIND_CONTENT:
        raise PageEditError(f"第 {after_index} 页不是正文页，无法在其后插入章节页")

    new_page = {
        "kind": PAGE_KIND_CONTENT,
        "title": anchor.get("title", ""),
        "chapter_seqs": list(anchor.get("chapter_seqs") or []),
    }
    return renumber([*pages[:after_index], new_page, *pages[after_index:]])


def delete_page(pages: list[dict], *, at_index: int) -> list[dict]:
    """删除 `at_index` 这一页，返回重新编号后的新页列表。

    封面（index 1）**不可删**；越界 / 空列表 → `PageEditError`。
    """
    if not pages:
        raise PageEditError("没有可增删的页：请先完成页面规划")
    if not (1 <= at_index <= len(pages)):
        raise PageEditError(
            f"删页位置 {at_index} 越界：当前共 {len(pages)} 页（含封面）"
        )
    if pages[0].get("kind") == PAGE_KIND_COVER and at_index == 1:
        raise PageEditError("封面不可删除：它占首页并计入总页数")

    return renumber([*pages[: at_index - 1], *pages[at_index:]])


def content_page_count(pages: list[dict]) -> int:
    """正文页数量（不含封面）。"""
    return sum(1 for page in pages if page.get("kind") == PAGE_KIND_CONTENT)