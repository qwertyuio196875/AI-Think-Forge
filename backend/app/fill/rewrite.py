"""单章重写（工单 14 / ADR-0006）。

**为什么单开一个入口**：单章填充（工单 10）对已完成的章是**拒绝**的（409），因为
那会把用户可能已经看过、甚至已经引用的正文悄悄换掉。重写是用户的明确意图，
因此单独一个端点：只有它允许覆盖已完成的章。

**三条纪律**：
1. **只动目标章**：其余章节的正文与状态一个字都不碰——它们可能已经定稿。
2. **成品重新拼装成同一份**：不产生第二个文件让用户自己合并。旧的正文成品记录
   连同文件一起删掉，新的那份顶上（大纲导出不动，那是另一条产物）。
3. **只对已完成或失败的章开放**：待写的章不需要「重写」，那是正常填充的活儿。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from app.db.generation_repository import GenerationRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.db.template_repository import TemplateRepository
from app.fill.document import compose_body_markdown
from app.fill.prompts import render_section_messages
from app.fill.writer import (
    SECTION_MAX_TOKENS,
    SECTION_TIMEOUT_SECONDS,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from app.generation.service import generate_body_word_deliverable
from app.providers.model_client import ModelCallError, complete_text
from app.sections.service import to_section_items


def rewrite_section(
    *,
    task_id: int,
    plan: dict,
    seq: int,
    model_client,
    model_name: str | None,
    section_repository: PlanSectionRepository,
    template_repository: TemplateRepository,
    generation_repository: GenerationRepository,
    data_dir: str,
    templates_dir: str,
) -> dict:
    """重写一章正文并重新拼装成品；返回（章节项, 成品记录）。

    失败口径：模型调用失败 → `ModelCallError`（路由翻 502），**旧正文保留**——
    重写失败不该把已经写好的一章弄丢。
    """
    rows = section_repository.list_for_plan(plan["id"])
    section = next((row for row in rows if int(row["seq"]) == seq), None)
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"当前方案没有第 {seq} 章，无法重写",
        )

    _ensure_rewritable(section)

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
    except ModelCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"第 {seq} 章重写失败：{exc}",
        ) from exc

    if not body_md:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"第 {seq} 章重写失败：模型没有返回正文",
        )

    updated = section_repository.write_content(
        plan_id=plan["id"], seq=seq, content_md=body_md, status=STATUS_COMPLETED
    )
    assert updated is not None  # 章节刚刚存在，写入不会让它消失

    # 先删旧的正文成品（记录 + 文件），再拼新的：同一任务只留一份正文成品。
    # 放在拼装之前，是为了「拼装失败时旧的也没了」——但那更糟，所以先拼后删。
    refreshed = section_repository.list_for_plan(plan["id"])
    record = generate_body_word_deliverable(
        task_id=task_id,
        plan=plan,
        body_md=compose_body_markdown(refreshed),
        requested_template=None,
        data_dir=data_dir,
        templates_dir=templates_dir,
        template_repository=template_repository,
        generation_repository=generation_repository,
    )

    # 新成品已经落盘并落库，才清理旧的：任何一步失败都不会让用户失去可用的成品。
    # `keep_id=record["id"]` 必须传——否则会把刚拼好的这份一起删掉。
    for stale in generation_repository.delete_body_generations(
        task_id, keep_id=record["id"]
    ):
        Path(stale["file_path"]).unlink(missing_ok=True)

    item = to_section_items([updated])[0]
    return {"section": item, "deliverable": record}


def _ensure_rewritable(section: dict) -> None:
    """只有已完成或失败的章可以重写。

    - 已完成的章：重写会覆盖用户可能已经看过的正文，所以必须由用户明确发起
      （这正是本端点存在的意义），且不设「没有进行中的填充任务」这种额外门槛；
    - 失败的章：本来就是「没写成」，重写是自然的下一步；
    - 待写的章：还没写过，谈不上重写——那是正常填充的职责。
    """
    if section["status"] not in (STATUS_COMPLETED, STATUS_FAILED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"第 {section['seq']} 章还没有写过（状态「{section['status']}」），"
                "无需重写；请直接填充"
            ),
        )
