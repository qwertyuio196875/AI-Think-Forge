"""待确认事项（`open_items`）数据访问。

规格 §4 + 术语「待确认事项」：尚未决定的关键信息清单（来源轮次、条目、状态）。
纪律：`open` 的条目**不得作为已定需求进入下游**——`has_unresolved` 就是给生成闸门用的判定。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso

# 用户处置待确认事项的两种终态：确认（承认其成为已定需求）/ 搁置（认定不需要）。
RESOLVABLE_STATUSES = ("confirmed", "dismissed")


class OpenItemRepository:
    """`open_items` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(self, task_id: int, round_no: int, text: str) -> dict:
        """新建一条待确认事项（status=open，resolved_at 为 NULL）。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO open_items (task_id, round_no, text, status, created_at, resolved_at)
                VALUES (?, ?, ?, 'open', ?, NULL)
                """,
                (task_id, round_no, text, utcnow_iso()),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM open_items WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get(self, item_id: int) -> dict | None:
        """按 id 读取单条待确认事项。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM open_items WHERE id = ?", (item_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_task(self, task_id: int) -> list[dict]:
        """按落库顺序返回某任务的全部待确认事项（含已处置的）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM open_items WHERE task_id = ? ORDER BY id ASC", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def open_texts(self, task_id: int) -> list[str]:
        """仅返回仍为 `open` 的条目内容（供提示词「未定」区块使用）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT text FROM open_items
                WHERE task_id = ? AND status = 'open'
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
        return [row["text"] for row in rows]

    def has_unresolved(self, task_id: int) -> bool:
        """是否还有未处置的待确认事项（生成闸门判定用）。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM open_items WHERE task_id = ? AND status = 'open' LIMIT 1",
                (task_id,),
            ).fetchone()
        return row is not None

    def count_for_task(self, task_id: int) -> int:
        """某任务的待确认事项条数（含已处置的；删除影响范围用）。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM open_items WHERE task_id = ?", (task_id,)
            ).fetchone()
        return int(row["total"])

    def resolve(self, item_id: int, status: str) -> dict | None:
        """处置一条待确认事项（confirmed / dismissed）并记录 `resolved_at`；不存在返回 None。

        幂等：重复处置保留原处置时间。
        """
        if status not in RESOLVABLE_STATUSES:
            raise ValueError(f"非法的处置状态：{status}")
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            connection.execute(
                """
                UPDATE open_items
                SET status = ?, resolved_at = COALESCE(resolved_at, ?)
                WHERE id = ?
                """,
                (status, now, item_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM open_items WHERE id = ?", (item_id,)
            ).fetchone()
        return dict(row) if row is not None else None