"""任务（Task）数据访问。

以字典形式在存储层与应用层之间传递记录，避免把 sqlite3.Row 泄漏到 API 层。
每次操作使用独立连接，天然适配 FastAPI 线程池中的同步处理。

TB-10 追加历史查询与任务状态机（术语「任务」：状态、对话、方案、成品持久保存，可中断后继续）：
- 历史列表按分类 / 状态过滤、按 id 倒序（最近任务在前）分页，并带元信息行所需的对话条数与轮次数；
- 导航徽标用的分计数（创作 / 分析 / 全部，均排除已删除任务）；
- 状态迁移：已完成 / 重新打开 / **软删除**（只置状态并留 `deleted_at`，不物理清库）。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso

# 种子输入（用户最初的一句话 / 一段描述）记为第 0 轮，见 `app.grilling.service`。
# 历史列表的「轮次数」只数真正的拷问轮次，故从第 1 轮起算。
FIRST_ROUND_NO = 1

# 状态机里允许「用户显式迁移」的两态；deleted 只能经删除入口达成（软删除）。
SETTABLE_STATUSES = ("in_progress", "completed")


class TaskRepository:
    """`tasks` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create(
        self, kind: str, title: str | None, provider_id: int | None = None
    ) -> dict:
        """新建任务，初始状态 in_progress；可带任务级模型覆盖。"""
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (kind, title, provider_id, status, created_at, updated_at)
                VALUES (?, ?, ?, 'in_progress', ?, ?)
                """,
                (kind, title, provider_id, now, now),
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

    def list_history(
        self,
        kind: str | None = None,
        status: str | None = None,
        *,
        limit: int,
        offset: int,
    ) -> list[dict]:
        """历史列表：默认排除已删除任务，按 id 倒序（最近任务在前）分页。

        每条附带元信息行所需的对话条数与轮次数（单条聚合查询，避免逐条再查）。
        `status='deleted'` 显式传入时才返回已删除任务（供留痕 / 审计查看）。
        """
        conditions: list[str] = []
        parameters: list[str | int] = []
        if kind is not None:
            conditions.append("t.kind = ?")
            parameters.append(kind)
        if status is not None:
            conditions.append("t.status = ?")
            parameters.append(status)
        else:
            conditions.append("t.status != 'deleted'")

        query = f"""
            SELECT t.id, t.kind, t.title, t.status, t.created_at, t.updated_at,
                   (SELECT s.id FROM sources s
                     WHERE s.task_id = t.id ORDER BY s.id DESC LIMIT 1)
                       AS source_id,
                   (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id)
                       AS dialogue_messages,
                   (SELECT COUNT(DISTINCT m.round_no) FROM messages m
                     WHERE m.task_id = t.id AND m.round_no >= {FIRST_ROUND_NO})
                       AS rounds
            FROM tasks t
            WHERE {" AND ".join(conditions)}
            ORDER BY t.id DESC
            LIMIT ? OFFSET ?
        """
        parameters.extend([limit, offset])

        with connect(self._db_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def count_history(self, kind: str | None = None, status: str | None = None) -> int:
        """历史列表在同样过滤条件下的总数（分页用；默认排除已删除任务）。"""
        conditions: list[str] = []
        parameters: list[str] = []
        if kind is not None:
            conditions.append("kind = ?")
            parameters.append(kind)
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)
        else:
            conditions.append("status != 'deleted'")

        query = "SELECT COUNT(*) AS total FROM tasks WHERE " + " AND ".join(conditions)
        with connect(self._db_path) as connection:
            row = connection.execute(query, parameters).fetchone()
        return int(row["total"])

    def counts_by_kind(self) -> dict[str, int]:
        """导航徽标用的分计数：全部 / 创作 / 分析（均排除已删除任务）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT kind, COUNT(*) AS total FROM tasks
                WHERE status != 'deleted'
                GROUP BY kind
                """
            ).fetchall()
        counts = {"all": 0, "creation": 0, "analysis": 0}
        for row in rows:
            counts[row["kind"]] = int(row["total"])
            counts["all"] += int(row["total"])
        return counts

    def set_status(self, task_id: int, status: str) -> dict | None:
        """迁移任务状态（in_progress ↔ completed）；不存在返回 None。

        非法取值直接报错而非静默落库；`deleted` 不在此入口（只能经软删除达成）。
        completed_at 不单列字段：状态迁移同时刷新 `updated_at`，即「何时完成」。
        """
        if status not in SETTABLE_STATUSES:
            raise ValueError(f"不可迁入的任务状态：{status}")

        with connect(self._db_path) as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, utcnow_iso(), task_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def set_provider_id(self, task_id: int, provider_id: int | None) -> dict | None:
        """设置 / 清除任务级模型覆盖；不存在返回 None。

        `provider_id=None` 表示回到默认 provider（不删任务、不改其它字段）。
        """
        with connect(self._db_path) as connection:
            connection.execute(
                "UPDATE tasks SET provider_id = ?, updated_at = ? WHERE id = ?",
                (provider_id, utcnow_iso(), task_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_deleted(self, task_id: int) -> dict | None:
        """**软删除**：置状态 deleted 并留 `deleted_at`；不存在返回 None。

        不物理清库——对话 / 方案 / 待确认事项 / 版本记录照旧留存（规格 US 27）。
        幂等：已是 deleted 的任务保留原删除时间，重复删除不漂移。
        """
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'deleted',
                    deleted_at = COALESCE(deleted_at, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, task_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row is not None else None