"""结构化方案（`plans`）数据访问。

规格 §4：方案内容（`content_md`）、状态（draft/confirmed）与确认时间（`confirmed_at`）；
工单 12 追加 `round_no`，记录方案由哪一轮问答产生（方案与轮次关联）。

纪律：一张任务的方案正文就地更新（工单 13 的**对话式修订**），历史版本落在
`plan_revisions`（见 `PlanRevisionRepository`），故 `get_current` 取 `id` 最大者；`id` 不变，
`update_content` 只改正文并把方案置回草稿（原确认不再覆盖新内容）。确认动作只作用于当前方案。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso


class PlanRepository:
    """`plans` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(self, task_id: int, content_md: str, *, round_no: int) -> dict:
        """新建方案草稿（status=draft，confirmed_at 为 NULL）。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO plans (task_id, round_no, content_md, status, confirmed_at)
                VALUES (?, ?, ?, 'draft', NULL)
                """,
                (task_id, round_no, content_md),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM plans WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get(self, plan_id: int) -> dict | None:
        """按 id 读取单份方案，不存在返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def get_current(self, task_id: int) -> dict | None:
        """返回某任务当前方案（id 最大者）；无方案返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM plans WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def count_for_task(self, task_id: int) -> int:
        """某任务的方案份数（删除影响范围用）。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM plans WHERE task_id = ?", (task_id,)
            ).fetchone()
        return int(row["total"])

    def confirm(self, plan_id: int) -> dict | None:
        """把方案置为已确认并记录 `confirmed_at`；不存在返回 None。

        幂等：已是 confirmed 的方案保留原确认时间，重复确认不漂移。
        """
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            connection.execute(
                """
                UPDATE plans
                SET status = 'confirmed',
                    confirmed_at = COALESCE(confirmed_at, ?)
                WHERE id = ?
                """,
                (now, plan_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def update_content(self, plan_id: int, content_md: str) -> dict | None:
        """用修订后的正文替换方案内容，并把方案置回**草稿**；不存在返回 None。

        置回草稿的理由（规格 User Story 9/10）：内容一变，用户此前的**方案确认**
        不再覆盖新内容，生成闸门必须重新关闭——未获批准的内容永不写出。
        """
        with connect(self._db_path) as connection:
            connection.execute(
                """
                UPDATE plans
                SET content_md = ?,
                    status = 'draft',
                    confirmed_at = NULL
                WHERE id = ?
                """,
                (content_md, plan_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return dict(row) if row is not None else None