"""任务（Task）数据访问。

以字典形式在存储层与应用层之间传递记录，避免把 sqlite3.Row 泄漏到 API 层。
每次操作使用独立连接，天然适配 FastAPI 线程池中的同步处理。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso


class TaskRepository:
    """`tasks` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(self, kind: str, title: str | None) -> dict:
        """新建任务，初始状态 in_progress。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (kind, title, status, created_at, updated_at)
                VALUES (?, ?, 'in_progress', ?, ?)
                """,
                (kind, title, now, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def list(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        """按可选 kind / status 过滤，按创建顺序（id 升序）返回。"""
        conditions: list[str] = []
        parameters: list[str] = []
        if kind is not None:
            conditions.append("kind = ?")
            parameters.append(kind)
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)

        query = "SELECT * FROM tasks"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id ASC"

        with connect(self._db_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def get(self, task_id: int) -> dict | None:
        """按 id 读取单条任务，不存在返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row is not None else None
