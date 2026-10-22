"""填充入口（工单 9 / ADR-0006）：`POST /api/tasks/{task_id}/fill`。

为什么是独立端点而不是 `/generations` 的一个参数：填充与成品生成是**两个阶段、两种
保证**——填充会调模型、写正文、可能失败在第三章；生成是确定性渲染。混在一个端点上，
前端就没法表达「先填充，再导出」这个先后关系（ADR-0006 决策一）。

本单只到「入口 + 初始进度」为止：建一条 `fill_tasks` 记录、返回章节清单。**不调模型、
不写正文**（#10 / #11 接手）。因此响应里的 `completed_sections` 恒为 0、各章 `status`
恒为 `pending`。

拒绝口径（错误码沿用全局约定）：
- 任务不存在 → 404；
- 无方案 / 方案未确认 / 有未处置待确认事项 → 409（与 `/generations` 同一套闸门，口径
  见 `app.api.gates`）；
- 已确认但切不出章节 → 422，并提示返回修订方案（ADR-0006：不猜、不退化切分）；
- 逐章字数含不存在的章节序号 / 目标字数超上限 → 422。

工单 10 追加 `POST /api/tasks/{task_id}/sections/{seq}/fill`：写**一章**正文并随即
拼装成品（见 `app.fill.writer`）。

工单 11 追加 `POST /api/tasks/{task_id}/fill/run`：把剩余章节**逐章串行**写完
（见 `app.fill.serial`），全部写完后整体重新拼装成品。任一章失败即停下、报错指出
是第几章、**不产出残缺成品**。

工单 13 追加 `POST /api/tasks/{task_id}/fill/cancel`：置中断标记，串行循环在章节
边界上停下；中断本身不产出成品、也不算失败。

工单 14 追加 `POST /api/tasks/{task_id}/sections/{seq}/rewrite`：只重写一章，
成品重新拼装成同一份（旧正文成品记录与文件一并清理）。

工单 15 追加 `POST /api/tasks/{task_id}/fill/allocation`：**只算不写**的分摊预览，
让参数弹窗在确认前就能看到「哪一章多少字」，并支持逐章调整。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    DataDirDep,
    FillTaskRepositoryDep,
    GenerationRepositoryDep,
    ModelClientDep,
    OpenItemRepositoryDep,
    PlanRepositoryDep,
    PlanSectionRepositoryDep,
    ProviderRepositoryDep,
    RetrievalServiceDep,
    TaskRepositoryDep,
    TemplateRepositoryDep,
    TemplatesDirDep,
)
from app.api.gates import require_confirmed_plan
from app.fill.deviation import measure
from app.fill.rewrite import rewrite_section
from app.fill.serial import run_serial_fill
from app.fill.service import (
    ensure_sections_exist,
    plan_lengths,
    preview_section_references,
    start_fill,
)
from app.fill.writer import write_section
from app.models.fill import (
    FILL_STATUS_LABELS,
    FillAllocationItem,
    FillAllocationResponse,
    FillRequest,
    FillResponse,
    SectionFillRequest,
    SectionReferencesResponse,
    SectionRewriteResponse,
    SectionWriteResponse,
    SerialFillResponse,
)
from app.providers.model_client import ModelCallError
from app.providers.task_model import model_for_task
from app.sections.service import to_section_items

router = APIRouter(prefix="/tasks", tags=["fill"])


@router.post("/{task_id}/fill", response_model=FillResponse)
def start_fill_task(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    fill_repository: FillTaskRepositoryDep,
    payload: FillRequest | None = None,
) -> FillResponse:
    """开始一次填充：落实字数参数、登记填充任务、返回初始进度。

    请求体可省略（`{}` 或空）：目标字数此时按方案各章建议字数求和，方案没给则用缺省值。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    fill, rows = start_fill(
        task_id=task_id,
        plan=plan,
        payload=payload or FillRequest(),
        section_repository=section_repository,
        fill_repository=fill_repository,
    )

    items = to_section_items(rows)
    return FillResponse(
        id=fill["id"],
        task_id=fill["task_id"],
        plan_id=fill["plan_id"],
        target_length=fill["target_length"],
        completed_sections=fill["completed_sections"],
        status=fill["status"],
        status_label=FILL_STATUS_LABELS.get(fill["status"], fill["status"]),
        error=fill["error"],
        created_at=fill["created_at"],
        items=items,
        total=len(items),
    )


