"""任务相关的请求 / 响应模型。

字段集固定为 id、kind、title、status、created_at、updated_at（规格 §4 最小集
+ title 小幅增补，供前端任务列表显示可读标签）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class TaskKind(str, Enum):
    """任务类型：主题创作 / 资料分析。"""

    creation = "creation"
    analysis = "analysis"


class TaskStatus(str, Enum):
    """任务状态：进行中 / 已完成 / 已删除（删除为软删除留痕）。"""

    in_progress = "in_progress"
    completed = "completed"
    deleted = "deleted"


class TaskStatusUpdate(BaseModel):
    """状态迁移请求体：只允许迁入 进行中 / 已完成。

    `deleted` 不在本模型取值范围：删除必须走 `DELETE /tasks/{id}`（先看影响范围再确认）。
    """

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus

    @field_validator("status")
    @classmethod
    def _reject_deleted(cls, value: TaskStatus) -> TaskStatus:
        """拒绝经状态迁移「删除」任务，避免绕过删除入口的影响范围确认。"""
        if value is TaskStatus.deleted:
            raise ValueError("删除须走删除入口（先返回影响范围再确认）")
        return value


class TaskCreate(BaseModel):
    """创建任务请求体。"""

    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    title: str | None = None


class Task(BaseModel):
    """任务响应体（对外固定字段集）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: TaskKind
    title: str | None
    status: TaskStatus
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: dict) -> Task:
        """从存储层记录构造响应体，只取对外字段。

        `tasks` 表还存有内部留痕字段（如 `deleted_at`），它们不属对外契约，
        故显式挑字段而非把整行灌进模型。
        """
        return cls(
            id=record["id"],
            kind=record["kind"],
            title=record["title"],
            status=record["status"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )


class TaskListResponse(BaseModel):
    """任务列表响应：条目 + 总数。"""

    items: list[Task]
    total: int


class TaskDeletionImpact(BaseModel):
    """删除影响范围（规格 US 27：删除操作明示影响范围）。

    数字全部来自已持久化的真实数据；成品生成管线未落地时 `deliverable_files` 如实为 0。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: int
    title: str | None
    kind: TaskKind
    status: TaskStatus
    dialogue_messages: int
    rounds: int
    plans: int
    plan_revisions: int
    open_items: int
    deliverable_files: int
    summary: str


class TaskDeletionResult(BaseModel):
    """删除结果：软删除后的任务留痕 + 本次确认的影响范围。"""

    model_config = ConfigDict(extra="forbid")

    task: Task
    deleted_at: str
    already_deleted: bool
    impact: TaskDeletionImpact
