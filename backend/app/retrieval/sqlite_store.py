"""v1 检索存储：SQLite 里读块、内存 numpy 暴力余弦（工单 21 / ADR-0005）。

零新服务、零向量库依赖：向量本来就在 `embeddings.vector_json` 里按分块存好，
本模块每次检索现读、现算。语料规模是「个人工作台的资料」，几百分块，
一次全量点积的开销远小于引入 ANN 索引的复杂度。

`EmbeddingRepository` 是 `embeddings` 表的唯一写入点与校验读取点，所以这里
**不自己解析 vector_json**：读取一律走 `list_vectors(document_id)`，由它负责
维度与模型一致性校验，并把「不一致」翻译成 `EmbeddingDimensionError`。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from app.db.analysis_repository import AnalysisRepository
from app.db.embedding_repository import EmbeddingRepository
from app.db.knowledge_repository import INDEX_STATUS_STORED, KnowledgeRepository
from app.providers.embedding_client import EmbeddingDimensionError
from app.retrieval.store import (
    RetrievalCandidate,
    RetrievalStoreError,
    StoreSearchResult,
    VectorQuery,
)


class SqliteVectorStore:
    """`EmbeddingStore` 的 v1 实现：SQLite 取块 + numpy 暴力余弦。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._knowledge = KnowledgeRepository(self._db_path)
        self._embeddings = EmbeddingRepository(self._db_path)
        self._analysis = AnalysisRepository(self._db_path)

    def search(self, query: VectorQuery, *, limit: int) -> StoreSearchResult:
        """取全部「已入库」资料的向量，算余弦，回前 `limit` 条候选。"""
        if limit <= 0 or not query.vector:
            return StoreSearchResult()

        query_array = np.asarray(query.vector, dtype=np.float64)
        query_norm = float(np.linalg.norm(query_array))
        if not math.isfinite(query_norm) or query_norm == 0.0:
            raise RetrievalStoreError("查询向量为空或数值异常，无法计算相似度")

        scored: list[RetrievalCandidate] = []
        skipped = 0
        for record in self._stored_records():
            document = record["document"]
            if document is None:
                continue
            try:
                vectors = self._embeddings.list_vectors(document["id"])
            except EmbeddingDimensionError:
                # 这份资料内部维度就乱了：跳过并计数，不让一份坏数据拖垮整次检索。
                skipped += 1
                continue

            chunks = {chunk["id"]: chunk for chunk in self._analysis.list_chunks(document["id"])}
            name = _display_name(record["source"])
            for row in vectors:
                if row["model_name"] != query.model_name or row["version"] != query.version:
                    skipped += 1
                    continue
                chunk = chunks.get(row["chunk_id"])
                if chunk is None:
                    continue
                similarity = _cosine(query_array, query_norm, row["vector"])
                if similarity is None:
                    skipped += 1
                    continue
                scored.append(
                    RetrievalCandidate(
                        chunk_id=chunk["id"],
                        document_id=document["id"],
                        source_id=record["source"]["id"],
                        name=name,
                        seq=chunk["seq"],
                        text=chunk["text"],
                        locator=chunk["locator"],
                        similarity=similarity,
                    )
                )

        scored.sort(key=lambda candidate: (-candidate.similarity, candidate.chunk_id))
        return StoreSearchResult(candidates=scored[:limit], skipped_incompatible=skipped)

    def stored_source_count(self) -> int:
        """「已入库」（`index_status = stored`）的资料份数，用于区分「空库」与「全降级」。"""
        return sum(1 for record in self._stored_records() if record["document"] is not None)

    def missing_index_count(self) -> int:
        """分块在、向量缺的资料份数（入库时嵌入失败的那一类）。"""
        missing = 0
        for record in self._stored_records(include_failed=True):
            document = record["document"]
            if document is None or record["source"]["index_status"] == INDEX_STATUS_STORED:
                continue
            if record["chunk_count"] > 0 and self._embeddings.count_vectors(document["id"]) == 0:
                missing += 1
        return missing

    def _stored_records(self, *, include_failed: bool = False) -> list[dict]:
        """逐页列出知识库资料；默认只取「已入库」，`include_failed` 时含索引失败的。"""
        records: list[dict] = []
        offset = 0
        page_size = 100
        while True:
            items, total = self._knowledge.list_sources(limit=page_size, offset=offset)
            records.extend(items)
            offset += len(items)
            if not items or offset >= total:
                break
        if include_failed:
            return [record for record in records if record["chunk_count"] > 0]
        return [
            record
            for record in records
            if record["source"]["index_status"] == INDEX_STATUS_STORED
        ]


def _cosine(
    query_array: np.ndarray, query_norm: float, vector: list[float]
) -> float | None:
    """余弦相似度；维度不同或数值异常返回 `None`（由调用方计入「跳过」）。"""
    if len(vector) != query_array.shape[0]:
        return None
    candidate = np.asarray(vector, dtype=np.float64)
    candidate_norm = float(np.linalg.norm(candidate))
    if not math.isfinite(candidate_norm) or candidate_norm == 0.0:
        return None
    return float(np.dot(query_array, candidate) / (query_norm * candidate_norm))


def _display_name(source: dict) -> str:
    """可读文件名：优先上传时的原始文件名，退回存储路径末段。"""
    meta = source.get("meta") or {}
    return str(meta.get("original_name") or Path(source["ref"]).name)


__all__ = ["RetrievalStoreError", "SqliteVectorStore"]
