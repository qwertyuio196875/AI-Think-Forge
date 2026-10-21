"""全篇逐章串行填充的编排（工单 11 / ADR-0006）。

**为什么逐章串行**：每章的正文要承接上一章，因此必须一次写一章、拿到结果再写下一章。
并发写会得到一篇「N 段互不相干的短文拼接」的文章；一次整篇写则在长文上必然缩水，
而且某一章写砸了只能整篇重来。

**失败纪律**（工单 11 的硬要求）：
- 任一章失败 → 立刻停下，**不产出残缺成品**，报错里指明是第几章；
- 失败之前已经写成的章**保留**（它们本身是合格的，丢掉反而是损失）；
- 填充任务标「失败」并留痕是哪一章。

**本模块只做编排**：每一章的写作动作仍然走 `app.fill.writer.write_section`，
因此工单 10 的既有契约（失败留痕、模型调用参数、空正文算失败）一条都不改。

工单 12 在本模块接入**前情提要**：每章写完后压一段约 100 字摘要，累积成提要喂给
下一章。摘要调用失败只丢这段提要，不阻断正文生成。
本单不引入中断续写（#13）、单章重写（#14）、字数分摊（#15）、偏差修正（#16）、
长章分段（#17）——那些各自接在 write_section 之上。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.fill_task_repository import FillTaskRepository
from app.db.generation_repository import GenerationRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.db.template_repository import TemplateRepository
from app.fill.document import compose_body_markdown
from app.fill.history import build_history, summarize_section
from app.fill.writer import STATUS_COMPLETED, write_section
from app.generation.service import generate_body_word_deliverable
from app.providers.model_client import ModelCallError

# 填充任务的两种终态（`fill_tasks.status` 的取值域）。
STATUS_COMPLETED_FILL = "completed"
STATUS_FAILED = "failed"


def run_serial_fill(
    *,
    task_id: int,
    plan: dict,
    model_client,
    model_name: str | None,
    section_repository: PlanSectionRepository,
    fill_repository: FillTaskRepository,
    template_repository: TemplateRepository,
    generation_repository: GenerationRepository,
    data_dir: str,
    templates_dir: str,
) -> dict:
    """把剩余章节一章一章写完，返回（填充任务行, 章节行清单, 成品记录）。

    顺序：取清单 → 跳过已写完的章 → 逐章写 → 全部写完后整体拼装成品。

    「跳过已写完的章」是必要的：写完第一章后若再跑一次，不该把第一章重写一遍
    （重写是工单 14 的职责，且重写会丢掉用户可能已经看过的正文）。
    """
    rows = section_repository.list_for_plan(plan["id"])
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前方案没有可填充的章节，请返回修订方案",
        )

    active = fill_repository.active_for_task(task_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务 {task_id} 没有进行中的填充任务，无法开始填充（请先开始填充）",
        )

    pending = [row for row in rows if row["status"] != STATUS_COMPLETED]

    # 前情提要：已写完的章各压一段摘要，累积起来喂给下一章（工单 12）。
    # 只取**已完成**的章——失败或待写的章没有正文可压。
    summaries: list[str] = []
    for row in rows:
        if row["status"] != STATUS_COMPLETED:
            continue
        summary = summarize_section(
            model_client=model_client,
            model_name=model_name,
            title=row["title"],
            body_md=row["content_md"],
        )
        if summary:
            summaries.append(summary)

    for row in pending:
        seq = int(row["seq"])
        try:
            write_section(
                task_id=task_id,
                plan=plan,
                seq=seq,
                model_client=model_client,
                model_name=model_name,
                section_repository=section_repository,
                fill_repository=fill_repository,
                template_repository=template_repository,
                generation_repository=generation_repository,
                data_dir=data_dir,
                templates_dir=templates_dir,
                # 中途不拼装成品：写完一半的成品是残件，全部写完再一次性拼。
                build_deliverable=False,
                # 前情提要：第一章为空（不喂「暂无」占位）。
                history=build_history(summaries),
            )
        except ModelCallError as exc:
            # 失败留痕：写清是第几章，别只留一句「生成失败」。
            fill_repository.update_progress(
                active["id"],
                completed_sections=_completed_count(section_repository, plan["id"]),
                status=STATUS_FAILED,
                error=f"第 {seq} 章生成失败：{exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"第 {seq} 章生成失败：{exc}",
            ) from exc

        # 本章写完 → 压一段摘要，供下一章承接。
        # 摘要失败只丢这段提要（summarize_section 返回 None），正文已落库，不回滚。
        written = section_repository.list_for_plan(plan["id"])
        current = next((item for item in written if int(item["seq"]) == seq), None)
        if current is not None:
            summary = summarize_section(
                model_client=model_client,
                model_name=model_name,
                title=current["title"],
                body_md=current["content_md"],
            )
            if summary:
                summaries.append(summary)

    # 全部写完：整体重新拼装成品（成品目录与章节清单同源）。
    refreshed = section_repository.list_for_plan(plan["id"])
    deliverable = generate_body_word_deliverable(
        task_id=task_id,
        plan=plan,
        body_md=compose_body_markdown(refreshed),
        requested_template=None,
        data_dir=data_dir,
        templates_dir=templates_dir,
        template_repository=template_repository,
        generation_repository=generation_repository,
    )

    fill = fill_repository.update_progress(
        active["id"],
        completed_sections=_completed_count(section_repository, plan["id"]),
        status=STATUS_COMPLETED_FILL,
        error=None,
    )
    assert fill is not None  # 填充任务刚刚存在，更新不会让它消失
    return {"fill": fill, "sections": refreshed, "deliverable": deliverable}


def _completed_count(section_repository: PlanSectionRepository, plan_id: int) -> int:
    """已完成章节数（`plan_sections.status` 是唯一真源，不另设计数列）。"""
    return sum(
        1
        for row in section_repository.list_for_plan(plan_id)
        if row["status"] == STATUS_COMPLETED
    )
