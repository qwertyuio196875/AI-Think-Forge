"""拷问相关的请求 / 响应模型。

`recommended_answer` 必填（min_length=1）：每题附推荐答案是拷问规则的硬结构约束，
由模型输出解析与 API 校验共同保证，不依赖模型自觉。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.plan import Plan
from app.models.task import Task


class FrontierQuestion(BaseModel):
    """前沿中的一个问题：标题、正文与推荐答案。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    recommended_answer: str = Field(min_length=1)


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
    """提交某一轮的回答（与前沿问题一一对应）。"""

    model_config = ConfigDict(extra="forbid")

    round_no: int = Field(ge=0)
    answers: list[str]


class AdvanceResponse(BaseModel):
    """一次推进的结果：下一轮前沿，或收敛产出的方案草稿。"""

    model_config = ConfigDict(extra="forbid")

    task_id: int
    converged: bool
    next_round: FrontierRound | None
    plan: Plan | None