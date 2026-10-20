"""结构化方案（plan）的响应模型。

规格 §4：方案 = 内容（Markdown）+ 状态（draft/confirmed）+ 确认时间。
`round_no` 记录方案由哪一轮问答产生（工单 12「方案与轮次关联」）。

TB-4 追加方案版本记录（工单 13）：每次**对话式修订**留痕一条
（修订前内容、修订后内容、修订时间），旧版本不可丢。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class PlanChangeKind(str, Enum):
    """差异提示里的改动类型。"""

    added = "added"
    removed = "removed"
    modified = "modified"


class PlanChange(BaseModel):
    """差异提示的一条：被改动的章节。"""

    model_config = ConfigDict(extra="forbid")

    kind: PlanChangeKind
    heading: str


class PlanRevision(BaseModel):
    """一次方案修订的版本记录（修订前内容 / 修订后内容 / 修订时间 / 差异提示）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    plan_id: int
    task_id: int
    instruction: str
    previous_content_md: str
    content_md: str
    change_summary: list[PlanChange]
    created_at: str


class PlanRevisionRequest(BaseModel):
    """对已生成方案继续对话：一段修订指令。"""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1)

    @field_validator("instruction")
    @classmethod
    def _reject_blank_instruction(cls, value: str) -> str:
        """纯空白不是有效指令（去掉两端空白后不得为空）。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("修订指令不能为空")
        return stripped


class PlanRevisionResponse(BaseModel):
    """修订结果：更新后的方案 + 本次修订的版本记录（含差异提示）。"""

    model_config = ConfigDict(extra="forbid")

    plan: Plan
    revision: PlanRevision


class PlanRevisionListResponse(BaseModel):
    """方案修订历史（旧版本留痕，供回查）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[PlanRevision]
    total: int