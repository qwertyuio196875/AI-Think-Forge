"""进入下游阶段的共享闸门（方案确认判定）。

同一套判据被两条入口复用：成品生成（`/generations`，工单 13 起就有）与填充
（`/fill`，工单 9）。判据本身只有一条：**方案必须存在、已确认、且没有未处置的待确认事项**。
把它写成两份，迟早会有一份被改漏——那正是「未确认的推测流进下游」的经典路径。

文案按用途分开：生成与填充的报错要指向用户当下能做的下一步（去确认方案 / 去返回修订），
所以 `purpose` 只切换措辞，**不切换判据**。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.api.errors import require_task

# 各用途的措辞。键只有两个：generate（成品生成）、fill（填充）。
_GATE_TEXTS: dict[str, tuple[str, str, str]] = {
    "generate": (
        "任务 {task_id} 尚无结构化方案，无法生成",
        "结构化方案尚未确认，拒绝生成（方案确认是进入生成阶段的唯一闸门）",
        (
            "仍有未处置的待确认事项，拒绝生成"
            "（未确认的推测不得进入下游；请先确认或搁置这些条目）"
        ),
    ),
    "fill": (
        "任务 {task_id} 尚无结构化方案，无法开始填充",
        "结构化方案尚未确认，拒绝填充（方案确认是进入填充阶段的唯一闸门）",
        (
            "仍有未处置的待确认事项，拒绝填充"
            "（未确认的推测不得进入下游；请先确认或搁置这些条目）"
        ),
    ),
}


def require_confirmed_plan(
    task_id: int,
    task_repository,
    plan_repository,
    open_item_repository,
    *,
    purpose: str = "generate",
) -> dict:
    """返回已确认且无未定条目的当前方案；否则抛 404 / 409。

    三段判定（顺序即优先级：先「有没有方案」，再「确认没确认」，最后「有没有未定条目」）：
    1. 任务不存在 → 404；
    2. 无当前方案 / 方案非 confirmed → 409；
    3. 仍有 `open` 的待确认事项 → 409（纵深防御，见 `app/api/routes/generations.py` 说明）。
    """
    missing_plan, unconfirmed, unresolved = _GATE_TEXTS[purpose]

    require_task(task_repository, task_id)

    plan = plan_repository.get_current(task_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=missing_plan.format(task_id=task_id),
        )
    if plan["status"] != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=unconfirmed,
        )
    if open_item_repository.has_unresolved(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=unresolved,
        )

    return plan
