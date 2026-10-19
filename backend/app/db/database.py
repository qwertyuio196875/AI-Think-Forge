"""SQLite 连接管理与建表。

TB-0 只落地 `tasks` 表最小集；资料登记 / 文本分块 / 嵌入版本等字段由
后续工单（含 v1.1 RAG 预留）追加，此处冻结最小可用结构。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

# 建表幂等：应用启动时执行，重复运行不改变已有表。
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL CHECK (kind IN ('creation', 'analysis')),
    title      TEXT,
    status     TEXT NOT NULL DEFAULT 'in_progress'
               CHECK (status IN ('in_progress', 'completed', 'deleted')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utcnow_iso() -> str:
    """当前时间的 ISO8601 字符串（UTC，含时区偏移）。"""
    return datetime.now(UTC).isoformat()


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """打开到指定 SQLite 文件的连接，返回 Row 以支持按列名取值。"""
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path) -> None:
    """幂等建表；父目录不存在时创建（data/ 运行时目录）。"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        connection.commit()
