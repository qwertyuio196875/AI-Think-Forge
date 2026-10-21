"""成品（`generations`）的数据访问。

规格 §4：`generations(id, task_id, plan_id, format, file_path, template_used, created_at)`。
术语（GLOSSARY）**成品**：方案确认后生成的最终文件（Word / 单文件 HTML，见 ADR-0003）。

- 记录在**产物落盘并通过完整性检查之后**才写入：不落库就不交付（规格 US 22）；
- `template_used` 记录本次**实际所用模板**（含任务级临时覆盖），全局默认不改（规格 US 20）。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso

# 成品来源（`generations.source`）：正文成品 vs 大纲导出。
# 规格 §4「新增一列记录某次生成是否来自填充」；术语表把两者明确区分开，
# 因此它们在成品记录里必须是两个不同的值，不能靠文件名猜。
SOURCE_OUTLINE = "outline"
SOURCE_BODY = "body"


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
        source: str = SOURCE_OUTLINE,
    ) -> dict:
        """记录一次成品生成（产物已落盘并通过完整性检查后才调用）。

        `source` 区分「正文成品」（body，来自填充的章节正文）与「大纲导出」
        （outline，直接渲染方案正文）。缺省 outline：既有调用点行为不变。
        """
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO generations
                    (task_id, plan_id, format, file_path, template_used, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    plan_id,
                    format,
                    file_path,
                    template_used,
                    source,
                    utcnow_iso(),
                ),
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

    def delete_body_generations(self, task_id: int, *, keep_id: int | None = None) -> list[dict]:
        """删掉某任务全部**正文成品**记录（可保留一条），返回被删的行供清理文件。

        为什么只在重写时用（工单 14）：正文成品是「整篇正文的快照」，同一任务同时
        留多份会让用户分不清哪份是最新的。重写某一章后，旧的那份正文成品已经被新
        拼装的那份取代——它不是历史版本，是过期快照。

        `keep_id` 是**必须保留**的那一条（刚拼好的新成品）。调用方先拼新的、再清旧的，
        所以这里必须能排除新记录，否则会把刚写好的成品一起删掉。

        **不动大纲导出**（`source='outline'`）：那是另一条产物、另一种用途，
        用户可能确实要留着做对照。
        """
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM generations WHERE task_id = ? AND source = ?",
                (task_id, SOURCE_BODY),
            ).fetchall()
            stale = [
                dict(row) for row in rows if keep_id is None or int(row["id"]) != keep_id
            ]
            for row in stale:
                connection.execute("DELETE FROM generations WHERE id = ?", (row["id"],))
            if stale:
                connection.commit()
        return stale

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