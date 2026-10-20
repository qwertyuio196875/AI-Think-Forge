"""模型配置（provider）数据访问。

`providers` 表只存非敏感字段：服务商名、Base URL、模型名、是否默认、档位角色标签。
密钥不经此处——由 `app.providers.key_store` 写入系统凭据管理器。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect

# 允许被更新的列（白名单，杜绝拼接入参导致的越权列写入）。
_UPDATABLE_COLUMNS = ("name", "base_url", "model_name", "kind")


class ProviderRepository:
    """`providers` 表的读写入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def list(self) -> list[dict]:
        """按 id 升序返回全部 provider。"""
        with connect(self._db_path) as connection:
            rows = connection.execute("SELECT * FROM providers ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        """provider 总数。"""
        with connect(self._db_path) as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM providers").fetchone()
        return int(row["total"])

    def get(self, provider_id: int) -> dict | None:
        """按 id 读取单条，不存在返回 None。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?", (provider_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def get_by_id(self, provider_id: int) -> dict | None:
        """按 id 读取单条（任务级模型覆盖解析用）；不存在返回 None。"""
        return self.get(provider_id)

    def get_by_name(self, name: str) -> dict | None:
        """按 name 读取单条（name 唯一）。"""
        with connect(self._db_path) as connection:
            row = connection.execute("SELECT * FROM providers WHERE name = ?", (name,)).fetchone()
        return dict(row) if row is not None else None

    def create(
        self,
        name: str,
        base_url: str,
        model_name: str,
        kind: str | None = None,
        *,
        is_default: bool = False,
    ) -> dict:
        """新建 provider；name 冲突时抛出 sqlite3.IntegrityError，由 API 层转为 409。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO providers (name, base_url, model_name, is_default, kind)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, base_url, model_name, int(is_default), kind),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def update(self, provider_id: int, fields: dict) -> dict | None:
        """部分更新非敏感字段；无字段可更新时返回当前行；不存在返回 None。"""
        assignments = [column for column in _UPDATABLE_COLUMNS if column in fields]
        if not assignments:
            return self.get(provider_id)

        values = [fields[column] for column in assignments]
        set_clause = ", ".join(f"{column} = ?" for column in assignments)
        with connect(self._db_path) as connection:
            cursor = connection.execute(
                f"UPDATE providers SET {set_clause} WHERE id = ?", (*values, provider_id)
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?", (provider_id,)
            ).fetchone()
        return dict(row)

    def delete(self, provider_id: int) -> bool:
        """删除 provider，返回是否命中。"""
        with connect(self._db_path) as connection:
            cursor = connection.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
            connection.commit()
        return cursor.rowcount > 0

    def set_default(self, provider_id: int) -> dict | None:
        """把指定 provider 设为唯一默认；不存在返回 None。"""
        with connect(self._db_path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM providers WHERE id = ?", (provider_id,)
            ).fetchone()
            if exists is None:
                return None
            connection.execute(
                "UPDATE providers SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END",
                (provider_id,),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?", (provider_id,)
            ).fetchone()
        return dict(row)

    def get_default(self) -> dict | None:
        """读取当前默认 provider。"""
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM providers WHERE is_default = 1 ORDER BY id ASC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def get_by_kind(self, kind: str) -> dict | None:
        """按档位标签（turbo / plus / max）取 provider；同档位优先默认者。

        档位只是角色标签，同一档位理论上可有多条配置；这里取「默认优先、id 升序」
        的第一条，保证解析结果稳定可复现。
        """
        with connect(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM providers
                WHERE kind = ?
                ORDER BY is_default DESC, id ASC
                LIMIT 1
                """,
                (kind,),
            ).fetchone()
        return dict(row) if row is not None else None
