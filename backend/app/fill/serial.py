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
from app.fill.deviation import measure, pick_regeneration_target, remaining_length
from app.fill.document import compose_body_markdown
from app.fill.history import build_history, summarize_section
from app.fill.writer import STATUS_COMPLETED, _write_body, write_section
from app.generation.service import generate_body_word_deliverable
from app.providers.model_client import ModelCallError

# 填充任务的终态（`fill_tasks.status` 的取值域）。
STATUS_COMPLETED_FILL = "completed"
STATUS_CANCELLED_FILL = "cancelled"
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

        # 中断检查放在**章节边界**上（工单 13）：正在写的那一章必须写完才能停，
        # 写到一半停下会在库里留下半章正文。所以这个判断在写之前、上一章写完之后。
        if fill_repository.is_cancel_requested(active["id"]):
            return _stop_cancelled(fill_repository, section_repository, plan, active)

        # 每章重新读一遍：剩余字数（工单 16）必须按**已落库**的正文算，
        # 用循环外的快照会一直把余量算成开跑前的值。
        current_rows = section_repository.list_for_plan(plan["id"])

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
                # 剩余字数（工单 16）：把「全文还剩多少」传给模型，否则它会照本章目标
                # 一路写下去，总字数必然超出去。
                remaining_length=remaining_length(current_rows, int(active["target_length"])),
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

    # 收尾偏差校验（工单 16）：只在**新写完**的章上做——若本次是「续写剩余章节」，
    # 那些早就写完的章不该因为这次的总量再被改一遍。
    if pending:
        _correct_deviation(
            task_id=task_id,
            plan=plan,
            model_client=model_client,
            model_name=model_name,
            section_repository=section_repository,
            template_repository=template_repository,
            generation_repository=generation_repository,
            data_dir=data_dir,
            templates_dir=templates_dir,
            target_length=int(active["target_length"]),
        )

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

    deviation = measure(refreshed, int(active["target_length"]))
    return {
        "fill": fill,
        "sections": refreshed,
        "deliverable": deliverable,
        "deviation": deviation,
    }


def _correct_deviation(
    *,
    task_id: int,
    plan: dict,
    model_client,
    model_name: str | None,
    section_repository: PlanSectionRepository,
    template_repository: TemplateRepository,
    generation_repository: GenerationRepository,
    data_dir: str,
    templates_dir: str,
    target_length: int,
) -> None:
    """偏差超过 ±15% 时，对**最短**的一章重生成一次（工单 16）。

    三条约束：
    - **只做一次**：写完还差，说明目标与这一章的体量不匹配；再重试只是继续烧额度。
      剩下的交给 `deviation.note` 明示偏差，由用户决定。
    - **只重那一章**：其他章节的正文逐字不动（「不截断、不注水」的落点）。
    - **不补写**：走的是整章重写，不是往末尾追加无意义的段落——规格明令不得注水。

    重生成失败只影响这次修正：正文保留、偏差如实上报，不把整次填充判成失败
    （已经写完的正文是合格产物，丢掉反而是损失）。
    """
    rows = section_repository.list_for_plan(plan["id"])
    if measure(rows, target_length).within_threshold:
        return

    target = pick_regeneration_target(rows)
    if target is None:
        return

    # 重写这一章时，把它该分到的份额作为目标：整章重写才有意义，追加段落等于注水。
    share = target["target_length"] or target_length
    try:
        body_md = _write_body(
            model_client=model_client,
            model_name=model_name,
            title=target["title"],
            key_points=target["key_points"],
            target_length=int(share),
            history=None,
        ).strip()
    except ModelCallError:
        # 重生成失败不回滚已写好的正文；偏差由调用方如实上报。
        return

    if not body_md:
        return

    section_repository.write_content(
        plan_id=plan["id"],
        seq=int(target["seq"]),
        content_md=body_md,
        status=STATUS_COMPLETED,
    )


def _completed_count(section_repository: PlanSectionRepository, plan_id: int) -> int:
    """已完成章节数（`plan_sections.status` 是唯一真源，不另设计数列）。"""
    return sum(
        1
        for row in section_repository.list_for_plan(plan_id)
        if row["status"] == STATUS_COMPLETED
    )


def _stop_cancelled(
    fill_repository: FillTaskRepository,
    section_repository: PlanSectionRepository,
    plan: dict,
    active: dict,
) -> dict:
    """按用户请求停下并返回（工单 13）。

    **不拼装成品**：中断时还没有写完整篇，此时出一份成品等于把「写了一半的文章」
    当成品交给用户。等用户续写跑完再出——这也是「中断本身不产生成品文件」的落点。
    """
    refreshed = section_repository.list_for_plan(plan["id"])
    fill = fill_repository.update_progress(
        active["id"],
        completed_sections=_completed_count(section_repository, plan["id"]),
        status=STATUS_CANCELLED_FILL,
        error=None,
    )
    assert fill is not None  # 填充任务刚刚存在，更新不会让它消失
    return {
        "fill": fill,
        "sections": refreshed,
        "deliverable": None,
        # 中断时也报当前偏差：用户要知道「停下来时已经写了多少」，好判断要不要续写。
        "deviation": measure(refreshed, int(active["target_length"])),
    }
