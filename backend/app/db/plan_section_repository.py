"""成品章节（`plan_sections`）数据访问（工单 7 / ADR-0006）。

纪律（本模块的重点）：
- 对外寻址用「方案 + 序号」（`plan_id` + `seq`），**不用自增 id**：章节的一等身份是
  它在成品目录里的位置，跨修订搬序号时不能让调用方跟着换 id；
- 方案修订后重建整份清单：先按**标题**匹配旧行（保留已写正文与状态），匹配不上的旧行
  删除、新标题新建为「待写」——这是 ADR-0006 的明确规则，不做模糊匹配也不猜；
- 重建在**一个事务**里完成（删除 + 写入同进同退），绝不让外部看到半份目录。

本模块只做数据访问；切分本身复用 `app.grilling.plan_sections.parse_plan_sections`，
不在这里另写解析。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.db.database import connect, utcnow_iso


class PlanSectionRepository:
    """`plan_sections` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def list_for_plan(self, plan_id: int) -> list[dict]:
        """按序号升序读一份方案的全部章节；无章节返回空清单。"""
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM plan_sections WHERE plan_id = ? ORDER BY seq ASC",
                (plan_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace(self, task_id: int, plan_id: int, sections: Sequence[dict]) -> list[dict]:
        """按给定清单重建这份方案的章节表，返回重建后的行（按序号升序）。

        `sections` 每项含 `seq` / `title`，可含 `key_points` / `target_length`。
        旧行按**标题**与新清单匹配：匹配上的保留 `content_md` / `status` / `completed_at`，
        并把内容迁到新序号；匹配不上的旧行删除，新出现的标题按「待写」新建。

        为什么整表重建而不是逐行 diff：章节数极少（十来章），而「删除已消失的章」与
        「搬迁序号」用增量 SQL 表达反而更容易漏行；整表替换在一个事务里，外部永远看到
        完整的某一版目录。
        """
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            # 旧行在同一连接里读，避免「读旧行」与「整表替换」之间被别人插进一次写入。
            # 同名多行时只保留第一条：唯一键是「方案 + 序号」，标题不是键，避免二选一的歧义。
            keep: dict[str, dict] = {}
            for row in connection.execute(
                "SELECT * FROM plan_sections WHERE plan_id = ? ORDER BY seq ASC", (plan_id,)
            ).fetchall():
                keep.setdefault(str(row["title"]), dict(row))

            connection.execute("DELETE FROM plan_sections WHERE plan_id = ?", (plan_id,))
            for item in sections:
                matched = keep.get(str(item["title"]))
                if matched is None:
                    connection.execute(
                        """
                        INSERT INTO plan_sections (
                            task_id, plan_id, seq, title, key_points, target_length,
                            content_md, status, completed_at, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, '', 'pending', NULL, ?, ?)
                        """,
                        (
                            task_id,
                            plan_id,
                            item["seq"],
                            item["title"],
                            item.get("key_points", ""),
                            item.get("target_length"),
                            now,
                            now,
                        ),
                    )
                    continue

                # 匹配上了：正文与状态跟着标题走，目标字数用新方案的值（方案是字数真源）。
                connection.execute(
                    """
                    INSERT INTO plan_sections (
                        task_id, plan_id, seq, title, key_points, target_length,
                        content_md, status, completed_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        plan_id,
                        item["seq"],
                        item["title"],
                        item.get("key_points", ""),
                        item.get("target_length"),
                        matched["content_md"],
                        matched["status"],
                        matched["completed_at"],
                        matched["created_at"],
                        now,
                    ),
                )
            connection.commit()

        return self.list_for_plan(plan_id)
