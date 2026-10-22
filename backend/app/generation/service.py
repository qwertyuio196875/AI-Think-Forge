"""成品生成编排：解析模板 → 写入 → 完整性检查 → 记录。

顺序是有意的：**先确认产物合格，再落库**。任何一步失败都不会留下成品记录，
也不会留下可被误认为成品的不完整文件（规格 US 22「结构损坏的成品不会被交到我手上」）。

本模块的**渲染**不做模型调用：成品是把**已确认的结构化方案**确定性渲染成文件，方案内容早已由
拷问流程定稿（这是「未经确认的推测绝不变成成品」的另一面）。**填充**（把大纲扩写成正文）
会调模型，但那是 `app.fill` 模块的职责，与这里的渲染是两条独立的路径（ADR-0006 决策一）。

两轨（ADR-0003）：
- Word：模板机制（`app.generation.word` / `templates`）；
- 单文件 HTML 演示：主题族（`app.generation.deck` / `themes`），资源全内联、无网络引用。

**两种输入**（规格 §2「/generations 的行为不因填充而改变，只是新增一种输入」）：
- 方案原文 → **大纲导出**（`generations.source = outline`）；
- 已填充的章节正文 → **正文成品**（`generations.source = body`）。
两者共用同一条「先确认产物合格再落库」的纪律，只是源文本与来源标记不同。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app import config
from app.db.generation_repository import SOURCE_BODY, GenerationRepository
from app.db.page_plan_repository import PagePlanRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.db.summary_deliverable_repository import SummaryDeliverableRepository
from app.db.template_repository import TemplateRepository
from app.generation.deck import (
    build_html_deck,
    build_html_deck_from_slides,
    verify_html_deliverable,
)
from app.generation.page_deck import slides_for_page_plan
from app.generation.pdfs import PdfRenderer, render_pdf, verify_pdf_deliverable
from app.generation.pptx import assemble_pptx, verify_pptx_deliverable
from app.generation.screenshots import SlideRenderer, screenshot_slides
from app.generation.templates import resolve_template
from app.generation.themes import DeckTheme
from app.generation.word import build_word_deliverable, verify_word_deliverable

FORMAT_DOCX = "docx"
FORMAT_HTML = "html"
FORMAT_PPTX = "pptx"
FORMAT_PDF = "pdf"

# 单文件 HTML 演示所用「主题模板」在生成记录里的标识前缀（`generations.template_used`）。
# 术语（GLOSSARY）**模板**：样式文件；HTML 一轨的样式载体就是主题，故沿用同一列记录，
# 加前缀与模板目录里的 `.docx` 相对路径区分开（语义不混淆，且不改表结构）。
DECK_TEMPLATE_PREFIX = "deck-theme:"

# 正文成品文件名前缀。与「大纲导出」的 `outline-` 前缀对称，一眼能分清哪份是成品。
BODY_FILE_PREFIX = "body-"

# 大纲导出文件名前缀（工单 18）。术语（GLOSSARY）：**大纲导出**是跳过填充、直接把
# 方案正文渲染成的成品，与填充后的正文成品是两种产物。前缀必须写在文件名里，
# 因为用户是从文件管理器里双击打开的——只靠 `generations.source` 他看不见。
OUTLINE_FILE_PREFIX = "outline-"


def deck_template_name(theme_id: str) -> str:
    """生成记录里「本次实际所用主题」的取值。"""
    return f"{DECK_TEMPLATE_PREFIX}{theme_id}"


def generate_word_deliverable(
    *,
    task_id: int,
    plan: dict,
    requested_template: str | None,
    data_dir: str | Path,
    templates_dir: str | Path,
    template_repository: TemplateRepository,
    generation_repository: GenerationRepository,
) -> dict:
    """生成一份 Word 成品并记录；返回记录 + 产物元数据。

    `requested_template` 是**任务级临时覆盖**：只影响本次生成（写进
    `generations.template_used`），不改写 `templates` 表的全局默认。
    """
    default_record = template_repository.get_default(FORMAT_DOCX)
    resolved = resolve_template(
        templates_dir,
        requested=requested_template,
        default_name=default_record["name"] if default_record else None,
    )

    output_dir = Path(data_dir) / config.DELIVERABLES_SUBDIR / str(task_id)
    output_path = _unique_output_path(
        output_dir, plan["id"], suffix=".docx", prefix=OUTLINE_FILE_PREFIX
    )

    build = build_word_deliverable(plan["content_md"], resolved.path, output_path)
    try:
        verify_word_deliverable(build)
    except Exception:
        # 结构损坏：丢弃产物，绝不交付、绝不落库（负测「不产生成品文件」）。
        output_path.unlink(missing_ok=True)
        raise

    record = generation_repository.create(
        task_id=task_id,
        plan_id=plan["id"],
        format=FORMAT_DOCX,
        file_path=str(output_path),
        template_used=resolved.template_used,
    )

    return {
        **record,
        "template_style_applied": build.template_style_applied,
        "missing_styles": list(build.missing_styles),
        "headings": build.headings,
        "integrity_ok": True,
    }


def generate_body_word_deliverable(
    *,
    task_id: int,
    plan: dict,
    body_md: str,
    requested_template: str | None,
    data_dir: str | Path,
    templates_dir: str | Path,
    template_repository: TemplateRepository,
    generation_repository: GenerationRepository,
) -> dict:
    """由**已填充的章节正文**生成一份 Word 成品并记录（工单 10）。

    与大纲导出走同一条纪律：**先确认产物合格，再落库**；失败删半成品、不落库。
    差别只有两处：源文本是正文而非方案正文、成品记录的 `source` 是 `body`。

    `body_md` 由 `app.fill.document.compose_body_markdown` 组装（章标题由系统给），
    本函数只负责渲染与记录，不关心正文从哪来。
    """
    default_record = template_repository.get_default(FORMAT_DOCX)
    resolved = resolve_template(
        templates_dir,
        requested=requested_template,
        default_name=default_record["name"] if default_record else None,
    )

    output_dir = Path(data_dir) / config.DELIVERABLES_SUBDIR / str(task_id)
    output_path = _unique_output_path(
        output_dir, plan["id"], suffix=".docx", prefix=BODY_FILE_PREFIX
    )

    build = build_word_deliverable(body_md, resolved.path, output_path)
    try:
        verify_word_deliverable(build)
    except Exception:
        # 结构损坏：丢弃产物，绝不交付、绝不落库（规格 US 22）。
        output_path.unlink(missing_ok=True)
        raise

    record = generation_repository.create(
        task_id=task_id,
        plan_id=plan["id"],
        format=FORMAT_DOCX,
        file_path=str(output_path),
        template_used=resolved.template_used,
        source=SOURCE_BODY,
    )

    return {
        **record,
        "template_style_applied": build.template_style_applied,
        "missing_styles": list(build.missing_styles),
        "headings": build.headings,
        "integrity_ok": True,
    }


def generate_summary_word_deliverable(
    *,
    source: dict,
    summary: dict,
    requested_template: str | None,
    data_dir: str | Path,
    templates_dir: str | Path,
    template_repository: TemplateRepository,
    deliverable_repository: SummaryDeliverableRepository,
) -> dict:
    """由「总结 + 引用」按模板生成 Word 交付并记录。

    与方案成品同一条纪律：**先确认产物合格，再落库**；任何失败删除半成品。
    总结没有结构化方案，故独立记入 `summary_deliverables`，绝不伪造 plan。
    """
    default_record = template_repository.get_default(FORMAT_DOCX)
    resolved = resolve_template(
        templates_dir,
        requested=requested_template,
        default_name=default_record["name"] if default_record else None,
    )

    task_id = source["task_id"]
    output_dir = (
        Path(data_dir) / config.DELIVERABLES_SUBDIR / str(task_id or "analysis")
    )
    output_path = _unique_summary_output_path(output_dir, source["id"])

    build = build_word_deliverable(
        build_summary_markdown(source, summary), resolved.path, output_path
    )
    try:
        verify_word_deliverable(build)
    except Exception:
        # 结构损坏：丢弃产物，绝不交付、绝不落库（规格 US 22）。
        output_path.unlink(missing_ok=True)
        raise

    record = deliverable_repository.create(
        source["id"],
        task_id=task_id,
        file_path=str(output_path),
        template_used=resolved.template_used,
    )
    return {
        **record,
        "format": FORMAT_DOCX,
        "template_style_applied": build.template_style_applied,
        "missing_styles": list(build.missing_styles),
        "headings": build.headings,
    }


def build_summary_markdown(source: dict, summary: dict) -> str:
    """把总结与引用组织成 Word 写入用的 Markdown（来源 / 总结 / 引用）。"""
    meta = source.get("meta") or {}
    name = meta.get("original_name") or source["ref"]
    lines = ["# 资料总结", "", "## 来源", "", f"- 名称：{name}"]
    url = meta.get("url") or meta.get("final_url")
    if url:
        lines.append(f"- URL：{url}")

    lines.extend(["", "## 总结", "", summary["text"], "", "## 引用", ""])
    for citation in summary.get("citations") or []:
        locator = json.dumps(
            citation.get("locator") or {}, ensure_ascii=False, sort_keys=True
        )
        lines.append(
            f"- 分块 {citation.get('chunk_seq')} · {locator}："
            f"{citation.get('excerpt') or ''}"
        )
    return "\n".join(lines) + "\n"


def generate_html_deliverable(
    *,
    task_id: int,
    plan: dict,
    task_title: str,
    theme: DeckTheme,
    data_dir: str | Path,
    generation_repository: GenerationRepository,
) -> dict:
    """生成一份**单文件 HTML 演示**并记录；返回记录 + 产物元数据。

    与 Word 一轨同一条纪律：渲染 → 完整性检查（无外部网络引用 + 结构可解析）→ 通过才落库。
    未通过则丢弃产物、不写记录（规格 US 22），绝不交付半成品。
    """
    output_dir = Path(data_dir) / config.DELIVERABLES_SUBDIR / str(task_id)
    output_path = _unique_output_path(
        output_dir, plan["id"], suffix=".html", prefix=OUTLINE_FILE_PREFIX
    )

    build = build_html_deck(
        plan_md=plan["content_md"],
        task_title=task_title,
        theme=theme,
        output_path=output_path,
    )
    try:
        verify_html_deliverable(build)
    except Exception:
        # 含外部引用 / 结构损坏：丢弃产物，绝不交付、绝不落库。
        output_path.unlink(missing_ok=True)
        raise

    record = generation_repository.create(
        task_id=task_id,
        plan_id=plan["id"],
        format=FORMAT_HTML,
        file_path=str(output_path),
        template_used=deck_template_name(theme.id),
    )

    return {
        **record,
        "integrity_ok": True,
        "theme_used": theme.id,
        "inlined_fonts": list(build.inlined_fonts),
        "cjk_fallback": True,
        "slides": build.slide_count,
        "external_resources": list(build.external_resources),
        "network_resources_declared": list(theme.network_resources),
        "presenter_mode": "in-page-overlay",
    }


def generate_pptx_deliverable(
    *,
    task_id: int,
    task_title: str,
    theme: DeckTheme,
    data_dir: str | Path,
    generation_repository: GenerationRepository,
    section_repository: PlanSectionRepository,
    page_plan_repository: PagePlanRepository,
    renderer: SlideRenderer,
) -> dict:
    """生成一份**截图版 PPT**（HTML deck → 逐页截图 → 装配 pptx）并记录。

    与 Word / HTML 同一条纪律：**先确认产物合格，再落库**；任何失败丢弃产物、不落库、
    磁盘上不留 pptx（规格 US 22 + issue #29 验收）。

    三步走（issue #29 验收 + ADR-0004）：
    1. 取最新页面规划（`page_plans.latest_for_task`）——没有规划 = 没有「章节 → 页列表」，
       截图版 PPT 无从谈起，明确报错（不落库、不产文件）；
    2. 页面规划 + 已填章节 → 渲染 HTML deck → 逐页截图（`renderer`，注入点）；
    3. 截图序列 → 装配 pptx → 回读校验（页数 = 规划页数 + 结尾页、每页一张满幅图）。
       校验通过才 `create(format="pptx", source=body, page_plan_id=...)`。

    `renderer` 是依赖注入点：生产传 `PlaywrightScreenshotRenderer()`（真实截图），测试
    **绝不启动浏览器**（注入产真实 PNG 的假实现）。
    """
    page_plan = page_plan_repository.latest_for_task(task_id)
    if page_plan is None:
        raise ValueError("该任务还没有页面规划：截图版 PPT 需要先按目标页数规划（#25）")
    page_plan_id = int(page_plan["id"])
    plan_id = int(page_plan["plan_id"])
    pages = _decode_pages(page_plan["pages_json"])

    sections = section_repository.list_for_plan(plan_id)
    slides = slides_for_page_plan(
        pages=pages,
        sections=sections,
        task_title=task_title,
        plan_title=task_title,
    )

    output_dir = Path(data_dir) / config.DELIVERABLES_SUBDIR / str(task_id)
    html_path = output_dir / f".pptx-stage-{page_plan_id}.html"
    build = build_html_deck_from_slides(
        slides=slides,
        task_title=task_title,
        plan_md="",
        theme=theme,
        output_path=html_path,
    )
    output_path = _unique_output_path(
        output_dir, page_plan_id, suffix=".pptx", prefix=BODY_FILE_PREFIX
    )

    # 截图 → 装配 → 校验，任一失败即丢弃，磁盘不留 pptx（issue #29 验收 ③）。
    try:
        pngs = screenshot_slides(build=build, output_dir=output_dir, renderer=renderer)
        assemble_pptx(pngs, output_path)
        verify_pptx_deliverable(output_path, expected_slides=len(slides))
    except Exception:
        output_path.unlink(missing_ok=True)
        html_path.unlink(missing_ok=True)
        raise

    output_path = Path(str(output_path))
    record = generation_repository.create(
        task_id=task_id,
        plan_id=plan_id,
        format=FORMAT_PPTX,
        file_path=str(output_path),
        template_used=deck_template_name(theme.id),
        source=SOURCE_BODY,
        page_plan_id=page_plan_id,
    )

    return {
        **record,
        "integrity_ok": True,
        "theme_used": theme.id,
        "slides": len(slides),
        "page_plan_id": page_plan_id,
    }


def generate_pdf_deliverable(
    *,
    task_id: int,
    task_title: str,
    theme: DeckTheme,
    data_dir: str | Path,
    generation_repository: GenerationRepository,
    section_repository: PlanSectionRepository,
    page_plan_repository: PagePlanRepository,
    renderer: PdfRenderer,
) -> dict:
    """生成一份**可选 PDF**（同一份 HTML deck 直接打印）并记录。

    与 `generate_pptx_deliverable` **同源同版式**：同一份页面规划、同一份 deck，只是导出
    方式不同（PDF 打印而非逐页截图装配）。因此两者页数与版式天然一致（issue #31 验收 ①）。

    纪律与既有各轨相同：**先确认产物合格，再落库**；打印失败 / 页数不符一律丢弃产物、
    不落库、磁盘不留 `.pdf`（验收 ②）。PDF 是**独立格式**，不参与也不阻塞 HTML / PPTX
    的生成路径（验收 ③）。
    """
    page_plan = page_plan_repository.latest_for_task(task_id)
    if page_plan is None:
        raise ValueError("该任务还没有页面规划：PDF 需要先按目标页数规划（#25）")
    page_plan_id = int(page_plan["id"])
    plan_id = int(page_plan["plan_id"])
    pages = _decode_pages(page_plan["pages_json"])

    sections = section_repository.list_for_plan(plan_id)
    slides = slides_for_page_plan(
        pages=pages,
        sections=sections,
        task_title=task_title,
        plan_title=task_title,
    )

    output_dir = Path(data_dir) / config.DELIVERABLES_SUBDIR / str(task_id)
    html_path = output_dir / f".pdf-stage-{page_plan_id}.html"
    build = build_html_deck_from_slides(
        slides=slides,
        task_title=task_title,
        plan_md="",
        theme=theme,
        output_path=html_path,
    )
    output_path = _unique_output_path(
        output_dir, page_plan_id, suffix=".pdf", prefix=BODY_FILE_PREFIX
    )

    # 打印 → 回读校验，任一失败即丢弃，磁盘不留 pdf（issue #31 验收 ②）。
    try:
        render_pdf(build=build, output_path=output_path, renderer=renderer)
        verify_pdf_deliverable(output_path, expected_pages=len(slides))
    except Exception:
        output_path.unlink(missing_ok=True)
        html_path.unlink(missing_ok=True)
        raise

    record = generation_repository.create(
        task_id=task_id,
        plan_id=plan_id,
        format=FORMAT_PDF,
        file_path=str(output_path),
        template_used=deck_template_name(theme.id),
        source=SOURCE_BODY,
        page_plan_id=page_plan_id,
    )

    return {
        **record,
        "integrity_ok": True,
        "theme_used": theme.id,
        "slides": len(slides),
        "page_plan_id": page_plan_id,
    }


def _decode_pages(pages_json: str) -> list[dict]:
    """把 `page_plans.pages_json` 反序列化成页列表；损坏则抛明确错误。"""
    import json as _json

    try:
        pages = _json.loads(pages_json)
    except (_json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"页面规划 `pages_json` 无法解析：{exc}") from exc
    if not isinstance(pages, list):
        # 业务闸门（路由捕获 ValueError → 409「尚未规划」），不能用 TypeError。
        raise ValueError("页面规划 `pages_json` 必须是页列表")  # noqa: TRY004
    return pages


def _unique_output_path(
    output_dir: Path, plan_id: int, *, suffix: str, prefix: str = ""
) -> Path:
    """成品文件名：来源前缀 + 方案号 + 时间戳；同秒重复生成时追加序号，不覆盖已有成品。

    `prefix` 是**来源前缀**，必须由调用方显式给出：
    - 大纲导出用 `outline-`（工单 18）；
    - 正文成品用 `body-`（工单 10）。
    不给缺省值会让一次漏传就产出「身份不明」的文件，所以这里保留空串兜底只为兼容
    既有测试的调用形态，两条生产路径都显式传。
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = output_dir / f"{prefix}plan-{plan_id}-{stamp}{suffix}"
    order = 1
    while candidate.exists():
        order += 1
        candidate = output_dir / f"{prefix}plan-{plan_id}-{stamp}-{order}{suffix}"
    return candidate


def _unique_summary_output_path(output_dir: Path, source_id: int) -> Path:
    """总结 Word 文件名：`summary-{source_id}-{timestamp}.docx`（同秒追加序号）。"""
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = output_dir / f"summary-{source_id}-{stamp}.docx"
    order = 1
    while candidate.exists():
        order += 1
        candidate = output_dir / f"summary-{source_id}-{stamp}-{order}.docx"
    return candidate
