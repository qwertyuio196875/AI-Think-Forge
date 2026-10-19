"""任务路由：创建 / 列表 / 按 id 读取。

路由只负责校验与响应组织，存储细节委托给 TaskRepository。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import TaskRepositoryDep
from app.models.task import Task, TaskCreate, TaskKind, TaskListResponse, TaskStatus

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Task)
def create_task(payload: TaskCreate, repository: TaskRepositoryDep) -> Task:
    """新建任务（主题创作 / 资料分析）。"""
    record = repository.create(payload.kind.value, payload.title)
    return Task(**record)


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
    items = [Task(**record) for record in records]
    return TaskListResponse(items=items, total=len(items))


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: int, repository: TaskRepositoryDep) -> Task:
    """按 id 读取任务；不存在返回 404。"""
    record = repository.get(task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在")
    return Task(**record)
