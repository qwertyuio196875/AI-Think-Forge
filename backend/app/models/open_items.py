"""待确认事项（open items）的请求 / 响应模型。

术语（GLOSSARY）：「待确认事项 = 系统标记的、尚未决定的关键信息清单。用户未回应不等于同意。」
状态：open（待确认）/ confirmed（用户确认）/ dismissed（用户认定不需要）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class OpenItemStatus(str, Enum):
    """待确认事项状态。"""

    open = "open"
    confirmed = "confirmed"
    dismissed = "dismissed"


class ResolvableStatus(str, Enum):
    """用户处置动作允许的终态（open 不是处置结果）。"""

    confirmed = "confirmed"
    dismissed = "dismissed"


class OpenItem(BaseModel):
    """一条待确认事项（对外字段集）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    task_id: int
    round_no: int  # 来源轮次
    text: str  # 条目
    status: OpenItemStatus
    created_at: str
    resolved_at: str | None


class OpenItemListResponse(BaseModel):
    """某任务的待确认事项清单。"""

    model_config = ConfigDict(extra="forbid")

    items: list[OpenItem]
    total: int


class OpenItemResolveRequest(BaseModel):
    """用户对待确认事项的处置动作。"""

    model_config = ConfigDict(extra="forbid")

    status: ResolvableStatus = Field(
        description="confirmed = 承认该推测成为已定需求；dismissed = 认定不需要"
    )