"""成品生成入口（硬闸门）。

规格 User Story 10 / 术语「方案确认」：**只有方案被用户显式确认后**才进入正式生成，
未获批准的内容永不写出。本入口的职责就是把这条闸门落在**服务端**——不能只靠前端
不显示按钮（前端不显示是 UI 约定，不是安全边界）。

判定读规格 §4 的 `plans.status` 与工单 13 的待确认事项清单：
- 无方案，或方案仍为 `draft` → 409（拒绝生成，且不产生任何成品）；
- 存在 `open`（未处置）的待确认事项 → 409（未确认的推测不得进入下游，规格 US 9）。
  这一条在正常流程里已由「确认方案」入口拦在前面（见 `plan/confirm`，TB-10 修）；此处保留
  同一判定作**纵深防御**：无论方案如何变成 confirmed，只要还有未定条目就不放行；
- 已 `confirmed` 且无未定条目 → 放行到生成管线（Word / 单文件 HTML，见 ADR-0003）。
  生成管线本身由 TB-5/TB-6 落地，本单只保证闸门判定，故此处以 501 明确「能力待落地」。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import OpenItemRepositoryDep, PlanRepositoryDep, TaskRepositoryDep

router = APIRouter(prefix="/tasks", tags=["generations"])


@router.post("/{task_id}/generations")
def request_generation(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
) -> None:
    """请求生成成品：方案未确认、或仍有未定的待确认事项时，在服务端拒绝。"""
    if task_repository.get(task_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )

    plan = plan_repository.get_current(task_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务 {task_id} 尚无结构化方案，无法生成",
        )
    if plan["status"] != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="结构化方案尚未确认，拒绝生成（方案确认是进入生成阶段的唯一闸门）",
        )

    if open_item_repository.has_unresolved(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "仍有未处置的待确认事项，拒绝生成"
                "（未确认的推测不得进入下游；请先确认或搁置这些条目）"
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="方案已确认，但成品生成管线由 TB-5/TB-6 落地",
    )