"""成品（generation）与模板（template）的请求 / 响应模型。

规格 §4：`generations(id, task_id, plan_id, format, file_path, template_used, created_at)`。
术语（GLOSSARY）**成品**：方案确认后生成的最终文件；**模板**：样式文件；
「默认模板 / 临时覆盖」：全局默认 + 任务级临时选用，**临时选择不改变全局默认**。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GenerationFormat(str, Enum):
    """成品格式（ADR-0003：Word、单文件 HTML；工单 29 增 PPT 截图版）。

    - `docx`：Word 成品（方案 / 正文）；
    - `html`：单文件 HTML 演示（deck）；
    - `pptx`：截图版 PPT（HTML deck → 逐页截图 → 装配，ADR-0004）。
    """

    docx = "docx"
    html = "html"
    pptx = "pptx"


class GenerationSource(str, Enum):
    """成品来源（规格 §4：新增一列记录某次生成是否来自填充）。

    - `outline`：**大纲导出**——直接把方案正文渲染成文件（跳过填充）；
    - `body`：**正文成品**——来自填充写出的章节正文。

    术语（GLOSSARY）把两者明确区分开，因此它们在成品记录里必须是两个不同的值，
    不能靠文件名猜。中文标签由后端统一给，前端不另写一套翻译。
    """

    outline = "outline"
    body = "body"


GENERATION_SOURCE_LABELS: dict[str, str] = {
    "outline": "大纲导出",
    "body": "正文成品",
}


class GenerationRequest(BaseModel):
    """生成请求：格式 + 可选的**任务级临时覆盖**模板 / 演示主题。

    整体可省略（不传 body 即按默认格式 `docx`、走全局默认模板）。
    `theme` 只对 `format=html` 有意义（单文件 HTML 演示的主题族）；
    未指定时用默认主题，**未知主题一律明确报错**，不静默退回默认（工单硬要求）。
    """

    model_config = ConfigDict(extra="forbid")

    format: GenerationFormat = GenerationFormat.docx
    template: str | None = None
    theme: str | None = None

    @field_validator("template", "theme")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """纯空白的模板名 / 主题名视为「未指定」（走全局默认 / 内置默认主题）。"""
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
    # 截图版 PPT 所依据的来源页面规划（工单 29）；无规划的成品为 None。
    page_plan_id: int | None = None
    # 来源（正文成品 / 大纲导出）。这一列现在由后端给出，#18 收口文件名前缀时
    # 前端就能据此把两者一眼分开。
    source: GenerationSource = GenerationSource.outline
    source_label: str = GENERATION_SOURCE_LABELS["outline"]
    created_at: str

    @model_validator(mode="after")
    def _derive_source_label(self) -> Generation:
        """中文标签永远由来源派生：不让「状态说正文、标签说大纲」这种事发生。"""
        self.source_label = GENERATION_SOURCE_LABELS.get(self.source.value, self.source.value)
        return self


class GenerationResponse(Generation):
    """生成结果：记录 + 产物元数据。

    Word 一轨：样式是否贴合模板、缺哪些样式、标题数、完整性检查结论；
    单文件 HTML 一轨：所用主题、内联字体、中文回退、页数、外部资源清单、
    演讲者模式形态。两轨共用一个响应模型，字段各自按格式填充（默认值保证另一轨不缺字段）。
    """

    template_style_applied: bool = False
    missing_styles: list[str] = Field(default_factory=list)
    headings: int = 0
    integrity_ok: bool

    theme_used: str | None = None
    inlined_fonts: list[str] = Field(default_factory=list)
    cjk_fallback: bool = False
    slides: int = 0
    external_resources: list[str] = Field(default_factory=list)
    network_resources_declared: list[str] = Field(default_factory=list)
    presenter_mode: str | None = None


class DeckThemeInfo(BaseModel):
    """演示主题条目：调色板 / 内联字体 / 来源署名 / 许可 / 需保留的网络资源。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    palette: dict[str, str]
    fonts: list[str]
    cjk_fallback: bool
    derived_from: str
    license: str
    network_resources: list[str] = Field(default_factory=list)


class DeckThemeListResponse(BaseModel):
    """主题族清单（供前端主题选择器读同一份事实）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[DeckThemeInfo]
    total: int
    cjk_fallback: bool = True


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