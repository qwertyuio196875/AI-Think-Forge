"""成品生成编排：解析模板 → 写入 → 完整性检查 → 记录。

顺序是有意的：**先确认产物合格，再落库**。任何一步失败都不会留下成品记录，
也不会留下可被误认为成品的不完整文件（规格 US 22「结构损坏的成品不会被交到我手上」）。

本模块不做模型调用：成品是把**已确认的结构化方案**确定性渲染成文件，方案内容早已由
拷问流程定稿（这是「未经确认的推测绝不变成成品」的另一面）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app import config
from app.db.generation_repository import GenerationRepository
from app.db.template_repository import TemplateRepository
from app.generation.templates import resolve_template
from app.generation.word import build_word_deliverable, verify_word_deliverable

FORMAT_DOCX = "docx"
FORMAT_HTML = "html"


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
    output_path = _unique_output_path(output_dir, plan["id"])

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


def _unique_output_path(output_dir: Path, plan_id: int) -> Path:
    """成品文件名：方案号 + 时间戳；同一秒内重复生成时追加序号，不覆盖已有成品。"""
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = output_dir / f"plan-{plan_id}-{stamp}.docx"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = output_dir / f"plan-{plan_id}-{stamp}-{suffix}.docx"
    return candidate