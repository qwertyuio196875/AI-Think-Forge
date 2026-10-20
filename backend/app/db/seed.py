"""首次启动的默认模型配置播种。

按规格 §4 把档位当**角色标签**（turbo/plus/max），`model_name` 取当前有效 ID：
- 主流程：plus，默认档，`deepseek-flash`；
- 总结：turbo，`deepseek-flash`；
- 旗舰：max，`deepseek-v4-pro`。

默认服务商为 DeepSeek（2026-10-19 用户决策）。
**不得写入已停用的 `deepseek-chat` / `deepseek-reasoner` 或任何过期 ID。**

幂等：以 `settings.providers_seeded_v1` 标记，重复启动不重复插入；用户清空
provider 后也不回填（尊重用户删除）。
"""

from __future__ import annotations

from pathlib import Path

from app.db.database import connect

SEED_FLAG_KEY = "providers_seeded_v1"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 顺序即展示顺序；第一条为默认。
DEFAULT_PROVIDERS: tuple[dict[str, object], ...] = (
    {
        "name": "DeepSeek 主流程",
        "base_url": DEEPSEEK_BASE_URL,
        "model_name": "deepseek-flash",
        "is_default": 1,
        "kind": "plus",
    },
    {
        "name": "DeepSeek 总结",
        "base_url": DEEPSEEK_BASE_URL,
        "model_name": "deepseek-flash",
        "is_default": 0,
        "kind": "turbo",
    },
    {
        "name": "DeepSeek 旗舰",
        "base_url": DEEPSEEK_BASE_URL,
        "model_name": "deepseek-v4-pro",
        "is_default": 0,
        "kind": "max",
    },
)


def seed_default_providers(db_path: str | Path) -> None:
    """幂等播种默认 provider（首次启动调用一次）。"""
    with connect(db_path) as connection:
        seeded = connection.execute(
            "SELECT 1 FROM settings WHERE key = ?", (SEED_FLAG_KEY,)
        ).fetchone()
        if seeded is not None:
            return

        connection.executemany(
            """
            INSERT INTO providers (name, base_url, model_name, is_default, kind)
            VALUES (:name, :base_url, :model_name, :is_default, :kind)
            """,
            DEFAULT_PROVIDERS,
        )
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)", (SEED_FLAG_KEY, "1")
        )
        connection.commit()