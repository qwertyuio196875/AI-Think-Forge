"""单章写作：把「成品章节」扩写成正文并落库（工单 10 / ADR-0006）。

这是本系统**第一次真正的写作调用**（此前交付的只是方案本身）。本模块只做一章，
逐章串行推进的编排属工单 11；前情提要（#12）、中断续写（#13）、单章重写（#14）、
字数分摊（#15）、偏差修正（#16）、长章分段（#17）都不在这里。

三段纪律：

1. **先判、再写、再落库**：闸门（方案已确认）→ 调模型 → 写正文与状态 → 拼装成品。
   模型失败时章节标「失败」、**不产出成品文件**（失败必须留痕，但绝不交付半成品）。
2. **模型调用用按次覆盖**（#3）：长章节要更高的输出上限与更长的超时，
   `max_tokens=8192 / timeout=180.0`；渲染类调用维持既有默认值不变。
3. **先确认产物合格再落库**：正文写进章节表之后，成品由 `app.generation` 渲染并
   回读校验；不合格则删除半成品、不落成品记录。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.fill_task_repository import FillTaskRepository
from app.db.generation_repository import GenerationRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.db.template_repository import TemplateRepository
from app.fill.document import compose_body_markdown
from app.fill.prompts import render_section_messages
from app.generation.service import generate_body_word_deliverable
from app.providers.model_client import ModelCallError, complete_text
from app.sections.service import to_section_items

# 单章写作的按次调用参数（#3）：长章节不再被 4096 token / 60 秒卡住。
# 渲染类调用维持既有默认值——「生成类调用超时分级」（ADR-0006）。
SECTION_MAX_TOKENS = 8192
SECTION_TIMEOUT_SECONDS = 180.0

# 章节状态（`plan_sections.status` 的取值域）。
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def ensure_section_writable(section: dict) -> None:
    """已写完的章不重复写 → 409（重写是工单 14 的职责，另开端点）。

    已失败的章**可以**再写：失败就是「没写成」，重试是自然的下一步。
    """
    if section["status"] == STATUS_COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"第 {section['seq']} 章已经是「已完成」，不能重复填充"
                "（如需重写请走单章重写入口）"
            ),
        )


def require_active_fill(
    fill_repository: FillTaskRepository, task_id: int
) -> dict:
    """没有进行中的填充任务 → 409：填充是独立阶段，得先「确认开始填充」。

    不静默代填：没有填充任务就没有本次填充的目标字数与上下文，替他猜一套
    等于凭空造一次填充。
    """
    active = fill_repository.active_for_task(task_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"任务 {task_id} 没有进行中的填充任务，无法写入章节正文"
                "（请先开始填充）"
            ),
        )
    return active


def write_section(
    *,
    task_id: int,
    plan: dict,
    seq: int,
    model_client,
    model_name: str | None,
    section_repository: PlanSectionRepository,
    fill_repository: FillTaskRepository,
    template_repository: TemplateRepository,
    generation_repository: GenerationRepository,
    data_dir: str,
    templates_dir: str,
) -> dict:
    """写一章正文并随即拼装成品；返回（章节项, 成品记录）。

    顺序：写正文（落库）→ 拼装成品（渲染 + 回读校验）→ 落成品记录。
    模型失败走 `ModelCallError`，由路由翻成 502；此时章节已标「失败」、
    成品文件不存在。
    """
    rows = section_repository.list_for_plan(plan["id"])
    section = next((row for row in rows if int(row["seq"]) == seq), None)
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"当前方案没有第 {seq} 章，无法填充",
        )

    ensure_section_writable(section)
    fill = require_active_fill(fill_repository, task_id)

    messages = render_section_messages(
        title=section["title"],
        key_points=section["key_points"],
        target_length=section["target_length"],
    )

    try:
        body_md = complete_text(
            model_client,
            messages,
            model=model_name,
            max_tokens=SECTION_MAX_TOKENS,
            timeout=SECTION_TIMEOUT_SECONDS,
        ).strip()
    except ModelCallError:
        # 失败留痕：章节标「失败」，不写正文、不产出成品。
        section_repository.write_content(
            plan_id=plan["id"], seq=seq, content_md="", status=STATUS_FAILED
        )
        fill_repository.update_progress(
            fill["id"],
            completed_sections=_completed_count(rows),
            status="failed",
            error=f"第 {seq} 章生成失败",
        )
        raise

    if not body_md:
        # 模型给了空正文：算失败，不落「已完成」的空白章。
        section_repository.write_content(
            plan_id=plan["id"], seq=seq, content_md="", status=STATUS_FAILED
        )
        fill_repository.update_progress(
            fill["id"],
            completed_sections=_completed_count(rows),
            status="failed",
            error=f"第 {seq} 章生成失败：模型没有返回正文",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"第 {seq} 章生成失败：模型没有返回正文",
        )

    updated = section_repository.write_content(
        plan_id=plan["id"], seq=seq, content_md=body_md, status=STATUS_COMPLETED
    )
    assert updated is not None  # 章节刚刚存在，写入不会让它消失

    # 进度按**库里已完成章节数**给（唯一真源是 plan_sections.status）。
    refreshed = section_repository.list_for_plan(plan["id"])
    fill_repository.update_progress(
        fill["id"],
        completed_sections=_completed_count(refreshed),
        status="running",
        error=None,
    )

    # 随即拼装成品：章标题由系统给，只拼已写正文的章。
    body_md_document = compose_body_markdown(refreshed)
    record = generate_body_word_deliverable(
        task_id=task_id,
        plan=plan,
        body_md=body_md_document,
        requested_template=None,
        data_dir=data_dir,
        templates_dir=templates_dir,
        template_repository=template_repository,
        generation_repository=generation_repository,
    )

    item = to_section_items([updated])[0]
    return {"fill_id": fill["id"], "section": item, "deliverable": record}


def _completed_count(rows: list[dict]) -> int:
    """已完成章节数（`plan_sections.status` 是唯一真源，不另设计数列）。"""
    return sum(1 for row in rows if row["status"] == STATUS_COMPLETED)
