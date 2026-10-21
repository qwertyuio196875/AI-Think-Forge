"""关键词检索的存储抽象（工单 22 / ADR-0005 补充说明）。

与 `store.py` 的 `EmbeddingStore` 平行：向量路径与关键词路径各有各的存储抽象，
但**对外形状一致**——都是「给一段查询 → 回一批按相关度降序的候选」。

为什么单独一层而不是复用 `EmbeddingStore`：

- 两条路径的输入根本不同——向量路径要的是「查询向量 + 模型标识」，关键词路径
  要的是「查询文本」。硬塞进同一个协议会让调用方写出「有向量走这个、有文本走
  那个」的分叉，抽象也就没了意义；
- 将来若换用 SQLite FTS5 之类的外部索引，只需换掉 `KeywordStore` 的实现，
  `RetrievalService` 的调用方一个字都不用改（与 ADR-0005 对向量层的要求同构）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class KeywordStoreError(RuntimeError):
    """关键词检索无法完成（索引读不出来 / 库损坏）；消息可读、不含密钥。"""


@dataclass(frozen=True)
class KeywordCandidate:
    """关键词检索返回的一条候选（**未排序、未过滤**，只做取数与定位拼装）。

    字段与 `store.RetrievalCandidate` 对齐，便于检索层用同一套阈值 / top-k /
    预算规则处理两条路径的结果。
    """

    chunk_id: int
    document_id: int
    source_id: int
    name: str
    seq: int
    text: str
    locator: dict[str, Any]
    score: float


@dataclass(frozen=True)
class KeywordSearchResult:
    """关键词检索的回答：候选（按相关度降序）。"""

    candidates: list[KeywordCandidate] = field(default_factory=list)


@runtime_checkable
class KeywordStore(Protocol):
    """关键词存储的检索抽象（v1 实现见 `sqlite_store.py` 的关键词部分）。"""

    def search(self, query: str, *, limit: int) -> KeywordSearchResult:
        """返回至多 `limit` 条候选，按相关度**降序**；不在此处做阈值过滤。"""
        ...
