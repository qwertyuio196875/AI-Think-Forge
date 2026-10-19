"""成品（`generations`）的数据访问——**弱依赖** TB-5 / TB-6。

术语（GLOSSARY）**成品**：方案确认后生成的最终文件（Word / 单文件 HTML）。成品生成管线
由 TB-5 / TB-6 落地，本单只需要「删除影响范围」里的**成品文件数**，故本模块只做计数，
不建表、不写入、不假设表结构细节。

表尚未落地（生成管线未实现）时如实返回 0——不伪造影响范围。
表结构以「有 `task_id` 列」为唯一前提：列缺失或表缺失一律计 0，避免把下游的形态变更
变成上游的报错。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect


class GenerationRepository:
    """`generations` 表的只读计数入口（表不存在时计 0）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def count_deliverable_files(self, task_id: int) -> int:
        """某任务当前的成品文件数；表 / 列尚未落地时返回 0。"""
        if not self._has_task_column():
            return 0

        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM generations WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return int(row["total"])

    def _has_task_column(self) -> bool:
        """成品表是否已落地且带 `task_id`（生成管线归 TB-5/TB-6）。"""
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