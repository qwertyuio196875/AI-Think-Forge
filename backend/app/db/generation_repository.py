"""成品（`generations`）的数据访问。

规格 §4：`generations(id, task_id, plan_id, format, file_path, template_used, created_at)`。
术语（GLOSSARY）**成品**：方案确认后生成的最终文件（Word / 单文件 HTML，见 ADR-0003）。

- 记录在**产物落盘并通过完整性检查之后**才写入：不落库就不交付（规格 US 22）；
- `template_used` 记录本次**实际所用模板**（含任务级临时覆盖），全局默认不改（规格 US 20）。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso


class GenerationRepository:
    """`generations` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(
        self,
        task_id: int,
        plan_id: int,
        format: str,
        file_path: str,
        template_used: str,
    ) -> dict:
        """记录一次成品生成（产物已落盘并通过完整性检查后才调用）。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO generations
                    (task_id, plan_id, format, file_path, template_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, plan_id, format, file_path, template_used, utcnow_iso()),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM generations WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get(self, generation_id: int) -> dict | None:
        """按 id 读取单条成品记录，不存在返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE id = ?", (generation_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_task(self, task_id: int) -> list[dict]:
        """按生成顺序返回某任务的全部成品记录（供成品列表渲染）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM generations WHERE task_id = ? ORDER BY id ASC", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def count_deliverable_files(self, task_id: int) -> int:
        """某任务当前的成品文件数（删除影响范围用）。

        表 / 列尚未落地时返回 0：本库由 TB-10 以「弱依赖」方式读取，容错口径不变
        （库是老版本建的无表情况不应变成上游报错）。
        """
        if not self._has_task_column():
            return 0

        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM generations WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return int(row["total"])

    def _has_task_column(self) -> bool:
        """成品表是否已落地且带 `task_id`。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'generations'"
            ).fetchone()
            if row is None:
                return False
            columns = {
                column["name"]
                for column in connection.execute("PRAGMA table_info(generations)").fetchall()
            }
        return "task_id" in columns