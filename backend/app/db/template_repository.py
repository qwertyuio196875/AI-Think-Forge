"""模板登记（`templates`）的数据访问。

工单 14：模板登记需记录**名称、格式、是否默认**。术语（GLOSSARY）**模板**：样式文件；
系统只管理与应用，从不联网搜模板。术语「默认模板 / 临时覆盖」：全局默认模板 + 任务级
临时选用；**临时选择不改变全局默认**——故本表只承载全局默认，临时覆盖只落
`generations.template_used`。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect, utcnow_iso


class TemplateRepository:
    """`templates` 表的读写入口（全局默认模板的唯一真源）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def register(self, name: str, format: str, *, is_default: bool = False) -> dict:
        """登记一个模板；同名重复登记只刷新格式与默认标记（幂等）。

        `is_default=True` 时把同格式的其它模板取消默认——每个格式至多一个全局默认。
        """
        now = utcnow_iso()
        with connect(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO templates (name, format, is_default, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET format = excluded.format,
                                                is_default = excluded.is_default
                """,
                (name, format, 1 if is_default else 0, now),
            )
            if is_default:
                connection.execute(
                    """
                    UPDATE templates SET is_default = 0
                    WHERE format = ? AND name != ?
                    """,
                    (format, name),
                )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM templates WHERE name = ?", (name,)
            ).fetchone()
        return dict(row)

    def get(self, name: str) -> dict | None:
        """按名称读取登记记录，未登记返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM templates WHERE name = ?", (name,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_all(self) -> list[dict]:
        """全部登记记录（按 id 升序）。"""
        with connect(self._db_path) as connection:
            rows = connection.execute("SELECT * FROM templates ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]

    def get_default(self, format: str) -> dict | None:
        """某格式的**全局默认模板**登记记录；未设置返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM templates
                WHERE format = ? AND is_default = 1
                ORDER BY id DESC LIMIT 1
                """,
                (format,),
            ).fetchone()
        return dict(row) if row is not None else None

    def clear_default(self, format: str) -> None:
        """取消某格式的全局默认（内置默认模板回落到兜底位置）。"""
        with connect(self._db_path) as connection:
            connection.execute(
                "UPDATE templates SET is_default = 0 WHERE format = ?", (format,)
            )
            connection.commit()