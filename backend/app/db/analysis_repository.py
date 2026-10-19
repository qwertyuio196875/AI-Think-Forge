"""资料分析的数据访问：来源 / 文档 / 分块 / 总结（嵌入表按 ADR-0002 预留不填）。

表结构见 `app.db.database`。所有 JSON 字段以字符串落库，读出时由调用方解析；
这样 SQLite 不依赖 JSON1 扩展，行为在各平台一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.database import connect, utcnow_iso


class AnalysisRepository:
    """`sources` / `documents` / `document_chunks` / `summaries` 的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    # --- 来源 ---------------------------------------------------------------

    def create_source(
        self,
        kind: str,
        ref: str,
        *,
        meta: dict[str, Any] | None = None,
        task_id: int | None = None,
    ) -> dict:
        """登记来源；`meta` 序列化为 `meta_json`。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO sources (kind, ref, meta_json, task_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kind, ref, json.dumps(meta or {}, ensure_ascii=False), task_id, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _decode_source(dict(row))

    def get_source(self, source_id: int) -> dict | None:
        """按 id 读取来源，不存在返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return _decode_source(dict(row)) if row is not None else None

    def list_sources(self, *, limit: int, offset: int) -> tuple[list[dict], int]:
        """来源列表：按 `sources.id DESC` 分页，并带最新文档 / 是否有总结。

        返回 `(items, total)`；每项含 `source` / `document`（可为 None）/
        `has_summary` / `summary_id` / `summary_created_at`。
        """
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM sources ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total_row = connection.execute(
                "SELECT COUNT(*) AS total FROM sources"
            ).fetchone()

        items: list[dict] = []
        for row in rows:
            source = _decode_source(dict(row))
            document = self.get_document_for_source(source["id"])
            summary = self.get_summary_for_source(source["id"])
            items.append(
                {
                    "source": source,
                    "document": document,
                    "has_summary": summary is not None,
                    "summary_id": summary["id"] if summary is not None else None,
                    "summary_created_at": (
                        summary["created_at"] if summary is not None else None
                    ),
                }
            )
        return items, int(total_row["total"])

    # --- 文档 ---------------------------------------------------------------

    def create_document(
        self,
        source_id: int,
        path: str,
        *,
        parse_status: str = "pending",
        parse_message: str | None = None,
        heading_source: str | None = None,
        parser: str | None = None,
        encoding: str | None = None,
        headings: int = 0,
        images: int = 0,
        unrecognized: dict | None = None,
        unrecognized_parts: list[dict] | None = None,
    ) -> dict:
        """登记文档；解析结果（含解析器标识与未识别契约）一并落库。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents (
                    source_id, path, parse_status, parse_message, heading_source,
                    parser, encoding, headings, images, unrecognized_json,
                    unrecognized_parts_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    path,
                    parse_status,
                    parse_message,
                    heading_source,
                    parser,
                    encoding,
                    headings,
                    images,
                    _dump(unrecognized),
                    json.dumps(unrecognized_parts or [], ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _decode_document(dict(row))

    def update_document(
        self,
        document_id: int,
        *,
        parse_status: str | None = None,
        parse_message: str | None = None,
        heading_source: str | None = None,
        parser: str | None = None,
        encoding: str | None = None,
        headings: int | None = None,
        images: int | None = None,
        unrecognized: dict | None = None,
        unrecognized_parts: list[dict] | None = None,
    ) -> dict | None:
        """部分更新文档解析结果；只更新显式传入的字段。"""
        fields: dict[str, Any] = {}
        if parse_status is not None:
            fields["parse_status"] = parse_status
        if parse_message is not None:
            fields["parse_message"] = parse_message
        if heading_source is not None:
            fields["heading_source"] = heading_source
        if parser is not None:
            fields["parser"] = parser
        if encoding is not None:
            fields["encoding"] = encoding
        if headings is not None:
            fields["headings"] = headings
        if images is not None:
            fields["images"] = images
        if unrecognized is not None:
            fields["unrecognized_json"] = _dump(unrecognized)
        if unrecognized_parts is not None:
            fields["unrecognized_parts_json"] = json.dumps(
                unrecognized_parts, ensure_ascii=False
            )

        if not fields:
            return self.get_document(document_id)

        assignments = ", ".join(f"{column} = ?" for column in fields)
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?",
                (*fields.values(), document_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _decode_document(dict(row))

    def get_document(self, document_id: int) -> dict | None:
        """按 id 读取文档。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _decode_document(dict(row)) if row is not None else None

    def get_document_for_source(self, source_id: int) -> dict | None:
        """取某来源最新的一份文档。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE source_id = ? ORDER BY id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        return _decode_document(dict(row)) if row is not None else None

    # --- 分块 ---------------------------------------------------------------

    def add_chunks(self, document_id: int, chunks: list[dict]) -> int:
        """批量写入分块（单事务）；返回写入条数。"""
        if not chunks:
            return 0
        rows = [
            (
                document_id,
                chunk["seq"],
                chunk["text"],
                json.dumps(chunk.get("locator") or {}, ensure_ascii=False),
            )
            for chunk in chunks
        ]
        with connect(self._db_path) as connection:
            connection.executemany(
                """
                INSERT INTO document_chunks (document_id, seq, text, locator_json)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
        return len(rows)

    def list_chunks(self, document_id: int) -> list[dict]:
        """按 seq 升序返回某文档的全部分块。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM document_chunks WHERE document_id = ? ORDER BY seq ASC",
                (document_id,),
            ).fetchall()
        return [_decode_chunk(dict(row)) for row in rows]

    def count_chunks(self, document_id: int) -> int:
        """某文档的分块数。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM document_chunks WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return int(row["total"])

    # --- 总结 ---------------------------------------------------------------

    def create_summary(
        self,
        source_id: int,
        text: str,
        *,
        task_id: int | None = None,
        citations: list[dict] | None = None,
        chunk_count: int = 0,
        truncated: bool = False,
        provider_kind: str | None = None,
        provider_used: str | None = None,
        model_used: str | None = None,
        provider_fallback: bool = False,
        provider_note: str | None = None,
    ) -> dict:
        """保存总结（含引用与实际所用档位证据）。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO summaries (
                    source_id, task_id, text, citations_json, chunk_count, truncated,
                    provider_kind, provider_used, model_used, provider_fallback,
                    provider_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    task_id,
                    text,
                    json.dumps(citations or [], ensure_ascii=False),
                    chunk_count,
                    int(truncated),
                    provider_kind,
                    provider_used,
                    model_used,
                    int(provider_fallback),
                    provider_note,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM summaries WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _decode_summary(dict(row))

    def get_summary_for_source(self, source_id: int) -> dict | None:
        """取某来源最新的一份总结（重复分析时保留历史，读最新）。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM summaries WHERE source_id = ? ORDER BY id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        return _decode_summary(dict(row)) if row is not None else None


def _dump(value: dict | None) -> str | None:
    """JSON 序列化（None 保持 NULL，表示「没有这一项」）。"""
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _loads(value: str | None, default):
    """JSON 反序列化；空值回退默认，避免历史脏数据让读取整体失败。"""
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _decode_source(record: dict) -> dict:
    record["meta"] = _loads(record.pop("meta_json", None), {})
    return record


def _decode_document(record: dict) -> dict:
    record["unrecognized"] = _loads(record.pop("unrecognized_json", None), None)
    record["unrecognized_parts"] = _loads(
        record.pop("unrecognized_parts_json", None), []
    )
    return record


def _decode_chunk(record: dict) -> dict:
    record["locator"] = _loads(record.pop("locator_json", None), {})
    return record


def _decode_summary(record: dict) -> dict:
    record["citations"] = _loads(record.pop("citations_json", None), [])
    record["truncated"] = bool(record.get("truncated"))
    record["provider_fallback"] = bool(record.get("provider_fallback"))
    return record
