"""填充入口（工单 9 / ADR-0006）：`POST /api/tasks/{task_id}/fill`。

为什么是独立端点而不是 `/generations` 的一个参数：填充与成品生成是**两个阶段、两种
保证**——填充会调模型、写正文、可能失败在第三章；生成是确定性渲染。混在一个端点上，
前端就没法表达「先填充，再导出」这个先后关系（ADR-0006 决策一）。

本单只到「入口 + 初始进度」为止：建一条 `fill_tasks` 记录、返回章节清单。**不调模型、
不写正文**（#10 / #11 接手）。因此响应里的 `completed_sections` 恒为 0、各章 `status`
恒为 `pending`。

拒绝口径（错误码沿用全局约定）：
- 任务不存在 → 404；
- 无方案 / 方案未确认 / 有未处置待确认事项 → 409（与 `/generations` 同一套闸门，口径
  见 `app.api.gates`）；
- 已确认但切不出章节 → 422，并提示返回修订方案（ADR-0006：不猜、不退化切分）；
- 逐章字数含不存在的章节序号 / 目标字数超上限 → 422。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import (
    FillTaskRepositoryDep,
    OpenItemRepositoryDep,
    PlanRepositoryDep,
    PlanSectionRepositoryDep,
    TaskRepositoryDep,
)
from app.api.gates import require_confirmed_plan
from app.fill.service import start_fill
from app.models.fill import FILL_STATUS_LABELS, FillRequest, FillResponse
from app.sections.service import to_section_items

router = APIRouter(prefix="/tasks", tags=["fill"])


@router.post("/{task_id}/fill", response_model=FillResponse)
def start_fill_task(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    fill_repository: FillTaskRepositoryDep,
    payload: FillRequest | None = None,
) -> FillResponse:
    """开始一次填充：落实字数参数、登记填充任务、返回初始进度。

    请求体可省略（`{}` 或空）：目标字数此时按方案各章建议字数求和，方案没给则用缺省值。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    fill, rows = start_fill(
        task_id=task_id,
        plan=plan,
        payload=payload or FillRequest(),
        section_repository=section_repository,
        fill_repository=fill_repository,
    )

    items = to_section_items(rows)
    return FillResponse(
        id=fill["id"],
        task_id=fill["task_id"],
        plan_id=fill["plan_id"],
        target_length=fill["target_length"],
        completed_sections=fill["completed_sections"],
        status=fill["status"],
        status_label=FILL_STATUS_LABELS.get(fill["status"], fill["status"]),
        error=fill["error"],
        created_at=fill["created_at"],
        items=items,
        total=len(items),
    )
