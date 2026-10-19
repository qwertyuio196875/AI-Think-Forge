"""资料分析的请求 / 响应模型（术语：资料分析 / 总结 / 未识别 / 来源 / 分块）。

契约要点：
- **未识别是一级输出字段**：`unrecognized` 用统一契约
  `{unrecognized, reason, locator, needs_ocr}`；`unrecognized_parts` 列出「有正文但
  仍有读不到的内容」（如图片）。没有文本时绝不返回空字符串冒充成功。
- 总结响应带 `provider_kind` / `provider_used` / `model_used` / `provider_fallback`，
  使「总结走 turbo 档」与「档位缺失回退默认」可被观察、不静默。
- 引用 `citations` 给出总结来自哪些分块 / 位置（chunk_seq + locator + 摘录）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.task import Task


class UnrecognizedContent(BaseModel):
    """未识别内容（调研 A6 的统一契约）。"""

    model_config = ConfigDict(extra="forbid")

    unrecognized: bool = True
    reason: str
    locator: dict[str, Any]
    needs_ocr: bool = False


class SourceInfo(BaseModel):
    """来源（资料登记）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: str
    ref: str
    meta: dict[str, Any] = Field(default_factory=dict)
    task_id: int | None = None
    created_at: str


class DocumentInfo(BaseModel):
    """文档解析结果；`chunks` 为已落库的分块数。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    source_id: int
    path: str
    parse_status: str
    parse_message: str | None = None
    heading_source: str | None = None
    # 解析器标识（pypdf / python-pptx / python-docx / plain-text）；解析失败时为 None。
    parser: str | None = None
    encoding: str | None = None
    headings: int = 0
    images: int = 0
    chunks: int = 0
    created_at: str


class AnalysisSourceResponse(BaseModel):
    """上传 + 解析的结果。

    解析失败时仍返回 201 与 `parse_status="failed"` + 可读 `message`：
    来源 / 文档已入库，用户可据此重试或换文件（「不丢已存数据」）。
    """

    model_config = ConfigDict(extra="forbid")

    source: SourceInfo
    document: DocumentInfo
    unrecognized: UnrecognizedContent | None = None
    unrecognized_parts: list[UnrecognizedContent] = Field(default_factory=list)
    message: str | None = None


class SummaryCitation(BaseModel):
    """总结引用：来自哪个分块、什么位置、该块开头摘录。"""

    model_config = ConfigDict(extra="forbid")

    chunk_seq: int
    locator: dict[str, Any]
    excerpt: str


class AnalysisSummary(BaseModel):
    """总结（含长度、引用与实际所用档位证据）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    source_id: int
    task_id: int | None
    text: str
    hanzi_count: int
    citations: list[SummaryCitation] = Field(default_factory=list)
    chunk_count: int
    truncated: bool
    provider_kind: str | None
    provider_used: str | None
    model_used: str | None
    provider_fallback: bool
    provider_note: str | None = None
    created_at: str


class AnalysisResultResponse(BaseModel):
    """一次分析的结果：有总结，或（未识别时）只有显式的未识别契约。"""

    model_config = ConfigDict(extra="forbid")

    source: SourceInfo
    document: DocumentInfo
    summary: AnalysisSummary | None = None
    unrecognized: UnrecognizedContent | None = None
    unrecognized_parts: list[UnrecognizedContent] = Field(default_factory=list)
    message: str | None = None


class SendToCreationRequest(BaseModel):
    """一键送入主题创作：可选标题覆盖（默认取资料文件名）。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None

    @field_validator("title")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """纯空白标题视为未提供，默认由资料来源名派生。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SendToCreationResponse(BaseModel):
    """送入结果：新建的主题创作任务 + 预填的已知信息。"""

    model_config = ConfigDict(extra="forbid")

    task: Task
    source_id: int
    summary_id: int
    known_input: str