@router.post("/{task_id}/fill/allocation", response_model=FillAllocationResponse)
def preview_allocation(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    payload: FillRequest | None = None,
) -> FillAllocationResponse:
    """试算一次字数分摊（工单 15）：**只算不写**，不改章节表、不建填充任务。

    为什么单独开一个只读端点：用户在参数弹窗里改字数时需要立刻看到「哪一章多少字」，
    而 `POST /fill` 会真的登记一次填充任务。同一条分摊规则只实现一次（`app.fill.budget`），
    预览与真正开工必然给出同一个结果。

    拒绝口径与 `POST /fill` 完全一致（无方案/未确认 → 409、无可切分章节 → 422、
    字数超范围或分摊不成立 → 422），这样用户在弹窗里就能被拦住，不必先点确认再吃一次错。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    rows = section_repository.list_for_plan(plan["id"])
    ensure_sections_exist(rows)

    target_length, lengths = plan_lengths(payload or FillRequest(), plan, rows)
    items = [
        FillAllocationItem(
            seq=int(row["seq"]),
            title=str(row["title"]),
            target_length=lengths[int(row["seq"])],
        )
        for row in rows
    ]
    return FillAllocationResponse(
        plan_id=plan["id"], target_length=target_length, items=items, total=len(items)
    )


@router.post("/{task_id}/sections/{seq}/references", response_model=SectionReferencesResponse)
def preview_references(
    task_id: int,
    seq: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    retrieval: RetrievalServiceDep,
) -> SectionReferencesResponse:
    """给一章算一份「可用引用片段」预览（工单 24）：**只读不改库**。

    用户写这一章之前，先看到将注入哪些资料片段（默认全选、可逐条取消），
    再决定要不要**真的**用它们。检索不可用不报错：返回空卡片 + 检索状态，界面据此
    明示「本次未使用知识库」，填充照常可进行。

    闸门与 `POST /sections/{seq}/fill` 一致（方案已确认、无未处置待确认事项）。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )
    rows = section_repository.list_for_plan(plan["id"])
    ensure_sections_exist(rows)

    cards, status_payload = preview_section_references(
        rows=rows, seq=seq, retrieval=retrieval
    )
    return SectionReferencesResponse(
        task_id=task_id, seq=seq, cards=cards, retrieval_status=status_payload
    )


@router.post("/{task_id}/sections/{seq}/fill", response_model=SectionWriteResponse)
def fill_section(
    task_id: int,
    seq: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    fill_repository: FillTaskRepositoryDep,
    template_repository: TemplateRepositoryDep,
    generation_repository: GenerationRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
    data_dir: DataDirDep,
    templates_dir: TemplatesDirDep,
    payload: SectionFillRequest | None = None,
) -> SectionWriteResponse:
    """写**一章**正文（工单 10 / 24），随即拼装出含真实段落与小标题的 .docx 成品。

    闸门与 `/fill` 完全一致（方案已确认、无未处置待确认事项）：填充是唯一会调模型的
    写作环节，闸门一旦失守，模型就会替未定内容写正文。

    `payload.reference_cards`（工单 24）是本用户保留的引用片段：只注入 `adopted=True`
    的，并在正文写成功后把这些实际采用的片段落库供成品拼参考资料。

    失败口径：
    - 章节不存在 → 404；已完成不重复写 → 409；没有进行中的填充任务 → 409；
    - 模型调用失败 → 502（章节已标「失败」、不产出成品文件）。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    task = task_repository.get(task_id) or {}
    client, model_name = model_for_task(task, provider_repository, model_client)

    try:
        outcome = write_section(
            task_id=task_id,
            plan=plan,
            seq=seq,
            model_client=client,
            model_name=model_name,
            section_repository=section_repository,
            fill_repository=fill_repository,
            template_repository=template_repository,
            generation_repository=generation_repository,
            data_dir=data_dir,
            templates_dir=templates_dir,
            reference_cards=(payload or SectionFillRequest()).reference_cards,
        )
    except ModelCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"第 {seq} 章生成失败：{exc}",
        ) from exc

    return SectionWriteResponse(
        task_id=task_id,
        fill_id=outcome["fill_id"],
        section=outcome["section"],
        deliverable=outcome["deliverable"],
    )


@router.post("/{task_id}/fill/run", response_model=SerialFillResponse)
def run_fill(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    fill_repository: FillTaskRepositoryDep,
    template_repository: TemplateRepositoryDep,
    generation_repository: GenerationRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
    data_dir: DataDirDep,
    templates_dir: TemplatesDirDep,
) -> SerialFillResponse:
    """把剩余章节**逐章串行**写完（工单 11），全部写完后整体拼装正文成品。

    闸门与 `/fill`、`/sections/{seq}/fill` 完全一致：填充是唯一会调模型的写作环节，
    闸门一旦失守，模型就会替未定内容写正文。

    失败口径：
    - 没有进行中的填充任务 → 409；方案无可填充章节 → 422；
    - 任一章模型调用失败 → 502，报错指明是第几章；**不产出残缺成品**，
      已写成的章保留，填充任务标「失败」并留痕。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    task = task_repository.get(task_id) or {}
    client, model_name = model_for_task(task, provider_repository, model_client)

    outcome = run_serial_fill(
        task_id=task_id,
        plan=plan,
        model_client=client,
        model_name=model_name,
        section_repository=section_repository,
        fill_repository=fill_repository,
        template_repository=template_repository,
        generation_repository=generation_repository,
        data_dir=data_dir,
        templates_dir=templates_dir,
    )

    fill = outcome["fill"]
    items = to_section_items(outcome["sections"])
    total = len(items)
    completed = int(fill["completed_sections"])
    deviation = outcome["deviation"]
    return SerialFillResponse(
        task_id=task_id,
        fill_id=fill["id"],
        status=fill["status"],
        status_label=FILL_STATUS_LABELS.get(fill["status"], fill["status"]),
        completed_sections=completed,
        total_sections=total,
        progress_label=f"第 {completed} / {total} 章",
        items=items,
        total=total,
        deliverable=outcome["deliverable"],
        # 字数偏差（工单 16）：实际与目标都由后端按唯一计量入口算，前端不重算。
        target_length=deviation.target_length,
        actual_length=deviation.actual_length,
        deviation_ratio=round(deviation.ratio, 4),
        deviation_note=deviation.note,
    )


