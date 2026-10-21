"""知识库检索层（工单 21 / ADR-0005；工单 22 接入关键词降级）。

对外只暴露三样东西：

- `EmbeddingStore`（`store.py`）：检索抽象，调用方不感知向量存在哪里；
- `RetrievalService.retrieve(query)`：把查询文本变成 `RetrievalResult`；
- `RetrievalResult` / `RetrievalHit` / 三个参数常量（`models.py`）：下游 #23 / #24
  渲染引用卡片、拼提示词、算预算时只认这些字段。

**没有 HTTP 路由**：规格 §2 明确检索结果不作为独立公开接口，只挂在拷问 / 填充的
既有响应里。

**降级路径（工单 22）**：嵌入不可用时改走**关键词检索**（二元组匹配，见
`keyword.py`），RAG 仍然可用，状态标成「降级检索」；关键词检索也不可用时标成
「本次未使用知识库」——两种状态都明示，绝不静默按正常流程继续。两条路径共用
同一套阈值 / top-k / 注入预算规则。
"""

from __future__ import annotations

from app.retrieval.keyword import bigram_tokens, keyword_coverage
from app.retrieval.keyword_store import (
    KeywordCandidate,
    KeywordSearchResult,
    KeywordStore,
    KeywordStoreError,
)
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
from app.retrieval.sqlite_store import SqliteKeywordStore, SqliteVectorStore
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
    "KeywordCandidate",
    "KeywordSearchResult",
    "KeywordStore",
    "KeywordStoreError",
    "LocatorInfo",
    "RetrievalCandidate",
    "RetrievalHit",
    "RetrievalResult",
    "RetrievalService",
    "RetrievalStatus",
    "RetrievalStoreError",
    "SqliteKeywordStore",
    "SqliteVectorStore",
    "StoreSearchResult",
    "VectorQuery",
    "bigram_tokens",
    "describe_locator",
    "keyword_coverage",
]
