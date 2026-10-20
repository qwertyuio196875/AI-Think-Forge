"""知识库资料的数据访问（工单 19；ADR-0005）。

知识库不新建表族：资料仍是 `sources`，以 **`task_id IS NULL`** 表示「不属于任何
任务」。分块复用 `document_chunks`（与资料分析同一套切分参数），因此这里只补
「知识库视角」的查询与删除，通用写入仍走 `AnalysisRepository`，避免两套 SQL 漂移。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.analysis_repository import AnalysisRepository
from app.db.database import connect, utcnow_iso

# 索引状态取值域（API 同名字段，中文标签由路由层映射，见 models/knowledge.py）。
INDEX_STATUS_STORED = "stored"
INDEX_STATUS_INDEXING = "indexing"
INDEX_STATUS_FAILED = "failed"


class KnowledgeRepository:
    """知识库资料的读写入口（只认 `sources.task_id IS NULL` 的那部分）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        # 通用来源 / 文档 / 分块的写入与读取复用资料分析仓库，避免重复 SQL。
        self._analysis = AnalysisRepository(db_path)

    # --- 写入 ---------------------------------------------------------------

    def create_source(
        self,
        kind: str,
        ref: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> dict:
        """登记知识库资料：`task_id` 为空，初始状态「索引中」。"""
        return self._analysis.create_source(
            kind, ref, meta=meta, task_id=None, index_status=INDEX_STATUS_INDEXING
        )

    def set_index_status(
        self,
        source_id: int,
        status: str,
        *,
        message: str | None = None,
    ) -> dict | None:
        """更新索引状态；`stored` / `failed` 时记录完成时间。"""
        now = utcnow_iso()
        indexed_at = now if status in (INDEX_STATUS_STORED, INDEX_STATUS_FAILED) else None
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE sources
                   SET index_status = ?, index_message = ?, indexed_at = ?
                 WHERE id = ? AND task_id IS NULL
                """,
                (status, message, indexed_at, source_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self.get(source_id)

    def delete(self, source_id: int) -> int | None:
        """删除一份知识库资料及其全部派生数据（单事务，按依赖顺序删）。

        返回被连带清掉的分块数；来源不存在或已属于某个任务（`task_id` 非空）时返回
        `None`——知识库接口绝不删除资料分析的历史数据。
        """
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT id FROM sources WHERE id = ? AND task_id IS NULL",
                (source_id,),
            ).fetchone()
            if row is None:
                return None

            document_ids = [
                item["id"]
                for item in connection.execute(
                    "SELECT id FROM documents WHERE source_id = ?", (source_id,)
                ).fetchall()
            ]
            deleted_chunks = 0
            for document_id in document_ids:
                connection.execute(
                    """
                    DELETE FROM embeddings
                     WHERE chunk_id IN (
                        SELECT id FROM document_chunks WHERE document_id = ?
                     )
                    """,
                    (document_id,),
                )
                cursor = connection.execute(
                    "DELETE FROM document_chunks WHERE document_id = ?", (document_id,)
                )
                deleted_chunks += int(cursor.rowcount or 0)
            connection.execute("DELETE FROM summaries WHERE source_id = ?", (source_id,))
            connection.execute("DELETE FROM summary_deliverables WHERE source_id = ?", (source_id,))
            connection.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
            connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            connection.commit()
        return deleted_chunks

    def replace_chunks(self, document_id: int, chunks: list[dict]) -> int:
        """以新分块替换某文档的全部分块（单事务，连带丢弃旧嵌入）。

        重建索引时文档 id 保持不变（引用与嵌入都指向分块，重建必然是整份重切）；
        旧嵌入随旧分块一并删除，避免向量与文本错位。
        """
        with connect(self._db_path) as connection:
            connection.execute(
                """
                DELETE FROM embeddings
                 WHERE chunk_id IN (
                    SELECT id FROM document_chunks WHERE document_id = ?
                 )
                """,
                (document_id,),
            )
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.commit()
        return self._analysis.add_chunks(document_id, chunks)

    # --- 读取 ---------------------------------------------------------------

    def get(self, source_id: int) -> dict | None:
        """按 id 读取一份知识库资料；属于任务的来源在这里视作不存在。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ? AND task_id IS NULL", (source_id,)
            ).fetchone()
        return _decode_source(dict(row)) if row is not None else None

    def get_record(self, source_id: int) -> dict:
        """读取一份资料及其最新文档与分块数（上传 / 重建后回显用）。"""
        source = self.get(source_id)
        if source is None:
            raise KeyError(source_id)
        document = self._analysis.get_document_for_source(source_id)
        return {
            "source": source,
            "document": document,
            "chunk_count": (
                self._analysis.count_chunks(document["id"]) if document is not None else 0
            ),
        }

    def list_sources(self, *, limit: int, offset: int) -> tuple[list[dict], int]:
        """知识库清单：按 `sources.id DESC` 分页，带最新文档与分块数。

        返回 `(items, total)`；每项含 `source` / `document`（可为 None）/ `chunk_count`。
        未解析出文档的资料（解析直接失败）也会出现在清单里，只是 `document` 为 None，
        这正是「资料本身仍可看可读、失败状态明确可见」的落点。
        """
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM sources WHERE task_id IS NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total_row = connection.execute(
                "SELECT COUNT(*) AS total FROM sources WHERE task_id IS NULL"
            ).fetchone()

        items: list[dict] = []
        for row in rows:
            source = _decode_source(dict(row))
            document = self._analysis.get_document_for_source(source["id"])
            items.append(
                {
                    "source": source,
                    "document": document,
                    "chunk_count": (
                        self._analysis.count_chunks(document["id"]) if document is not None else 0
                    ),
                }
            )
        return items, int(total_row["total"])

    def list_reindex_targets(self) -> list[int]:
        """全部知识库资料的 id（重建索引用，按 id 升序稳定）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT id FROM sources WHERE task_id IS NULL ORDER BY id ASC"
            ).fetchall()
        return [int(row["id"]) for row in rows]


def _decode_source(record: dict) -> dict:
    """`meta_json` → `meta`；坏数据退回空对象，别让一行脏数据拖垮整份清单。"""
    raw = record.pop("meta_json", None)
    try:
        record["meta"] = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        record["meta"] = {}
    return record
