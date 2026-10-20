"""向量数据访问（工单 20；ADR-0005）。

`embeddings` 表结构早已存在（外键指向 `document_chunks`），本模块是它的**唯一
写入点**，并把「写入格式固定、读取端校验维度」这两条规格要求落到实处：

- 写：`vector_json` 一律是紧凑的 JSON 浮点数组（`[0.1,-0.2,...]`），同一次写入
  的各向量必须同维，且每个 `chunk_id` 必须属于同一份文档；
- 读：`list_vectors` 会核对维度与 `model_name`，不一致直接抛
  `EmbeddingDimensionError`——**绝不把不同维度的向量当成可比较的相似度**。

「换模型 = 整份替换」也在这里保证：`replace_document_vectors` 在**同一事务**内
先删该文档的全部旧向量再插入新向量，因此重建索引不会出现新旧混存。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from app.db.database import connect, utcnow_iso
from app.providers.embedding_client import VECTOR_FORMAT_VERSION, EmbeddingDimensionError


class EmbeddingRepository:
    """某份文档的全部向量（按分块序号可回查）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def replace_document_vectors(
        self,
        document_id: int,
        vectors: Sequence[tuple[int, Sequence[float]]],
        *,
        model_name: str,
        version: str = VECTOR_FORMAT_VERSION,
    ) -> int:
        """整份替换某文档的向量（单事务），返回写入条数。

        `vectors` 是 `(chunk_id, 向量)` 序列；写入前统一校验：非空、同维、
        且每个分块都属于这份文档——不满足就抛 `EmbeddingDimensionError` /
        `ValueError`，让上层把资料标成「索引失败」，而不是留下半份向量。
        """
        if not vectors:
            return 0

        dimensions = {len(vector) for _, vector in vectors}
        if len(dimensions) != 1:
            raise EmbeddingDimensionError(
                f"同一份文档的向量维度不一致（出现 {sorted(dimensions)} 个维度），"
                "请确认只使用一个嵌入模型并重建索引"
            )
        chunk_ids = [chunk_id for chunk_id, _ in vectors]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("同一分块不能写入多条向量")

        now = utcnow_iso()
        with connect(self._db_path) as connection:
            owned = {
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM document_chunks WHERE document_id = ?", (document_id,)
                ).fetchall()
            }
            foreign = [chunk_id for chunk_id in chunk_ids if chunk_id not in owned]
            if foreign:
                raise ValueError(f"分块 {foreign[0]} 不属于文档 {document_id}")

            connection.execute(
                """
                DELETE FROM embeddings
                 WHERE chunk_id IN (
                    SELECT id FROM document_chunks WHERE document_id = ?
                 )
                """,
                (document_id,),
            )
            connection.executemany(
                """
                INSERT INTO embeddings (chunk_id, model_name, version, vector_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (chunk_id, model_name, version, dump_vector(vector), now)
                    for chunk_id, vector in vectors
                ],
            )
            connection.commit()
        return len(vectors)

    def list_vectors(self, document_id: int) -> list[dict]:
        """按分块 `seq` 升序读取某文档的向量，并校验维度与模型一致。

        返回 `[{"chunk_id", "seq", "model_name", "version", "vector"}, ...]`。
        任何一条维度与其余不同、或 `model_name` 与本批不同，都抛
        `EmbeddingDimensionError`：宁可报错让人重建索引，也不静默算出错误的相似度。
        """
        with connect(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT e.chunk_id      AS chunk_id,
                       c.seq           AS seq,
                       e.model_name    AS model_name,
                       e.version       AS version,
                       e.vector_json   AS vector_json
                  FROM embeddings e
                  JOIN document_chunks c ON c.id = e.chunk_id
                 WHERE c.document_id = ?
                 ORDER BY c.seq ASC
                """,
                (document_id,),
            ).fetchall()

        vectors: list[dict] = []
        for row in rows:
            record = dict(row)
            record["vector"] = load_vector(record.pop("vector_json"))
            vectors.append(record)

        if not vectors:
            return []

        dimensions = {len(record["vector"]) for record in vectors}
        if len(dimensions) != 1:
            raise EmbeddingDimensionError(
                f"文档 {document_id} 的向量维度不一致（出现 {sorted(dimensions)} 个维度），"
                "疑似换过嵌入模型；请重建索引"
            )
        models = {str(record["model_name"]) for record in vectors}
        if len(models) != 1:
            raise EmbeddingDimensionError(
                f"文档 {document_id} 的向量来自多个嵌入模型（{sorted(models)}），"
                "新旧向量混存；请重建索引"
            )
        return vectors

    def count_vectors(self, document_id: int) -> int:
        """某文档已写入的向量条数（与分块数对不上即视为索引不完整）。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                  FROM embeddings e
                  JOIN document_chunks c ON c.id = e.chunk_id
                 WHERE c.document_id = ?
                """,
                (document_id,),
            ).fetchone()
        return int(row["total"])


def dump_vector(vector: Sequence[float]) -> str:
    """把向量序列化成固定的紧凑 JSON 数组（写入格式的唯一真源）。"""
    return json.dumps([float(value) for value in vector], ensure_ascii=False, separators=(",", ":"))


def load_vector(raw: str | None) -> list[float]:
    """把 `vector_json` 读回浮点列表；坏数据明确报错，不返回空向量糊过去。"""
    if not raw:
        raise EmbeddingDimensionError("向量数据为空，无法参与相似度计算")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EmbeddingDimensionError("向量数据不是合法的 JSON，无法参与相似度计算") from exc
    if not isinstance(parsed, list) or not parsed:
        raise EmbeddingDimensionError("向量数据不是非空数组，无法参与相似度计算")
    try:
        return [float(value) for value in parsed]
    except (TypeError, ValueError) as exc:
        raise EmbeddingDimensionError("向量数据含非数值元素，无法参与相似度计算") from exc
