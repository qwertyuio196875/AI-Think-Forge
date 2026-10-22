"""知识库检索的对外模型与参数（工单 21 / ADR-0005）。

**为什么没有路由**：规格 §2 明确「检索结果不作为独立公开接口」——它以「本次对话 /
本次填充所用引用」挂在既有响应里（工单 23 / 24）。所以本模块只定义检索层自己的
契约：状态、命中、结果。调用方（拷问、填充）只认这些字段，不感知向量存在哪里。

三条参数写死在这里，是因为它们同时是回归夹具 `fixtures/knowledge/index.json`
`retrieval` 段的判据；改一个数就要连带重跑语料回归。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

# 取前 6 条，余弦低于 0.3 丢弃，单次注入不超过 3000 汉字（ADR-0005）。
TOP_K = 6
MIN_SIMILARITY = 0.3
MAX_INJECT_HANZI = 3000


class RetrievalStatus(str, Enum):
    """检索结果的三种状态：正常 / 降级 / 未使用知识库。"""

    ok = "ok"
    degraded = "degraded"
    unavailable = "unavailable"


# 中文标签由后端统一给，避免前端（或下游工单）各自翻译出第三种说法。
RETRIEVAL_STATUS_LABELS: dict[str, str] = {
    "ok": "正常检索",
    "degraded": "降级检索",
    "unavailable": "本次未使用知识库",
}


class LocatorInfo(BaseModel):
    """命中位置：既给可读标签，也给结构化字段（格式 / 段落 / 页 / 幻灯片）。"""

    model_config = ConfigDict(extra="forbid")

    format: str
    label: str
    paragraph: int | None = None
    line: int | None = None
    page: int | None = None
    slide: int | None = None


class RetrievalHit(BaseModel):
    """一条命中：来源文件名 + 位置 + 相关度 + 将要注入的正文。

    `hanzi_count` 是**这条命中实际占用的注入预算**（含定位标签那一行），
    因此「预算够不够」不必由调用方再算一遍。
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: int
    document_id: int
    source_id: int
    name: str
    seq: int
    similarity: float
    format: str
    locator: dict[str, Any] = Field(default_factory=dict)
    locator_label: str
    # 位置字段平铺一份：引用卡片（#23）与参考资料（#24）不必自己解析 locator。
    paragraph: int | None = None
    line: int | None = None
    page: int | None = None
    slide: int | None = None
    text: str
    hanzi_count: int


class RetrievalResult(BaseModel):
    """一次检索的完整结果：状态、命中、注入预算用量，以及给用户看的一句话。

    `degraded` 由 `status` 派生而不是单独传值，避免出现「状态说降级、标记说正常」
    这种自相矛盾的响应。
    """

    model_config = ConfigDict(extra="forbid")

    status: RetrievalStatus
    status_label: str
    message: str | None = None
    hits: list[RetrievalHit] = Field(default_factory=list)
    total_hanzi: int = 0
    truncated: bool = False
    # 因模型 / 版本 / 维度不一致（或向量数据损坏）而跳过的条数；非 0 时建议重建索引。
    skipped_incompatible: int = 0
    # 只有分块、没有向量的资料份数；非 0 说明这些资料当前检索不到。
    missing_index_count: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def degraded(self) -> bool:
        """是否处于降级状态（响应字段，前端据此明示，不静默隐藏）。"""
        return self.status is RetrievalStatus.degraded
