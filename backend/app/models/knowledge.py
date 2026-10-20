"""知识库资料（工单 19 / ADR-0005）的响应模型。

契约要点：
- 知识库资料复用 `sources` / `documents` / `document_chunks`，以**不隶属任何任务**
  表示归属；因此这里没有 `task_id` 字段，知识库视角里它恒为空。
- **索引状态是一等字段**：`index_status` 给机器值（`stored` / `indexing` / `failed`），
  `index_status_label` 同时给中文（已入库 / 索引中 / 索引失败），避免前端各自翻译；
  `index_message` 说明失败原因。解析或索引失败时资料**仍在清单里可看可读**，
  状态必须明确可见，绝不静默吞掉。
- `chunk_count` 是已落库的分块数；分块参数复用分析管线（1200 / 1800，按标题边界）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# 索引状态取值域：`indexing` 由后续的嵌入写入（工单 20）使用，本单只产出首尾两态。
INDEX_STATUS_LABELS: dict[str, str] = {
    "stored": "已入库",
    "indexing": "索引中",
    "failed": "索引失败",
}


class KnowledgeSourceItem(BaseModel):
    """知识库清单里的一份资料（含解析结果与索引状态）。"""

    model_config = ConfigDict(extra="forbid")

    source_id: int
    # 可读文件名：优先原始文件名，退回存储路径末段。
    name: str
    kind: str
    ref: str
    size: int | None = None
    document_id: int | None = None
    parse_status: str | None = None
    parse_message: str | None = None
    chunk_count: int = 0
    index_status: str
    index_status_label: str
    index_message: str | None = None
    indexed_at: str | None = None
    created_at: str


class KnowledgeSourceListResponse(BaseModel):
    """知识库清单：当页条目 + 总数 + 分页参数。"""

    model_config = ConfigDict(extra="forbid")

    items: list[KnowledgeSourceItem]
    total: int
    limit: int
    offset: int


class KnowledgeUploadResponse(BaseModel):
    """上传即入库的结果：入库后的资料 + 一句可读说明（失败时说明原因）。"""

    model_config = ConfigDict(extra="forbid")

    item: KnowledgeSourceItem
    message: str | None = None


class KnowledgeDeleteResponse(BaseModel):
    """删除结果：被删掉的资料 id 与连带清掉的分块数（便于用户确认）。"""

    model_config = ConfigDict(extra="forbid")

    source_id: int
    deleted_chunk_count: int = 0


class KnowledgeReindexRequest(BaseModel):
    """重建索引请求：给 `source_id` 只重建一份，留空则重建全部知识库资料。"""

    model_config = ConfigDict(extra="forbid")

    source_id: int | None = None


class KnowledgeReindexItem(BaseModel):
    """单份资料的重建结果（失败也如实列出，不中断整批）。"""

    model_config = ConfigDict(extra="forbid")

    source_id: int
    index_status: str
    index_status_label: str
    message: str | None = None


class KnowledgeReindexResponse(BaseModel):
    """重建索引汇总：逐份结果 + 总数（失败份数由状态体现，便于前端提示）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[KnowledgeReindexItem] = Field(default_factory=list)
    total: int = 0
