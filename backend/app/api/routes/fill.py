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
    TaskRepositoryDep,
    TemplateRepositoryDep,
    TemplatesDirDep,
)
from app.api.gates import require_confirmed_plan
from app.fill.serial import run_serial_fill
from app.fill.service import start_fill
from app.fill.writer import write_section
from app.models.fill import (
    FILL_STATUS_LABELS,
    FillRequest,
    FillResponse,
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
) -> SectionWriteResponse:
    """写**一章**正文（工单 10），随即拼装出含真实段落与小标题的 .docx 成品。

    闸门与 `/fill` 完全一致（方案已确认、无未处置待确认事项）：填充是唯一会调模型的
    写作环节，闸门一旦失守，模型就会替未定内容写正文。

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
    )
