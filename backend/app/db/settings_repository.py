"""应用设置项（`settings` 表）的读写入口。

值以文本存储；调用方负责解释（例如 HTML 演示的全局默认主题 id）。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect


class SettingsRepository:
    """`settings` 表的 key-value 读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def get(self, key: str, default: str | None = None) -> str | None:
        """读取设置值；不存在返回 `default`。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row is not None else default

    def set(self, key: str, value: str) -> None:
        """写入设置值（UPSERT，重复写入覆盖旧值）。"""
        with connect(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            connection.commit()