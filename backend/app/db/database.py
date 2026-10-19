"""SQLite 连接管理与建表。

TB-0 落地 `tasks` 表最小集；TB-1 追加 `providers`（模型配置非敏感字段）与
`settings`（应用设置项）；TB-2 追加 `messages`（对话轮次）；TB-3 追加 `plans`
（结构化方案，draft/confirmed）。密钥字段刻意不存在于任何表——凭据只进系统凭据管理器。
资料登记 / 文本分块 / 嵌入版本等字段由后续工单（含 v1.1 RAG 预留）追加。
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

-- 模型配置（服务商）非敏感字段。`kind` 仅为角色标签（turbo/plus/max，可空）。
-- 注意：本表不含任何密钥列；密钥只进 Windows 凭据管理器。
CREATE TABLE IF NOT EXISTS providers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    base_url   TEXT NOT NULL,
    model_name TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    kind       TEXT CHECK (kind IN ('turbo', 'plus', 'max'))
);

-- 应用设置项（key-value），如默认播种标记。
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT
);

-- 对话消息（规格 §4）：拷问轮次的提问与回答**同序落库**。
-- - round_no：种子输入为 0，第 N 轮为 N；
-- - role：user = 用户输入 / 回答；assistant = 系统产出的问题集（前沿）；system 预留；
-- - 顺序由自增 id 保证：同一轮内 assistant（问题集）先于该轮的 user（回答）。
-- - assistant 的 content 为结构化 JSON（见 MessageRepository 文档）。
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id),
    round_no   INTEGER NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('system', 'assistant', 'user')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_task_round ON messages (task_id, round_no, id);

-- 结构化方案（规格 §4）：拷问收敛后的阶段性产物，未经确认只是草稿。
-- - content_md：方案正文（Markdown；章节随任务类型裁剪，不要求所有任务同一结构）；
-- - status：draft（草稿）/ confirmed（用户显式确认，进入生成阶段的唯一闸门）；
-- - confirmed_at：确认时刻（未确认为 NULL），供下游（生成）判定放行；
-- - round_no：方案由哪一轮问答产生（工单 12 要求「方案与轮次关联」）。
CREATE TABLE IF NOT EXISTS plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL REFERENCES tasks(id),
    round_no     INTEGER NOT NULL,
    content_md   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft', 'confirmed')),
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_plans_task ON plans (task_id, id);
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
