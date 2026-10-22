"""检索抽象：调用方只认 `EmbeddingStore`，不感知向量存在哪里（工单 21 / ADR-0005）。

ADR-0005 要求「检索层定义 `EmbeddingStore` 抽象，将来换 ANN 索引不动调用方」。
因此这里的顺序是固定的：

1. 调用方给一段查询文本；
2. 检索服务向 `EmbeddingClient` 要查询向量（失败 → 降级，见 service）；
3. 检索服务把 `VectorQuery` 交给 `EmbeddingStore`；
4. `EmbeddingStore` 回 `StoreSearchResult`（候选 + 跳过条数）。

第 4 步之后的一切（阈值、top-k、预算、定位）都在 service 里，与存储实现无关；
将来把 `SqliteVectorStore` 换成 FAISS / 向量库，只要新实现也返回
`StoreSearchResult`，调用方与上述规则一个字都不用改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class RetrievalStoreError(RuntimeError):
    """存储层无法完成检索（库损坏 / 向量数据不可读）；消息可读、不含密钥。"""


@dataclass(frozen=True)
class VectorQuery:
    """一次向量查询：查询向量 + 它来自哪个模型 / 格式版本。

    `model_name` / `version` 一并交给存储层，是为了让「新旧模型向量混存」能在
    存储层就地识别并跳过，而不是把不可比的数字算成相似度。
    """

    vector: tuple[float, ...]
    model_name: str
    version: str


@dataclass(frozen=True)
class RetrievalCandidate:
    """存储层返回的一条候选（**未排序、未过滤**，只做取数与定位拼装）。"""

    chunk_id: int
    document_id: int
    source_id: int
    name: str
    seq: int
    text: str
    locator: dict[str, Any]
    similarity: float


@dataclass(frozen=True)
class StoreSearchResult:
    """存储层的回答：候选 + 因不可比对而跳过的条数。"""

    candidates: list[RetrievalCandidate] = field(default_factory=list)
    skipped_incompatible: int = 0


@runtime_checkable
class EmbeddingStore(Protocol):
    """向量存储的检索抽象（v1 实现见 `SqliteVectorStore`）。"""

    def search(self, query: VectorQuery, *, limit: int) -> StoreSearchResult:
        """返回至多 `limit` 条候选，按相似度**降序**；不在此处做阈值过滤。"""
        ...
