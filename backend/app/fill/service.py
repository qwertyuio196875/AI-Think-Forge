"""填充阶段的业务逻辑：入口校验、目标字数定值、进度初值（工单 9 / ADR-0006）。

本单**不生成正文**：不调模型、不写 `plan_sections.content_md`。这里只做三件事——
把用户给的字数规整成一次填充的参数、把这次尝试登记成 `fill_tasks` 一行、把章节清单
连同状态一起回给前端做初始进度。

为什么字数定值放在这里而不是路由里：目标字数有三条来源（用户显式给、方案各章建议字数
之和、系统缺省），三条来源的优先级是业务规则，会随 #15 的字数分摊一起演进；路由只该
关心 HTTP 语义。本单刻意**不做分摊**，只把「目标字数」这一个总数与逐章建议字数落库。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.fill_task_repository import FillTaskRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.models.fill import DEFAULT_TARGET_LENGTH, MAX_TARGET_LENGTH, FillRequest

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

    目标字数的上限**不在这里**判：它既可能是用户给的，也可能是各章建议字数之和，只有
    定值之后才知道。见 `ensure_target_length_within_cap`。
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


def resolve_target_length(payload: FillRequest, rows: list[dict]) -> int:
    """定下本次填充的目标字数。

    优先级（规格 §4 + ADR-0006）：
    1. 用户显式给的目标字数；
    2. 各章建议字数之和——但只有在**每一章**都有建议字数时才算；旧格式方案（plan-v2）
       有的章没建议字数，此时求和不成立（缺的章按 0 算会让目标字数凭空缩水）；
    3. 系统缺省值 `DEFAULT_TARGET_LENGTH`。真正的按章分摊属 #15，本单不猜。
    """
    if payload.target_length is not None:
        return int(payload.target_length)

    suggested = [row["target_length"] for row in rows]
    if all(length is not None for length in suggested):
        return int(sum(suggested))
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


def ensure_target_length_within_cap(target_length: int) -> None:
    """ADR-0006：目标字数上限 20000，超出即拒绝并说明原因，不静默截断。"""
    if target_length > MAX_TARGET_LENGTH:
        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail=(
                f"目标字数 {target_length} 超出上限 {MAX_TARGET_LENGTH} 字，"
                "请缩小篇幅或分多次填充"
            ),
        )


def _with_section_lengths(rows: list[dict], lengths: dict[int, int]) -> list[dict]:
    """返回逐章字数生效后的章节行（不改库），用来在**写库之前**定下目标字数。"""
    if not lengths:
        return rows
    adjusted = []
    for row in rows:
        seq = int(row["seq"])
        if seq in lengths:
            adjusted.append({**row, "target_length": lengths[seq]})
        else:
            adjusted.append(row)
    return adjusted


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
    填充记录，也不会改动章节表——包括「各章建议字数之和超上限」这种只有算完才发现的拒绝，
    所以目标字数先用内存里的副本算，判过上限才落库。
    """
    rows = section_repository.list_for_plan(plan["id"])
    ensure_sections_exist(rows)

    section_lengths = validate_request(payload, rows)
    ensure_no_active_fill(fill_repository, task_id)

    target_length = resolve_target_length(
        payload, _with_section_lengths(rows, section_lengths)
    )
    ensure_target_length_within_cap(target_length)

    # 逐章字数落在章节表（方案是字数真源），让只读清单与填充看到同一个数。
    if section_lengths:
        rows = section_repository.update_target_lengths(plan["id"], section_lengths)

    fill = fill_repository.start(task_id=task_id, plan_id=plan["id"], target_length=target_length)
    return fill, rows
