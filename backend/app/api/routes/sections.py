"""成品章节清单（只读；工单 7 / ADR-0006）。

只有一个端点：`GET /api/tasks/{task_id}/sections`。**刻意只有只读**——改名、拖拽排序、
增删章节一律不做（ADR-0006：那等于把方案直接编辑提前，超出本单范围）。

口径：
- 任务不存在 → 404；任务存在但还没有结构化方案 → 404（与 `GET /plan` 一致）；
- 当前方案没有可切分的章节 → **200 + 空清单**，不是错误（工单 7 验收 ②）；
- 字数由后端按唯一入口 `app.hanzi.count_hanzi` 现算，前端不另写一套；
- `plan_id` 一并返回：章节清单一律属于某一版方案，前端据此判断清单是否过期。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import PlanRepositoryDep, PlanSectionRepositoryDep, TaskRepositoryDep
from app.api.errors import require_task
from app.models.plan_section import PlanSectionListResponse
from app.sections.service import to_section_items

router = APIRouter(prefix="/tasks", tags=["sections"])


@router.get("/{task_id}/sections", response_model=PlanSectionListResponse)
def list_sections(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
) -> PlanSectionListResponse:
    """读取某任务成品的章节清单（只读，含每章状态与已写汉字数）。"""
    require_task(task_repository, task_id)

    plan = plan_repository.get_current(task_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 尚无结构化方案"
        )

    items = to_section_items(section_repository.list_for_plan(plan["id"]))
    return PlanSectionListResponse(plan_id=plan["id"], items=items, total=len(items))
