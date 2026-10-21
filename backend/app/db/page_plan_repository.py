"""页面规划（`page_plans`）数据访问（工单 25 / ADR-0004）。

一份方案可以先后按不同页数规划，故记录是**追加**的：每次「按目标页数规划」插一行，
预览与单页到增删都读**某次规划的具体一行**（按 id 寻址），而不是「任务最新的那份」——
同一任务下用户可能同时瞄着 8 页和 16 页两版规划，用「最新」去读会串味。

`pages_json` 存的是纯 JSON 文本；落库/回读时由调用方负责 marshal/unmarshal（本模块只
做存取，不解释结构——页面结构归 `app.pageplan` 管，避免这里和规划模块双向依赖）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.database import connect, utcnow_iso


class PagePlanRepository:
    """`page_plans` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(
        self, *, task_id: int, plan_id: int, target_pages: int, pages: list[dict]
    ) -> dict:
        """落库一次页面规划，返回这一行。

        `pages` 是要序列化的页列表（封面 + 内容页）；调用方保证 len 与 target_pages 一致。
        """
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO page_plans (task_id, plan_id, target_pages, pages_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, plan_id, target_pages, json.dumps(pages, ensure_ascii=False), now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM page_plans WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get(self, page_plan_id: int) -> dict | None:
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM page_plans WHERE id = ?", (page_plan_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def latest_for_task(self, task_id: int) -> dict | None:
        """某任务最近一次页面规划；从未规划过返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM page_plans WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_task(self, task_id: int) -> list[dict]:
        """某任务的全部页面规划（含不同页数的多份），按 id 升序。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM page_plans WHERE task_id = ? ORDER BY id ASC", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]