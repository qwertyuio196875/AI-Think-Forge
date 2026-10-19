"""成品（generation）与模板（template）的请求 / 响应模型。

规格 §4：`generations(id, task_id, plan_id, format, file_path, template_used, created_at)`。
术语（GLOSSARY）**成品**：方案确认后生成的最终文件；**模板**：样式文件；
「默认模板 / 临时覆盖」：全局默认 + 任务级临时选用，**临时选择不改变全局默认**。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GenerationFormat(str, Enum):
    """成品格式（ADR-0003 首版双轨：Word 与单文件 HTML）。"""

    docx = "docx"
    html = "html"


class GenerationRequest(BaseModel):
    """生成请求：格式 + 可选的**任务级临时覆盖**模板。

    整体可省略（不传 body 即按默认格式 `docx`、走全局默认模板）。
    """

    model_config = ConfigDict(extra="forbid")

    format: GenerationFormat = GenerationFormat.docx
    template: str | None = None

    @field_validator("template")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """纯空白的模板名视为「未指定」（走全局默认 / 内置默认模板）。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class Generation(BaseModel):
    """成品记录（对外字段集）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    task_id: int
    plan_id: int
    format: GenerationFormat
    file_path: str
    template_used: str
    created_at: str


class GenerationResponse(Generation):
    """生成结果：记录 + 产物元数据（样式是否贴合模板、完整性检查结论）。"""

    template_style_applied: bool
    missing_styles: list[str] = Field(default_factory=list)
    headings: int
    integrity_ok: bool


class GenerationListResponse(BaseModel):
    """某任务的成品列表（供成品卡渲染）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[Generation]
    total: int


class TemplateRegisterRequest(BaseModel):
    """登记一个已放入 `templates/` 的模板文件。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _reject_blank_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("模板名称不能为空")
        return stripped


class Template(BaseModel):
    """模板条目：名称 / 格式 / 是否全局默认 / 是否内置 / 是否可作为模板使用。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    format: str
    is_default: bool
    builtin: bool
    usable: bool
    registered: bool
    missing: bool = False


class TemplateListResponse(BaseModel):
    """模板清单（模板目录的实际情况 + 登记元数据）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[Template]
    total: int


class TemplateRegisterResponse(BaseModel):
    """登记结果：登记记录 + 该格式当前生效的全局默认模板名。"""

    model_config = ConfigDict(extra="forbid")

    template: Template
    default_template: str | None