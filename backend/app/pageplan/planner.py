"""PPT 页面规划：把已填充章节规划成「章节 → 页列表」（工单 25 / ADR-0004）。

这是 PPT 一轨的**确定性地基**：页数由显式的「章节 → 页列表」控制，而不是按标题层级
自动切页（`slides_from_plan` 那套因页数不可控，退为无页面规划时的兜底路径）。

四条硬约束（issue #25 验收）：
1. **说多少页就是多少页**：`target_pages` 是多少，规划的页数就恰好是多少；封面占一页
   且计入总数。
2. **页数不足时按权重合并，不是顺序截断**：少页时把**权重最低**的章节并进相邻章节，
   绝不砍掉靠后的章节（砍掉会让内容永久丢失）。
3. **富余时拆分重点章节**：多页时把权重高的章节拆成多页（按它的权重占比分页），
   页数不足时反着合并，两条路共用同一份权重。
4. **不接受不可信的页数**：3–60 之外的页数在进规划之前就要被拒绝（服务层翻 422），
   这里只处理合理区间。

权重来自方案的「建议字数」（`target_length`），与填充分摊同源（ADR-0006：权重回源头
读方案，不读上次分摊的产物）。全为缺失/非正数时退化为均分。

本模块是纯函数：不碰库、不调模型、不抛 HTTPException，输入输出都是不可变结构，
由调用方把校验失败翻成 422。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# 页数的硬区间（issue #25 验收 ⑤）：区间外一律拒绝，不做静默夹紧。
MIN_TARGET_PAGES = 3
MAX_TARGET_PAGES = 60

# 常用档位（issue #25「预设 8 / 12 / 16 / 20 / 30」）。
PAGES_PRESETS: tuple[int, ...] = (8, 12, 16, 20, 30)

# 封面占一页（计入总数）。
COVER_PAGE = True

# 规划里页的类型：封面页 / 常规章节页 / 结尾页。
# 结尾页（工单 27 收尾修正）同样**计入目标页数**：deck 完整性契约要求末张是结束页
# （`verify_html_deliverable`），而 issue #25 要求「说 16 页就是 16 页」；只有把它
# 算进规划、而不是渲染时额外追加，两个要求才能同时成立。
PAGE_KIND_COVER = "cover"
PAGE_KIND_CONTENT = "content"
PAGE_KIND_END = "end"


@dataclass(frozen=True)
class PagePlanError(Exception):
    """页面规划不成立的原因（由服务层翻成 4xx）。"""

    detail: str


@dataclass(frozen=True)
class Chapter:
    """章节输入：权重 = 方案建议字数；缺失/非正数等价。

    序号是章节一等身份（`plan_sections.seq`），跨修订搬序号时应由调用方重新映射。
    """

    seq: int
    title: str
    weight: int | None = None


@dataclass(frozen=True)
class PlannedPage:
    """规划里的一个页。

    `chapter_seqs` 是该页内容来源的章节：常规页只有一个（拆分时同一章占多页，每页
    各自引用同一 seq）；**合并页**有多个 seq（权重最低的章节并进相邻章）。封面为 `()`。
    `title` 是页面标题：合并页把所涉章节标题并起来，让「这一页讲了哪几章」一眼可见。
    """

    index: int
    kind: str
    title: str
    chapter_seqs: tuple[int, ...] = ()


@dataclass(frozen=True)
class PagePlan:
    """一次 `target_pages` 下的整份规划。

    `pages` 与 `target_pages` 同长（硬约束）。`cover` 恒真（封面总占一页）。
    """

    target_pages: int
    cover: bool
    pages: tuple[PlannedPage, ...]

    @property
    def actual_pages(self) -> int:
        """实际页数：恒等于 `target_pages`（工单 25 的「说多少就是多少」）。

        #26 做完单页增删后，实际页数可以不再等于最初的目标页数——那是增删后的新规划
        校验的右侧，由调用方拿 `replan_after_edit` 生成、用新的页数做 `target_pages`。
        """
        return len(self.pages)


def validate_target_pages(target_pages: int) -> None:
    """页数必须在 [3, 60] 内；区间外抛 `PagePlanError`（调用方翻 422）。"""
    if target_pages < MIN_TARGET_PAGES:
        raise PagePlanError(
            f"页数 {target_pages} 低于下限 {MIN_TARGET_PAGES}："
            "请选择或输入 3–60 之间的页数"
        )
    if target_pages > MAX_TARGET_PAGES:
        raise PagePlanError(
            f"页数 {target_pages} 超过上限 {MAX_TARGET_PAGES}："
            "请选择或输入 3–60 之间的页数"
        )


def plan_pages(
    *,
    target_pages: int,
    chapters: Sequence[Chapter],
    deck_title: str = "演示",
) -> PagePlan:
    """把章节规划成恰好 `target_pages` 页。

    - 封面占第 1 页（`PAGE_KIND_COVER`，`deck_title` 作标题）。
    - 结尾页占最后 1 页（`PAGE_KIND_END`，致谢 / 提问环节）——它**计入目标页数**：
      deck 的完整性契约要求末张是结束页，只有把它算进规划才不违反「说 16 页就是
      16 页」（issue #25 验收 ①）。
    - 中间 `target_pages - 2` 页分给章节：
      - 恰好每章一页：直接一一对应；
      - 页数不足：把**权重最低**的章节并进相邻章，直到页数对上（不砍章节）；
      - 富余：把**权重最高**的章节拆分，让它在连续多页上摊开。
    - 权重参考 `Chapter.weight`；全部缺失/非正数 → 均分。

    章节为空时抛 `PagePlanError`（调用方先拦「未填充」→ 409 时会挡住绝大多数情况，
    这里兜底）。
    """
    validate_target_pages(target_pages)

    chapter_list = list(chapters)
    if not chapter_list:
        raise PagePlanError("没有可规划正文的章节：请先完成填充再规划 PPT 页数")

    if target_pages <= 2:
        # 下限之外（validate_target_pages 已拦），兜底：只有封面与结尾。
        return PagePlan(
            target_pages=target_pages,
            cover=COVER_PAGE,
            pages=(
                _cover_page(index=1, deck_title=deck_title),
                _end_page(index=2),
            )[:target_pages],
        )

    # 内容页 = 目标页数 - 封面 - 结尾（结尾页计入总数，见函数文档）。
    content_pages = target_pages - 2
    groups = _initial_groups(chapter_list)

    if len(groups) < content_pages:
        groups = _split_groups(groups, content_pages, deck_title)
    elif len(groups) > content_pages:
        groups = _merge_groups(groups, content_pages)

    pages: list[PlannedPage] = [_cover_page(index=1, deck_title=deck_title)]
    for group in groups:
        pages.extend(_group_pages(group, start_index=len(pages) + 1))
    # 结尾页计入目标页数（见函数文档），追加在最后。
    pages.append(_end_page(index=len(pages) + 1))
    return PagePlan(target_pages=target_pages, cover=COVER_PAGE, pages=tuple(pages))


# ---------- 内部结构：一个「组」承载一篇内容，成熟后摊成连续页 ----------


def _cover_page(*, index: int, deck_title: str) -> PlannedPage:
    return PlannedPage(index=index, kind=PAGE_KIND_COVER, title=deck_title)


def _end_page(*, index: int) -> PlannedPage:
    """结尾页（致谢 / 提问环节）：计入目标页数，保证 deck 末张是结束页。"""
    return PlannedPage(index=index, kind=PAGE_KIND_END, title="谢谢")


@dataclass(frozen=True)
class _Group:
    """一个内容组：聚合的章节清单 + 要在第几页摊开的页数（≥1）。"""

    members: tuple[Chapter, ...]
    span: int


def _group_weight(group: _Group) -> int:
    """组权重 = 成员权重的整数表示（缺失/非正数 → 1）。

    合并页多章并一团，权重按成员求和，让「谁重要谁该拆、谁次要谁该并」有据可依。
    """
    total = 0
    for member in group.members:
        total += member.weight if isinstance(member.weight, int) and member.weight > 0 else 1
    return total or 1


def _initial_groups(chapters: list[Chapter]) -> list[_Group]:
    """初始：每章一组、每组一页（先按实际章节数排好，再看富余/不足怎么调）。"""
    return [_Group(members=(chapter,), span=1) for chapter in chapters]


def _split_groups(
    groups: list[_Group], content_pages: int, deck_title: str
) -> list[_Group]:
    """页数富余：把权重最高的组拆开，直到组的总 span 恰好等于 `content_pages`。

    富余页数在 `[1, len(groups) - 1]` 之间（不然轮不到拆分）。逐轮在「权重最高」的组上
    加一页跨度；权重相同取靠前者，保证确定性（输入同则输出同）。
    """
    budget = content_pages - sum(group.span for group in groups)
    if budget <= 0:
        return groups

    work = list(groups)
    for _ in range(budget):
        # 只考虑还能继续摊的组（span 越高越靠后，但权重优先；span 相等的组权重高的先拆）。
        candidate_idx = max(
            range(len(work)),
            key=lambda i: (_group_weight(work[i]), -work[i].span, -i),
        )
        work = [
            _Group(
                members=group.members,
                span=group.span + (1 if i == candidate_idx else 0),
            )
            for i, group in enumerate(work)
        ]
    return work


def _merge_groups(groups: list[_Group], content_pages: int) -> list[_Group]:
    """页数不足：把**权重最低**的组并进相邻组，直到组数恰好等于 `content_pages`。

    不砍章节：并进相邻组后，被并的章节仍在其内容里出现（页标题把两章标题并起来）。
    相邻取「左右两边权重更低」的那一边，让轻的一并、重的一保持独立页（重点章节不被挤进
    合并页）。边界组只有一边可并。全部等权时并向靠前的邻居。
    """
    if content_pages <= 0:
        return groups
    work = list(groups)
    while len(work) > content_pages:
        # 找权重最低的组；权重相同取靠后的，让它倾向于并进「前置更重」的邻居。
        index = min(range(len(work)), key=lambda i: (_group_weight(work[i]), -i))
        left_idx = index - 1 if index > 0 else None
        right_idx = index + 1 if index < len(work) - 1 else None

        if left_idx is not None and right_idx is not None:
            target_idx = (
                right_idx
                if _group_weight(work[left_idx]) >= _group_weight(work[right_idx])
                else left_idx
            )
        elif left_idx is not None:
            target_idx = left_idx
        else:
            target_idx = right_idx

        source = work[index]
        target = work[target_idx]
        merged = _Group(
            members=(*source.members, *target.members),
            # 合并 = 一章（一个页）装下多章：span 归 1（不是两章 span 求和），
            # 否则总页数不降反升，「少页合并」的目的就被打破了。
            span=1,
        )
        # 用合并组替换被并的两个（保序：被并组每次都与目标相邻）。
        low, high = sorted((index, target_idx))
        work = [*work[:low], merged, *work[high + 1 :]]
    return work


def _group_pages(group: _Group, *, start_index: int) -> list[PlannedPage]:
    """把一个内容组摊成连续页：span 页，每页 index 递增。

    span == 1 → 一页，`chapter_seqs` 是组全体成员（常规一页即该章；**合并页多章**，
    要把被并的章都带上，否则章节在规划里「消失」，与「不砍章节」冲突）。
    span > 1 → 拆分成多页，被拆的组通常只有一名成员（或主要成员），每页都引用该章；
    标题用组标题，让「同一组的内容占了几页」可见。
    """
    title = _group_title(group)
    member_seqs = tuple(member.seq for member in group.members)
    return [
        PlannedPage(
            index=start_index + i,
            kind=PAGE_KIND_CONTENT,
            title=title,
            chapter_seqs=member_seqs if group.span == 1 else (member_seqs[0],),
        )
        for i in range(group.span)
    ]


def _group_title(group: _Group) -> str:
    """组标题：单章用章名，合并多章用「主章 + 附章」并起来。

    权重最高者作主标题（重点章节上牌面），其余按 seq 序追加。
    """
    sorted_members = sorted(group.members, key=lambda m: (_group_weight_from_chapter(m), m.seq))
    head = sorted_members[-1]
    rest = [m for m in sorted_members if m is not head]
    if not rest:
        return head.title
    return f"{head.title}（含 {'、'.join(m.title for m in rest)}）"


def _group_weight_from_chapter(chapter: Chapter) -> int:
    return chapter.weight if isinstance(chapter.weight, int) and chapter.weight > 0 else 1