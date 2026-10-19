"""成品生成入口（硬闸门 + Word 成品管线）。

规格 User Story 10 / 术语「方案确认」：**只有方案被用户显式确认后**才进入正式生成，
未获批准的内容永不写出。本入口的职责就是把这条闸门落在**服务端**——不能只靠前端
不显示按钮（前端不显示是 UI 约定，不是安全边界）。

判定读规格 §4 的 `plans.status` 与工单 13 的待确认事项清单：
- 无方案，或方案仍为 `draft` → 409（拒绝生成，且不产生任何成品）；
- 存在 `open`（未处置）的待确认事项 → 409（未确认的推测不得进入下游，规格 US 9）。
  这一条在正常流程里已由「确认方案」入口拦在前面（见 `plan/confirm`，TB-10 修）；此处保留
  同一判定作**纵深防御**：无论方案如何变成 confirmed，只要还有未定条目就不放行；
- 已 `confirmed` 且无未定条目 → 交 Word 成品管线（TB-5，`app.generation`）。

闸门通过后仍可能失败，且失败一律**明确报错、不产出成品**：
- 模板缺失 / 损坏 / 不是 .docx → 400（模板机制，规格 US 19）；
- 完整性检查未通过 → 500（结构损坏的成品不交付，规格 US 22）；
- 单文件 HTML 演示 → 501（TB-6，ADR-0003 的另一轨）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    DataDirDep,
    GenerationRepositoryDep,
    OpenItemRepositoryDep,
    PlanRepositoryDep,
    TaskRepositoryDep,
    TemplateRepositoryDep,
    TemplatesDirDep,
)
from app.generation.service import generate_word_deliverable
from app.generation.templates import TemplateError
from app.generation.word import DeliverableIntegrityError
from app.models.generation import (
    Generation,
    GenerationFormat,
    GenerationListResponse,
    GenerationRequest,
    GenerationResponse,
)

router = APIRouter(prefix="/tasks", tags=["generations"])


def _require_confirmed_plan(
    task_id: int, task_repository, plan_repository, open_item_repository
) -> dict:
    """闸门判定：返回已确认且无未定条目的方案；否则抛 404/409。"""
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

    return plan


@router.post(
    "/{task_id}/generations",
    status_code=status.HTTP_201_CREATED,
    response_model=GenerationResponse,
)
def request_generation(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    template_repository: TemplateRepositoryDep,
    generation_repository: GenerationRepositoryDep,
    data_dir: DataDirDep,
    templates_dir: TemplatesDirDep,
    payload: GenerationRequest | None = None,
) -> GenerationResponse:
    """请求生成成品：方案未确认、或仍有未定的待确认事项时，在服务端拒绝。"""
    plan = _require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository
    )

    request = payload or GenerationRequest()

    if request.format is GenerationFormat.html:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="单文件 HTML 演示成品由 TB-6 落地（ADR-0003 的另一轨）",
        )

    try:
        result = generate_word_deliverable(
            task_id=task_id,
            plan=plan,
            requested_template=request.template,
            data_dir=data_dir,
            templates_dir=templates_dir,
            template_repository=template_repository,
            generation_repository=generation_repository,
        )
    except TemplateError as exc:
        # 模板缺失 / 损坏 → 明确报错，绝不静默退回空白生成（规格 US 19）。
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DeliverableIntegrityError as exc:
        # 结构损坏的成品不交付（规格 US 22）；产物已由服务层丢弃。
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"成品完整性检查未通过，已丢弃产物：{exc}",
        ) from exc

    return GenerationResponse(**result)


@router.get("/{task_id}/generations", response_model=GenerationListResponse)
def list_generations(
    task_id: int,
    task_repository: TaskRepositoryDep,
    generation_repository: GenerationRepositoryDep,
) -> GenerationListResponse:
    """某任务已生成的成品记录（供成品卡渲染；含每次实际所用模板）。"""
    if task_repository.get(task_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )

    items = [Generation(**record) for record in generation_repository.list_for_task(task_id)]
    return GenerationListResponse(items=items, total=len(items))