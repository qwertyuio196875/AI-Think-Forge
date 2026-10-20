"""SQLite 连接管理与建表。

TB-0 落地 `tasks` 表最小集；TB-1 追加 `providers`（模型配置非敏感字段）与
`settings`（应用设置项）；TB-2 追加 `messages`（对话轮次）；TB-3 追加 `plans`
（结构化方案，draft/confirmed）；TB-4 追加 `open_items`（待确认事项）与
`plan_revisions`（方案版本记录）；TB-10 给 `tasks` 补 `deleted_at`（删除留痕）与
历史查询索引；TB-5 追加 `generations`（成品记录，含本次实际所用模板）与 `templates`
（模板登记：名称 / 格式 / 是否默认）。密钥字段刻意不存在于任何表——凭据只进系统凭据管理器。
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
-- 任务（规格 §4 + 术语「任务」）。状态机：in_progress（进行中）/ completed（已完成）
-- / deleted（已删除）。删除是**软删除**（规格 US 27：一次误操作不毁掉本地数据）：
-- 只把状态置为 deleted 并记录 deleted_at 留痕，**不物理清库**，对话 / 方案 / 待确认事项照旧留存。
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('creation', 'analysis')),
    title       TEXT,
    -- 任务级模型覆盖（US23）：为空表示沿用默认 provider；删除 provider 不影响已建任务。
    provider_id INTEGER,
    status      TEXT NOT NULL DEFAULT 'in_progress'
                CHECK (status IN ('in_progress', 'completed', 'deleted')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT
);

-- 历史查询用索引：分类 / 状态过滤 + 按 id 倒序（最近任务在前）分页。
CREATE INDEX IF NOT EXISTS idx_tasks_kind_status_id ON tasks (kind, status, id);

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

-- 待确认事项（规格 §4 术语「待确认事项」；工单 13）：系统标记的、尚未决定的关键信息清单。
-- - round_no：来源轮次（该条目由哪一轮的「暂时跳过」产生），供前端回指；
-- - text：条目内容（跳过的前沿问题标题）；
-- - status：open（待确认）/ confirmed（用户确认其成为已定需求）/ dismissed（用户认定不需要）；
-- - resolved_at：用户处置时刻（未处置为 NULL）。
-- 纪律：**open 的条目不得作为已定需求进入下游**——既不得写进方案正文的「已确定」部分，
-- 也不得让生成闸门放行（未经确认的推测绝不直接变成成品，规格 US 9）。
CREATE TABLE IF NOT EXISTS open_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id),
    round_no    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'confirmed', 'dismissed')),
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_open_items_task ON open_items (task_id, id);

-- 方案版本记录（工单 13）：对话式修订留痕，**旧版本不可丢**。
-- 每条记录一次修订：触发修订的用户指令、修订前内容、修订后内容、修订时间与差异提示。
-- 当前方案正文仍以 `plans.content_md` 为准；本表保存全部历史版本供回查。
CREATE TABLE IF NOT EXISTS plan_revisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id             INTEGER NOT NULL REFERENCES plans(id),
    task_id             INTEGER NOT NULL REFERENCES tasks(id),
    instruction         TEXT NOT NULL,
    previous_content_md TEXT NOT NULL,
    content_md          TEXT NOT NULL,
    change_summary      TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plan_revisions_plan ON plan_revisions (plan_id, id);

-- 成品（规格 §4；工单 14）：方案确认后生成的最终文件（Word / 单文件 HTML，见 ADR-0003）。
-- - plan_id：由哪一份结构化方案生成（方案确认是进入生成阶段的唯一闸门）；
-- - format：成品格式（docx / html），与 ADR-0003 的首版双轨一致；
-- - file_path：产物落盘位置（绝对路径；文件访问限定 data/ 白名单）；
-- - template_used：**本次生成实际所用的模板**（规格 US 20「每次生成实际所用模板的记录」），
--   取模板目录下的相对路径（内置默认模板为 `_builtin/minimal-default.docx`）。任务级
--   **临时覆盖**只体现在本列，绝不改写全局默认（术语「默认模板 / 临时覆盖」）。
CREATE TABLE IF NOT EXISTS generations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES tasks(id),
    plan_id       INTEGER NOT NULL REFERENCES plans(id),
    format        TEXT NOT NULL CHECK (format IN ('docx', 'html')),
    file_path     TEXT NOT NULL,
    template_used TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generations_task ON generations (task_id, id);

-- 模板登记（工单 14「名称、格式、是否默认」）：模板 = 样式文件（GLOSSARY）。
-- 系统只管理与应用，从不联网搜模板。字段取最小集：
-- - name：模板文件名（相对 `templates/` 的 posix 相对路径，如 `corp.docx`）；
-- - format：模板格式；本单只接受 docx —— `.dotx` / `.dotm` / `.docm` 打不开
--   （python-docx 校验主部件内容类型，调研 A2 陷阱 1），登记入口即拒。
-- - is_default：是否该格式的**全局默认模板**（同格式至多一个，写入时互斥）。
-- **任务级临时覆盖不写本表**：它只影响单次生成的 `generations.template_used`，
-- 不改变全局默认（术语「临时选择不改变全局默认」）。
CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    format     TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL
);

-- 资料登记（规格 §4；工单 16）：一次资料分析的来源。
-- - kind：file（本地上传）/ url（TB-9；本单只落 file）；
-- - ref：文件类为 `data/` 下的相对路径（带唯一前缀），URL 类为原始地址；
-- - meta_json：原始文件名 / 大小 / 扩展名等非结构化元信息；
-- - task_id：该来源所属的资料分析任务（任务状态与历史列表复用既有 `tasks`）；
--   **为空即知识库资料**（工单 19 / ADR-0005：复用本表族，不建平行表）；
-- - index_status / index_message / indexed_at：知识库资料的索引状态
--   （stored 已入库 / indexing 索引中 / failed 索引失败）与失败原因。
--   分析管线的来源也带默认值，但知识库接口只读 `task_id IS NULL`，两边不串味。
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL CHECK (kind IN ('file', 'url')),
    ref           TEXT NOT NULL,
    meta_json     TEXT NOT NULL DEFAULT '{}',
    task_id       INTEGER REFERENCES tasks(id),
    index_status  TEXT NOT NULL DEFAULT 'stored'
                  CHECK (index_status IN ('stored', 'indexing', 'failed')),
    index_message TEXT,
    indexed_at    TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_task ON sources (task_id, id);

-- 文档（规格 §4；工单 16）：来源解析后的一份文档。
-- - path：文件类为 `data/` 下的相对路径（与 sources.ref 一致，便于白名单解析）；
--   URL 类（TB-9）为抓取重定向后的最终地址（不落盘，仅作文档的可回溯引用）；
--   `unrecognized_json` 的 locator 亦记录该最终地址；
-- - parse_status：pending / parsed / unrecognized / failed；
--   失败与「未识别」都如实落库，**绝不用空字符串冒充解析成功**；
-- - unrecognized_json / unrecognized_parts_json：未识别契约（一级输出字段）；
-- - parser：解析器标识（TB-8：pypdf / python-pptx / python-docx / plain-text），
--   让「这份内容出自哪个解析器」可回溯；
-- - heading_source：标题来源——DOCX 为内置样式（style）/ 启发式（heuristic）/ 无（none）；
--   PDF 无样式信息，只可能出现 heuristic / none；PPTX 取标题占位符，为 style / none。
CREATE TABLE IF NOT EXISTS documents (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id               INTEGER NOT NULL REFERENCES sources(id),
    path                    TEXT NOT NULL,
    parse_status            TEXT NOT NULL DEFAULT 'pending'
                            CHECK (parse_status IN ('pending', 'parsed', 'unrecognized', 'failed')),
    parse_message           TEXT,
    heading_source          TEXT,
    parser                  TEXT,
    encoding                TEXT,
    headings                INTEGER NOT NULL DEFAULT 0,
    images                  INTEGER NOT NULL DEFAULT 0,
    unrecognized_json       TEXT,
    unrecognized_parts_json TEXT NOT NULL DEFAULT '[]',
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_source ON documents (source_id, id);

-- 文本分块（规格 §4；工单 16 / 19）：分析管线与知识库共用的分块，含位置 locator。
-- 注意：ADR-0005 起分块**同时**是知识库检索的粒度（`embeddings.chunk_id` 指向本表），
-- 分块参数只有一套（`analysis/chunking.py`：1200 / 1800，按标题边界），不另造分块器。
CREATE TABLE IF NOT EXISTS document_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    seq          INTEGER NOT NULL,
    text         TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_document_chunks_seq ON document_chunks (document_id, seq);

-- 总结（规格 §4；工单 16）：资料分析的输出，含引用位置与实际所用档位。
-- - citations_json：来自哪些分块 / 位置（chunk_seq + locator + 摘录），供「总结与引用来源」；
-- - provider_kind / provider_used / model_used / provider_fallback：总结走 turbo 档的
--   实际证据；该档缺失时回退默认 provider 也如实记录（不静默）。
CREATE TABLE IF NOT EXISTS summaries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         INTEGER NOT NULL REFERENCES sources(id),
    task_id           INTEGER REFERENCES tasks(id),
    text              TEXT NOT NULL,
    citations_json    TEXT NOT NULL DEFAULT '[]',
    chunk_count       INTEGER NOT NULL DEFAULT 0,
    truncated         INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    provider_kind     TEXT,
    provider_used     TEXT,
    model_used        TEXT,
    provider_fallback INTEGER NOT NULL DEFAULT 0 CHECK (provider_fallback IN (0, 1)),
    provider_note     TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summaries_source ON summaries (source_id, id);

-- 嵌入（规格 §4 预留；ADR-0002）：v1 **不填充**，v1.1 检索层追加时再加索引与写入。
-- 保留本表是为了让 v1.1 的跨文档检索不重构既有资料 / 分块 / 总结路径。
CREATE TABLE IF NOT EXISTS embeddings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id       INTEGER NOT NULL REFERENCES document_chunks(id),
    model_name     TEXT,
    version        TEXT,
    vector_json    TEXT,
    created_at     TEXT
);

-- 总结的 Word 交付记录（工单 16 / US16）：由「总结 + 引用」按模板生成，
-- 与方案成品（generations）分开记账——总结没有结构化方案，绝不伪造 plan。
-- - task_id：来源所属的资料分析任务（可空，兼容早期无任务来源）；
-- - template_used：本次实际所用模板（`templates/` 下的相对路径）；
-- - file_path：产物绝对路径（限定 `data/deliverables/` 白名单）。
CREATE TABLE IF NOT EXISTS summary_deliverables (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     INTEGER NOT NULL REFERENCES sources(id),
    task_id       INTEGER REFERENCES tasks(id),
    file_path     TEXT NOT NULL,
    template_used TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summary_deliverables_source
    ON summary_deliverables (source_id, id);
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
        _migrate(connection)
        connection.commit()


# 已存在的库补齐新增列：`CREATE TABLE IF NOT EXISTS` 不会改已建好的表，
# 故历史版本建的库需按列名探测后 `ALTER TABLE` 补列（幂等，不影响新库）。
MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    # TB-10：删除留痕；US23：任务级模型覆盖。
    "tasks": {"deleted_at": "TEXT", "provider_id": "INTEGER"},
    # TB-8：文档补「解析器标识」（pypdf / python-pptx / python-docx / plain-text）。
    "documents": {"parser": "TEXT"},
    # 工单 19：知识库资料的索引状态（来源表复用，靠 task_id 为空判定归属）。
    "sources": {
        "index_status": "TEXT NOT NULL DEFAULT 'stored'",
        "index_message": "TEXT",
        "indexed_at": "TEXT",
    },
}


def _migrate(connection: sqlite3.Connection) -> None:
    """对已有表补齐缺失列；已存在的列不动（重复运行无副作用）。"""
    for table, columns in MIGRATION_COLUMNS.items():
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, column_type in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
