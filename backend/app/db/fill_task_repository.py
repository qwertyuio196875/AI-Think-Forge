"""填充任务（`fill_tasks`）数据访问（工单 9 / ADR-0006）。

一个任务可以先后有多次填充尝试（中断后重来、失败后重试），故记录是**追加**的：
`start` 每次插一行，读进度时取最新一行。章节正文不在这里——它属于 `plan_sections`，
本章节表才是正文的唯一真源，填充任务表只记这次尝试的整体进度。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso

# 「仍在跑」的状态集合：同一任务同时只允许一次进行中的填充（逐章串行写入的前提）。
ACTIVE_STATUSES = ("running",)


class FillTaskRepository:
    """`fill_tasks` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def start(
        self, *, task_id: int, plan_id: int, target_length: int, completed_sections: int = 0
    ) -> dict:
        """登记一次新的填充尝试（状态「进行中」、无错误信息），返回这一行。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO fill_tasks (
                    task_id, plan_id, target_length, completed_sections,
                    status, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'running', NULL, ?, ?)
                """,
                (task_id, plan_id, target_length, completed_sections, now, now),
            )
            connection.commit()
            # 同一条连接里回读，省一次开库；与 plans 的 create 写法一致。
            row = connection.execute(
                "SELECT * FROM fill_tasks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get(self, fill_id: int) -> dict | None:
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM fill_tasks WHERE id = ?", (fill_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def latest_for_task(self, task_id: int) -> dict | None:
        """某任务最近一次填充尝试；从未填充过返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM fill_tasks WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def active_for_task(self, task_id: int) -> dict | None:
        """某任务进行中的填充尝试；没有则 None。

        为什么要拦重复启动：填充是逐章串行写 `plan_sections` 的，两次并发填充会互相覆盖
        同一章的正文，还会各自把「已完成章节数」算成不同的值。
        """
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with connect(self._db_path) as connection:
            row = connection.execute(
                f"SELECT * FROM fill_tasks WHERE task_id = ? AND status IN ({placeholders})"
                " ORDER BY id DESC LIMIT 1",
                (task_id, *ACTIVE_STATUSES),
            ).fetchone()
        return dict(row) if row is not None else None
