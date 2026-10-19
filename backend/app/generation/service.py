"""成品生成编排：解析模板 → 写入 → 完整性检查 → 记录。

顺序是有意的：**先确认产物合格，再落库**。任何一步失败都不会留下成品记录，
也不会留下可被误认为成品的不完整文件（规格 US 22「结构损坏的成品不会被交到我手上」）。

本模块不做模型调用：成品是把**已确认的结构化方案**确定性渲染成文件，方案内容早已由
拷问流程定稿（这是「未经确认的推测绝不变成成品」的另一面）。

两轨（ADR-0003）：
- Word：模板机制（`app.generation.word` / `templates`）；
- 单文件 HTML 演示：主题族（`app.generation.deck` / `themes`），资源全内联、无网络引用。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app import config
from app.db.generation_repository import GenerationRepository
from app.db.summary_deliverable_repository import SummaryDeliverableRepository
from app.db.template_repository import TemplateRepository
from app.generation.deck import build_html_deck, verify_html_deliverable
from app.generation.templates import resolve_template
from app.generation.themes import DeckTheme
from app.generation.word import build_word_deliverable, verify_word_deliverable

FORMAT_DOCX = "docx"
FORMAT_HTML = "html"

# 单文件 HTML 演示所用「主题模板」在生成记录里的标识前缀（`generations.template_used`）。
# 术语（GLOSSARY）**模板**：样式文件；HTML 一轨的样式载体就是主题，故沿用同一列记录，
# 加前缀与模板目录里的 `.docx` 相对路径区分开（语义不混淆，且不改表结构）。
DECK_TEMPLATE_PREFIX = "deck-theme:"


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
    output_path = _unique_output_path(output_dir, plan["id"], suffix=".docx")

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
    output_path = _unique_output_path(output_dir, plan["id"], suffix=".html")

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


def _unique_output_path(output_dir: Path, plan_id: int, *, suffix: str) -> Path:
    """成品文件名：方案号 + 时间戳；同一秒内重复生成时追加序号，不覆盖已有成品。"""
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = output_dir / f"plan-{plan_id}-{stamp}{suffix}"
    order = 1
    while candidate.exists():
        order += 1
        candidate = output_dir / f"plan-{plan_id}-{stamp}-{order}{suffix}"
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
