"""API 层共用的错误判定（统一可读中文，避免各路由重复样板）。"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.task_repository import TaskRepository


def require_task(task_repository: TaskRepository, task_id: int) -> dict:
    """读取任务；不存在时抛统一的 404「任务 {id} 不存在」。

    返回任务记录，调用方可继续检查状态（例如已删除任务的操作应回 409）。
    """
    task = task_repository.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )
    return task