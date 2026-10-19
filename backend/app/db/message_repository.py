"""对话消息（`messages`）数据访问。

规格 §4 的持久化是拷问轮次的**唯一**状态存储（LangGraph 不另立隐藏状态）。
一轮内的顺序由自增 id 保证：同轮里 assistant（问题集）先于该轮的 user（回答）。

assistant 消息的 `content` 为结构化 JSON，供前端渲染问题卡片：
    {"frontier": [{"title", "body", "recommended_answer"}, ...]}
user 消息的 `content` 为纯文本（用户输入或某题回答）。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso


class MessageRepository:
    """`messages` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def append(self, task_id: int, round_no: int, role: str, content: str) -> dict:
        """追加一条消息并返回落库行。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (task_id, round_no, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, round_no, role, content, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def list_for_task(self, task_id: int) -> list[dict]:
        """按落库顺序（id 升序）返回某任务的全部消息，用于复原对话与轮次。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE task_id = ? ORDER BY id ASC", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]