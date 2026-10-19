"""总结 Word 交付记录（`summary_deliverables`）的数据访问。

由「总结 + 引用」按模板生成，与方案成品（`generations`）分开记账——总结没有
结构化方案，**绝不伪造 plan**。记录在产物落盘并通过完整性检查之后才写入。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso


class SummaryDeliverableRepository:
    """`summary_deliverables` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(
        self,
        source_id: int,
        *,
        task_id: int | None,
        file_path: str,
        template_used: str,
    ) -> dict:
        """记录一次总结 Word 交付（产物已落盘并通过完整性检查后才调用）。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO summary_deliverables
                    (source_id, task_id, file_path, template_used, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_id, task_id, file_path, template_used, utcnow_iso()),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM summary_deliverables WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get(self, deliverable_id: int) -> dict | None:
        """按 id 读取单条交付记录，不存在返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM summary_deliverables WHERE id = ?", (deliverable_id,)
            ).fetchone()
        return dict(row) if row is not None else None