@router.post("/{task_id}/fill/cancel", response_model=SerialFillResponse)
def cancel_fill(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    fill_repository: FillTaskRepositoryDep,
) -> SerialFillResponse:
    """请求中断一次进行中的填充（工单 13）。

    **中断发生在章节边界上**，不是在这次请求里立刻生效：正在写的那一章必须写完
    才能停，写到一半停下会在库里留下半章正文。所以这里只置标记并返回当前进度，
    真正的 `cancelled` 由串行循环在下一个章节边界写入。

    - 没有进行中的填充任务 → 409（没什么可中断的）；
    - 中断**不产生成品文件**：还没写完整篇，此时出成品等于交一份半成品。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    active = fill_repository.active_for_task(task_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务 {task_id} 没有进行中的填充任务，无法中断",
        )

    fill_repository.request_cancel(active["id"])
    fill = fill_repository.get(active["id"]) or active
    rows = section_repository.list_for_plan(plan["id"])
    items = to_section_items(rows)
    total = len(items)
    completed = sum(1 for row in rows if row["status"] == "completed")
    deviation = measure(rows, int(fill["target_length"]))
    return SerialFillResponse(
        task_id=task_id,
        fill_id=fill["id"],
        status=fill["status"],
        status_label=FILL_STATUS_LABELS.get(fill["status"], fill["status"]),
        completed_sections=completed,
        total_sections=total,
        progress_label=f"第 {completed} / {total} 章",
        items=items,
        total=total,
        # 中断不出成品：还没写完整篇。
        deliverable=None,
        # 中断时也报当前偏差：用户要知道「停下来时已经写了多少」，好判断要不要续写。
        target_length=deviation.target_length,
        actual_length=deviation.actual_length,
        deviation_ratio=round(deviation.ratio, 4),
        deviation_note=None,
    )


@router.post(
    "/{task_id}/sections/{seq}/rewrite", response_model=SectionRewriteResponse
)
def rewrite_task_section(
    task_id: int,
    seq: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    template_repository: TemplateRepositoryDep,
    generation_repository: GenerationRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
    data_dir: DataDirDep,
    templates_dir: TemplatesDirDep,
    payload: SectionFillRequest | None = None,
) -> SectionRewriteResponse:
    """只重写一章正文并重新拼装成品（工单 14 / 24）。

    与 `/sections/{seq}/fill` 的差别：后者对已完成的章是 409（不许悄悄覆盖），
    本端点正是为「用户明确要求换掉这一章」而存在。

    `payload.reference_cards`（工单 24）与单章填充同口径：只用用户保留的片段，
    并更新这一章落库的参考资料。

    - 章节不存在 → 404；章**还没写过**（pending）→ 409，那是正常填充的活儿；
    - 模型调用失败 → 502，**旧正文保留**（重写失败不该把已写好的一章弄丢）；
    - 其余章节一个字不动；成品重新拼装成同一份（旧正文成品记录与文件清理掉，
      大纲导出不动）。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="fill"
    )

    task = task_repository.get(task_id) or {}
    client, model_name = model_for_task(task, provider_repository, model_client)

    outcome = rewrite_section(
        task_id=task_id,
        plan=plan,
        seq=seq,
        model_client=client,
        model_name=model_name,
        section_repository=section_repository,
        template_repository=template_repository,
        generation_repository=generation_repository,
        data_dir=data_dir,
        templates_dir=templates_dir,
        reference_cards=(payload or SectionFillRequest()).reference_cards,
    )

    return SectionRewriteResponse(
        task_id=task_id,
        section=outcome["section"],
        deliverable=outcome["deliverable"],
    )
