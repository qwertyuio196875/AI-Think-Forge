"""任务相关的请求 / 响应模型。

字段集固定为 id、kind、title、status、created_at、updated_at（规格 §4 最小集
+ title 小幅增补，供前端任务列表显示可读标签）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class TaskKind(str, Enum):
    """任务类型：主题创作 / 资料分析。"""

    creation = "creation"
    analysis = "analysis"


class TaskStatus(str, Enum):
    """任务状态。"""

    in_progress = "in_progress"
    completed = "completed"
    deleted = "deleted"


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


class TaskListResponse(BaseModel):
    """任务列表响应：条目 + 总数。"""

    items: list[Task]
    total: int
