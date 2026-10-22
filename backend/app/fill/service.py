"""填充阶段的业务逻辑：入口校验、目标字数定值与逐章分摊、进度初值（工单 9 / 15 / ADR-0006）。

本模块**不生成正文**：不调模型、不写 `plan_sections.content_md`。这里只做三件事——
把用户给的字数规整成一次填充的参数、把这次尝试登记成 `fill_tasks` 一行、把章节清单
连同状态一起回给前端做初始进度。

字数为什么在这里定：目标字数有三条来源（用户显式给、方案各章建议字数之和、系统缺省），
三条来源的优先级是业务规则；分摊算法本身是纯函数，见 `app.fill.budget`。

**权重回源头读方案**，不读章节表的 `target_length`：后者是上一次分摊的产物，拿它当权重
会让每次重新分摊都放大上次的偏差。方案才是字数的真源（ADR-0006）。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.fill_task_repository import FillTaskRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.fill.budget import AllocationError, allocate_lengths
from app.grilling.plan_sections import parse_plan_sections
from app.grilling.retrieval import to_citation_cards
from app.models.fill import (
    DEFAULT_TARGET_LENGTH,
    MAX_TARGET_LENGTH,
    MIN_TARGET_LENGTH,
    FillRequest,
)
from app.retrieval.service import RetrievalService

# 参数不可用统一用 422。这里写字面量而不是 `status.HTTP_422_UNPROCESSABLE_ENTITY`：
# 该常量在新版 Starlette 里已改名并会发弃用警告，而旧版又没有新名字；与 grilling 路由
# 的既有写法保持一致。
UNPROCESSABLE = 422

# 切不出章节时的提示：ADR-0006 明确要求「拒绝并提示返回修订方案」，不猜测、不按标题
# 层级退化切分。文案里必须出现「修订方案」四个字，前端据此给出返回修订的出口。
NO_SECTION_DETAIL = (
    "当前方案切不出可填充的成品章节，无法开始填充"
    "（请返回修订方案，在「章节」一节按“- 标题：… ｜ 要点：…”的格式补齐章节后再试）"
)


def ensure_sections_exist(rows: list[dict]) -> None:
    """方案确认了但一章都切不出来 → 422（不是 409：方案状态没错，是内容不可用）。"""
    if not rows:
        raise HTTPException(status_code=UNPROCESSABLE, detail=NO_SECTION_DETAIL)


def validate_request(payload: FillRequest, rows: list[dict]) -> dict[int, int]:
    """校验请求体里的逐章字数，返回规整后的 {序号: 字数}（只含有改动的章）。

    - 给了不存在的章节序号 → 422 并点名该序号。静默忽略最糟：用户以为分摊生效了，
      填充却按旧字数写；
    - 字数必须为正整数。

    目标字数的区间**不在这里**判：它既可能是用户给的，也可能是各章建议字数之和，只有
    定值之后才知道。见 `ensure_target_length_within_range`。
    """
    if not payload.section_lengths:
        return {}

    known = {int(row["seq"]) for row in rows}
    unknown = sorted(set(payload.section_lengths) - known)
    if unknown:
        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail=(
                f"逐章字数里出现了当前方案不存在的章节序号：{'、'.join(str(seq) for seq in unknown)}"
            ),
        )

    normalized: dict[int, int] = {}
    for seq, length in payload.section_lengths.items():
        if length < 1:
            raise HTTPException(
                status_code=UNPROCESSABLE,
                detail=f"第 {seq} 章的建议字数必须为正整数，收到 {length}",
            )
        normalized[int(seq)] = int(length)
    return normalized


def suggested_weights(plan: dict, rows: list[dict]) -> dict[int, int | None]:
    """各章的**分摊权重**：回源头读方案「章节」一节的建议字数。

    按标题把方案条目与章节行对上（章节表只由方案切出，标题相同即同一章）。方案没写
    建议字数、或该章在方案里找不到时给 None，由 `budget` 退化为均分。
    """
    suggested = {section.title: section.suggested_length for section in parse_plan_sections(
        plan.get("content_md", "")
    )}
    return {
        int(row["seq"]): suggested.get(str(row["title"]))
        for row in rows
    }


def resolve_target_length(payload: FillRequest, weights: dict[int, int | None]) -> int:
    """定下本次填充的目标字数。

    优先级（规格 §4 + ADR-0006）：
    1. 用户显式给的目标字数；
    2. 各章建议字数之和——但只有在**每一章**都有建议字数时才算；旧格式方案（plan-v2）
       有的章没建议字数，此时求和不成立（缺的章按 0 算会让目标字数凭空缩水）；
    3. 系统缺省值 `DEFAULT_TARGET_LENGTH`。
    """
    if payload.target_length is not None:
        return int(payload.target_length)

    if weights and all(length is not None for length in weights.values()):
        return int(sum(length for length in weights.values() if length is not None))
    return DEFAULT_TARGET_LENGTH


def ensure_no_active_fill(fill_repository: FillTaskRepository, task_id: int) -> None:
    """同一任务同时只允许一次进行中的填充 → 否则 409。"""
    active = fill_repository.active_for_task(task_id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"任务 {task_id} 已有进行中的填充任务（#{active['id']}），请先等待完成或中断它"
            ),
        )


def ensure_target_length_within_range(target_length: int) -> None:
    """US 14：目标字数 300–20000；超出即拒绝并说明原因，**不静默改成边界值**。

    文案里同时给出用户填的数与合法区间：只说「参数非法」等于让人自己猜边界；
    而把 299 悄悄改成 300，用户拿到的是自己没要的篇幅。
    """
    if target_length < MIN_TARGET_LENGTH:
        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail=(
                f"目标字数 {target_length} 低于下限 {MIN_TARGET_LENGTH} 字，"
                f"不会自动改成 {MIN_TARGET_LENGTH}；请提高篇幅或分多篇写"
            ),
        )
    if target_length > MAX_TARGET_LENGTH:
        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail=(
                f"目标字数 {target_length} 超出上限 {MAX_TARGET_LENGTH} 字，"
                "请缩小篇幅或分多次填充"
            ),
        )


def plan_lengths(
    payload: FillRequest, plan: dict, rows: list[dict]
) -> tuple[int, dict[int, int]]:
    """定目标字数并分摊到各章，返回（目标字数, {序号: 字数}）。

    顺序即纪律：目标字数先用内存里的副本算、判过区间才分摊、分摊成立才返回结果。
    本函数**不写库**——拒绝必须发生在任何写入之前。
    """
    weights = suggested_weights(plan, rows)
    target_length = resolve_target_length(payload, weights)
    ensure_target_length_within_range(target_length)

    overrides = validate_request(payload, rows)
    try:
        lengths = allocate_lengths(
            target_length=target_length,
            seqs=[int(row["seq"]) for row in rows],
            weights=weights,
            overrides=overrides,
        )
    except AllocationError as exc:
        raise HTTPException(status_code=UNPROCESSABLE, detail=exc.detail) from exc

    return target_length, {
        int(row["seq"]): length for row, length in zip(rows, lengths, strict=True)
    }


def start_fill(
    *,
    task_id: int,
    plan: dict,
    payload: FillRequest,
    section_repository: PlanSectionRepository,
    fill_repository: FillTaskRepository,
) -> tuple[dict, list[dict]]:
    """执行入口流程，返回（填充任务行，章节行清单）。

    顺序即纪律：**先判、再写**。所有拒绝都发生在任何写入之前，失败请求不会留下半份
    填充记录，也不会改动章节表——包括「分摊后各章之和超上限」这种只有算完才发现的拒绝。
    """
    rows = section_repository.list_for_plan(plan["id"])
    ensure_sections_exist(rows)
    ensure_no_active_fill(fill_repository, task_id)

    target_length, lengths = plan_lengths(payload, plan, rows)

    # 分摊结果落在章节表（方案是字数真源），让只读清单与填充看到同一个数。
    rows = section_repository.update_target_lengths(plan["id"], lengths)

    fill = fill_repository.start(task_id=task_id, plan_id=plan["id"], target_length=target_length)
    return fill, rows


def preview_section_references(
    *,
    rows: list[dict],
    seq: int,
    retrieval: RetrievalService,
) -> tuple[list[dict], dict | None]:
    """给一章算一份「可用引用片段」预览（工单 24）：**只读不改库**。

    用「章节标题 + 要点」做检索查询——这是本章要写的内容，据此召回最贴切的资料。
    返回（引用卡片, 检索状态）。`to_citation_cards` 契约下的卡片默认全选，前端逐条
    取消；取消后用户会把**保留的**卡片带回填充请求，后端只注入那些。

    章节不存在时由调用方先拦（这里假定 `seq` 已存在于 `rows`，不重复校验）。
    检索不可用不报错：返回空卡片 + 检索状态，界面据状态明示「本次未使用知识库」。
    """
    section = next((row for row in rows if int(row["seq"]) == seq), None)
    if section is None:
        raise HTTPException(status_code=404, detail=f"当前方案没有第 {seq} 章")

    query = f"{section['title']} {section['key_points']}".strip()
    result = retrieval.retrieve(query)
    status_payload = {
        "status": result.status.value,
        "status_label": result.status_label,
        "message": result.message,
        "degraded": result.degraded,
        "truncated": result.truncated,
    }
    return to_citation_cards(result), status_payload
