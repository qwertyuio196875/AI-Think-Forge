"""任务路由：创建 / 列表 / 按 id 读取 / 状态迁移 / 删除（先看影响范围再确认）。

路由只负责校验与响应组织，存储细节委托给 TaskRepository。
状态机（术语「任务」）：in_progress（进行中）↔ completed（已完成）由本模块的
`POST /tasks/{id}/status` 迁移；deleted（已删除）只能经 `DELETE /tasks/{id}` 达成，
且为**软删除**（留痕、不物理清库，规格 US 27），并要求**先看影响范围、确认后才执行**。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    GenerationRepositoryDep,
    MessageRepositoryDep,
    OpenItemRepositoryDep,
    PlanRepositoryDep,
    PlanRevisionRepositoryDep,
    ProviderRepositoryDep,
    TaskRepositoryDep,
)
from app.api.errors import require_task
from app.db.generation_repository import GenerationRepository
from app.db.message_repository import MessageRepository
from app.db.open_item_repository import OpenItemRepository
from app.db.plan_repository import PlanRepository
from app.db.plan_revision_repository import PlanRevisionRepository
from app.deletion import build_impact
from app.models.task import (
    Task,
    TaskCreate,
    TaskDeletionImpact,
    TaskDeletionResult,
    TaskKind,
    TaskListResponse,
    TaskModelUpdate,
    TaskStatus,
    TaskStatusUpdate,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Task)
def create_task(
    payload: TaskCreate,
    repository: TaskRepositoryDep,
    provider_repository: ProviderRepositoryDep,
) -> Task:
    """新建任务（主题创作 / 资料分析）；可带任务级模型覆盖。"""
    if payload.provider_id is not None:
        provider = provider_repository.get_by_id(payload.provider_id)
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"模型配置 {payload.provider_id} 不存在，请重新选择",
            )

    record = repository.create(
        payload.kind.value, payload.title, provider_id=payload.provider_id
    )
    return Task.from_record(record)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    repository: TaskRepositoryDep,
    kind: TaskKind | None = None,
    status: TaskStatus | None = None,
) -> TaskListResponse:
    """按可选 kind / status 过滤列出任务。"""
    records = repository.list(
        kind=kind.value if kind is not None else None,
        status=status.value if status is not None else None,
    )
    items = [Task.from_record(record) for record in records]
    return TaskListResponse(items=items, total=len(items))


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: int, repository: TaskRepositoryDep) -> Task:
    """按 id 读取任务；不存在返回 404（已软删除的任务仍可读，删除只是留痕标记）。"""
    return Task.from_record(require_task(repository, task_id))


@router.put("/{task_id}/model", response_model=Task)
def update_task_model(
    task_id: int,
    payload: TaskModelUpdate,
    task_repository: TaskRepositoryDep,
    provider_repository: ProviderRepositoryDep,
) -> Task:
    """设置 / 清除任务级模型覆盖（US23）；`provider_id=null` 回到默认。"""
    task = require_task(task_repository, task_id)
    if task["status"] == TaskStatus.deleted.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务 {task_id} 已删除，无法变更模型配置（删除是留痕的终态）",
        )

    if payload.provider_id is not None:
        provider = provider_repository.get_by_id(payload.provider_id)
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"模型配置 {payload.provider_id} 不存在，请重新选择",
            )

    updated = task_repository.set_provider_id(task_id, payload.provider_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )
    return Task.from_record(updated)


@router.post("/{task_id}/status", response_model=Task)
def update_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    repository: TaskRepositoryDep,
) -> Task:
    """迁移任务状态：completed（已完成）/ in_progress（重新打开）。

    已删除的任务不可再迁移（409）：删除是留痕的终态，不靠改状态复活。
    """
    current = require_task(repository, task_id)
    if current["status"] == TaskStatus.deleted.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务 {task_id} 已删除，无法再变更状态（删除是留痕的终态）",
        )

    updated = repository.set_status(task_id, payload.status.value)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在")
    return Task.from_record(updated)


@router.delete("/{task_id}", response_model=TaskDeletionResult)
def delete_task(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    plan_repository: PlanRepositoryDep,
    revision_repository: PlanRevisionRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    generation_repository: GenerationRepositoryDep,
    confirm: bool = Query(default=False),
) -> TaskDeletionResult:
    """删除任务：**先返回影响范围，确认后才执行**（规格 US 27）。

    - 未带 `confirm=true` → 409，`detail` 即影响范围（对话条数 / 方案 / 待确认事项 / 成品文件数）
      与继续方式——用户不该在看不见代价的情况下删掉本地数据；
    - 带 `confirm=true` → 软删除（置为已删除并留 `deleted_at`），对话与方案一条不删；
      重复删除幂等，保留首次删除时间。
    """
    task = require_task(task_repository, task_id)

    impact = _impact_for(
        task,
        message_repository=message_repository,
        plan_repository=plan_repository,
        revision_repository=revision_repository,
        open_item_repository=open_item_repository,
        generation_repository=generation_repository,
    )

    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{impact.summary} 确认无误后重试（加 confirm=true）。",
        )

    already_deleted = task["status"] == TaskStatus.deleted.value
    deleted = task_repository.mark_deleted(task_id)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在")

    return TaskDeletionResult(
        task=Task.from_record(deleted),
        deleted_at=deleted["deleted_at"],
        already_deleted=already_deleted,
        impact=impact,
    )


@router.get("/{task_id}/deletion-impact", response_model=TaskDeletionImpact)
def get_deletion_impact(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    plan_repository: PlanRepositoryDep,
    revision_repository: PlanRevisionRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    generation_repository: GenerationRepositoryDep,
) -> TaskDeletionImpact:
    """取删除影响范围（确认弹层的数据源；不改动任何数据）。"""
    task = require_task(task_repository, task_id)

    return _impact_for(
        task,
        message_repository=message_repository,
        plan_repository=plan_repository,
        revision_repository=revision_repository,
        open_item_repository=open_item_repository,
        generation_repository=generation_repository,
    )


def _impact_for(
    task: dict,
    *,
    message_repository: MessageRepository,
    plan_repository: PlanRepository,
    revision_repository: PlanRevisionRepository,
    open_item_repository: OpenItemRepository,
    generation_repository: GenerationRepository,
) -> TaskDeletionImpact:
    """汇总各表的真实计数为影响范围（删除入口与影响范围预览共用）。"""
    counts = message_repository.counts_for_task(task["id"])
    return build_impact(
        task,
        dialogue_messages=counts["messages"],
        rounds=counts["rounds"],
        plans=plan_repository.count_for_task(task["id"]),
        plan_revisions=revision_repository.count_for_task(task["id"]),
        open_items=open_item_repository.count_for_task(task["id"]),
        deliverable_files=generation_repository.count_deliverable_files(task["id"]),
    )