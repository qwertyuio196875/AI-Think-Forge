"""拷问相关的请求 / 响应模型。

`recommended_answer` 必填（min_length=1）：每题附推荐答案是拷问规则的硬结构约束，
由模型输出解析与 API 校验共同保证，不依赖模型自觉。

TB-4 增补（工单 13，对应规格 User Story 5）：`why`（为什么现在问）与 `alternatives`
（备选方向）随 `grilling-v2` 输出契约引入。**解析层对两字段容错**——缺失即落 `None` / `[]`，
不在结构上强制报错（模型偶尔漏字段不应让整轮作废）；「要求模型给出」由提示词契约承担。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.plan import Plan
from app.models.task import Task


class FrontierQuestion(BaseModel):
    """前沿中的一个问题：标题、正文、推荐答案，以及「为什么现在问」与「备选方向」。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    recommended_answer: str = Field(min_length=1)
    # 为什么现在问：该问题的前置条件为何已定、它影响哪些下游决策（缺失容错为 None）。
    why: str | None = None
    # 备选方向：供用户不确定时挑选的可选答案（缺失/空条目容错为空列表）。
    alternatives: list[str] = Field(default_factory=list)

    @field_validator("why")
    @classmethod
    def _blank_why_to_none(cls, value: str | None) -> str | None:
        """空串 / 纯空白归一为 None，避免前端渲染出空的「为什么现在问」栏。"""
        if value is None:
            return None
        return value.strip() or None

    @field_validator("alternatives")
    @classmethod
    def _drop_blank_alternatives(cls, value: list[str]) -> list[str]:
        """剔除空 / 纯空白的备选方向条目。"""
        return [item.strip() for item in value if item and item.strip()]


class FrontierRound(BaseModel):
    """一个轮次：该轮的前沿问题集与用户回答。"""

    model_config = ConfigDict(extra="forbid")

    round_no: int
    frontier: list[FrontierQuestion]
    answers: list[str]


class DialogueMessage(BaseModel):
    """对话流中的一条消息（供前端按序渲染）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    round_no: int
    role: str
    content: str
    created_at: str


class Dialogue(BaseModel):
    """某任务的完整对话状态：种子输入 + 各轮次 + 原始消息流。"""

    model_config = ConfigDict(extra="forbid")

    task_id: int
    seed_input: str | None
    rounds: list[FrontierRound]
    messages: list[DialogueMessage]


class GrillingStartRequest(BaseModel):
    """一句话 / 一段描述发起主题创作。"""

    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1)


class GrillingStartResponse(BaseModel):
    """发起结果：新建的任务 + 第一轮前沿。"""

    model_config = ConfigDict(extra="forbid")

    task: Task
    round: FrontierRound


class AnswerSubmitRequest(BaseModel):
    """提交某一轮的回答（与前沿问题一一对应）。

    `answers` 中为 `null`（或纯空白）的项表示用户把该问题「**暂时跳过**」：
    它保持未定并进入待确认事项清单，绝不作为已定需求进入下游。
    """

    model_config = ConfigDict(extra="forbid")

    round_no: int = Field(ge=0)
    answers: list[str | None]


class AdvanceResponse(BaseModel):
    """一次推进的结果：下一轮前沿，或收敛产出的方案草稿。"""

    model_config = ConfigDict(extra="forbid")

    task_id: int
    converged: bool
    next_round: FrontierRound | None
    plan: Plan | None