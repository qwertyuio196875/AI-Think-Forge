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


class CitationCard(BaseModel):
    """一条引用卡片（工单 23）：文件名 · 段落号 · 相关度，可折叠、默认采用。

    为什么要一个专门的模型而不是复用 `RetrievalHit`：卡片是**展示契约**，
    它多了 `adopted`（默认全选、逐条可取消）与 `collapsible`（可折叠）两个交互字段，
    而那两样不属于检索层。检索层只管「找到了什么」，卡片管「怎么给用户看」。
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: int
    document_id: int
    source_id: int
    # 文件名（展示用）。
    name: str
    # 该资料内的分块序号。
    seq: int
    # 相关度（余弦或关键词覆盖率，0–1）。
    similarity: float
    # 段落号（可能为 None：PDF / PPT 用页 / 幻灯片定位）。
    paragraph: int | None = None
    # 可读定位标签（「第 3 段」这类），前端直接显示，不自己拼。
    locator_label: str
    # 将注入的正文片段（折叠时隐藏，展开时显示）。
    text: str
    # 是否采用；默认全选，用户逐条取消勾选即置 false。
    adopted: bool = True
    # 是否可折叠（规格要求可折叠，默认展开以便一眼看到相关度）。
    collapsible: bool = True


class RetrievalStatusInfo(BaseModel):
    """本次检索的状态（前端据此明示降级 / 未使用知识库，不静默隐藏）。"""

    model_config = ConfigDict(extra="forbid")

    status: str
    status_label: str
    message: str | None = None
    degraded: bool = False
    truncated: bool = False


class FrontierQuestion(BaseModel):
    """前沿中的一个问题：标题、正文、推荐答案，以及「为什么现在问」与「备选方向」。

    工单 23 追加两个字段：
    - `citations`：本次为该问题检索到的引用卡片。**决策型问题恒为空清单**（判定为
      不需要外部依据），空清单与「还没判」不是一回事——因此有问题就一定有这个字段；
    - `retrieval_status`：检索状态。降级或未使用知识库时非空，界面据此明示原因。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    recommended_answer: str = Field(min_length=1)
    # 为什么现在问：该问题的前置条件为何已定、它影响哪些下游决策（缺失容错为 None）。
    why: str | None = None
    # 备选方向：供用户不确定时挑选的可选答案（缺失/空条目容错为空列表）。
    alternatives: list[str] = Field(default_factory=list)
    # 引用卡片（工单 23）：决策型问题为空清单。
    citations: list[CitationCard] = Field(default_factory=list)
    # 检索状态（工单 23）：未检索 / 决策型时为 None。
    retrieval_status: RetrievalStatusInfo | None = None

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
    # 任务级模型覆盖（US23）：为空时使用默认 provider。
    provider_id: int | None = None


class GrillingStartResponse(BaseModel):
    """发起结果：新建的任务 + 第一轮前沿。"""

    model_config = ConfigDict(extra="forbid")

    task: Task
    round: FrontierRound


class AnswerSubmitRequest(BaseModel):
    """提交某一轮的回答（与前沿问题一一对应）。

    `answers` 中为 `null`（或纯空白）的项表示用户把该问题「**暂时跳过**」：
    它保持未定并进入待确认事项清单，绝不作为已定需求进入下游。

    `rejected_chunk_ids`（工单 23）：本次**取消采用**的引用片段。引用卡片默认全选，
    用户逐条取消后，那些片段不得进入本次提示词——否则界面上取消了、实际仍然喂给了
    模型，用户看到的与实际发生的是两回事。
    """

    model_config = ConfigDict(extra="forbid")

    round_no: int = Field(ge=0)
    answers: list[str | None]
    rejected_chunk_ids: list[int] = Field(default_factory=list)


class AdvanceResponse(BaseModel):
    """一次推进的结果：下一轮前沿，或收敛产出的方案草稿。"""

    model_config = ConfigDict(extra="forbid")

    task_id: int
    converged: bool
    next_round: FrontierRound | None
    plan: Plan | None