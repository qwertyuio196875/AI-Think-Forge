"""知识库检索层（工单 21 / ADR-0005）。

对外只暴露三样东西：

- `EmbeddingStore`（`store.py`）：检索抽象，调用方不感知向量存在哪里；
- `RetrievalService.retrieve(query)`：把查询文本变成 `RetrievalResult`；
- `RetrievalResult` / `RetrievalHit` / 三个参数常量（`models.py`）：下游 #23 / #24
  渲染引用卡片、拼提示词、算预算时只认这些字段。

**没有 HTTP 路由**：规格 §2 明确检索结果不作为独立公开接口，只挂在拷问 / 填充的
既有响应里。降级骨架的边界也在这一层：本工单只给出降级标记与原因，真正的关键词
检索由 #22 实现在 `RetrievalService` 的降级分支里，参数与预算规则不变。
"""

from __future__ import annotations

from app.retrieval.locator import describe_locator
from app.retrieval.models import (
    MAX_INJECT_HANZI,
    MIN_SIMILARITY,
    RETRIEVAL_STATUS_LABELS,
    TOP_K,
    LocatorInfo,
    RetrievalHit,
    RetrievalResult,
    RetrievalStatus,
)
from app.retrieval.service import RetrievalService
from app.retrieval.sqlite_store import SqliteVectorStore
from app.retrieval.store import (
    EmbeddingStore,
    RetrievalCandidate,
    RetrievalStoreError,
    StoreSearchResult,
    VectorQuery,
)

__all__ = [
    "MAX_INJECT_HANZI",
    "MIN_SIMILARITY",
    "RETRIEVAL_STATUS_LABELS",
    "TOP_K",
    "EmbeddingStore",
    "LocatorInfo",
    "RetrievalCandidate",
    "RetrievalHit",
    "RetrievalResult",
    "RetrievalService",
    "RetrievalStatus",
    "RetrievalStoreError",
    "SqliteVectorStore",
    "StoreSearchResult",
    "VectorQuery",
    "describe_locator",
]
