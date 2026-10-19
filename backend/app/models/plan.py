"""结构化方案（plan）的响应模型。

规格 §4：方案 = 内容（Markdown）+ 状态（draft/confirmed）+ 确认时间。
`round_no` 记录方案由哪一轮问答产生（工单 12「方案与轮次关联」）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class PlanStatus(str, Enum):
    """方案状态：草稿 / 已确认（方案确认是进入生成阶段的唯一闸门）。"""

    draft = "draft"
    confirmed = "confirmed"


class Plan(BaseModel):
    """结构化方案（对外字段集）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    task_id: int
    round_no: int
    content_md: str
    status: PlanStatus
    confirmed_at: str | None