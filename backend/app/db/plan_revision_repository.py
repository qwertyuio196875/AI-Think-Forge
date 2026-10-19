"""方案版本记录（`plan_revisions`）数据访问。

工单 13：对话式修订每次落一条版本记录（修订前内容 / 修订后内容 / 修订时间 / 差异提示），
**旧版本不可丢**——当前正文仍以 `plans.content_md` 为准，历史全在本表。
差异提示以 JSON 文本存储，读出时反序列化，保证存储层不泄漏结构细节给上层以外的东西。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.database import connect, utcnow_iso


class PlanRevisionRepository:
    """`plan_revisions` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(
        self,
        plan_id: int,
        task_id: int,
        instruction: str,
        previous_content_md: str,
        content_md: str,
        change_summary: list[dict],
    ) -> dict:
        """追加一条修订记录并返回落库行（`change_summary` 反序列化为列表）。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO plan_revisions
                    (plan_id, task_id, instruction, previous_content_md,
                     content_md, change_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    task_id,
                    instruction,
                    previous_content_md,
                    content_md,
                    json.dumps(change_summary, ensure_ascii=False),
                    utcnow_iso(),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM plan_revisions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._decode(dict(row))

    def list_for_task(self, task_id: int) -> list[dict]:
        """按落库顺序返回某任务的全部修订记录（旧版本可逐条回查）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM plan_revisions WHERE task_id = ? ORDER BY id ASC", (task_id,)
            ).fetchall()
        return [self._decode(dict(row)) for row in rows]

    @staticmethod
    def _decode(record: dict) -> dict:
        """把 `change_summary` 从 JSON 文本还原为结构。"""
        record["change_summary"] = json.loads(record["change_summary"])
        return record