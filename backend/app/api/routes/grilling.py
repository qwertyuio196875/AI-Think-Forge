"""拷问路由：发起第一轮、提交回答、推进轮次、读取方案、确认方案、读取对话。

沿用 `/api` 前缀与 `app/api/deps.py` 注入风格。路由只负责校验与响应组织：
- 状态机编排在 `app.grilling.service`（一次请求推进一轮 / 收敛即生成方案草稿）；
- 持久化只走规格 §4 的 `messages` 与 `plans` 表（LangGraph 不另立隐藏状态）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    MessageRepositoryDep,
    ModelClientDep,
    OpenItemRepositoryDep,
    PlanRepositoryDep,
    PlanRevisionRepositoryDep,
    PlanSectionRepositoryDep,
    ProviderRepositoryDep,
    RetrievalServiceDep,
    TaskRepositoryDep,
)
from app.api.errors import require_task
from app.db.provider_repository import ProviderRepository
from app.db.task_repository import TaskRepository
from app.grilling.frontier import FrontierParseError
from app.grilling.open_items import (
    SKIP_ANSWER_MARKER,
    is_skip_answer,
    skipped_items,
)
from app.grilling.retrieval import rejected_citations_content
from app.grilling.service import (
    AdvanceError,
    PlanGenerationError,
    PlanRevisionError,
    advance_round,
    build_dialogue,
    frontier_for_round,
    revise_plan,
    start_first_round,
)
from app.models.grilling import (
    AdvanceResponse,
    AnswerSubmitRequest,
    Dialogue,
    GrillingStartRequest,
    GrillingStartResponse,
)
from app.models.open_items import (
    OpenItem,
    OpenItemListResponse,
    OpenItemResolveRequest,
)
from app.models.plan import (
    Plan,
    PlanRevision,
    PlanRevisionListResponse,
    PlanRevisionRequest,
    PlanRevisionResponse,
)
from app.models.task import Task
from app.providers.model_client import ModelCallError
from app.sections.service import sync_plan_sections

router = APIRouter(prefix="/grilling", tags=["grilling"])

# 任务标题取种子输入首行、截断，供历史列表显示可读标签。
TITLE_MAX_LENGTH = 60
# 拒绝确认方案时，最多列出几项未处置的待确认事项（其余以省略号收束）。
MAX_LISTED_OPEN_ITEMS = 3


def _derive_title(idea: str) -> str:
    """从一句话 / 一段描述派生任务标题（首行截断）。"""
    first_line = idea.strip().splitlines()[0] if idea.strip() else ""
    return first_line[:TITLE_MAX_LENGTH]


def _require_task(task_repository: TaskRepository, task_id: int) -> dict:
    """任务不存在时抛 404（统一走 `app.api.errors.require_task`）。"""
    return require_task(task_repository, task_id)


def _model_for_task(
    task: dict, provider_repository: ProviderRepository, model_client
) -> tuple:
    """解析任务级模型覆盖：返回（客户端, model_name）。

    - 任务 pin 了 provider：客户端按其配置调用，`model_name` 取该 provider 的；
    - 未 pin：行为与既有实现一致（默认 provider 的 model_name）；
    - 测试注入的 fake 没有 `for_task` 时原样使用，保持既有接缝。
    """
    provider_id = task.get("provider_id")
    client = (
        model_client.for_task(provider_id)
        if hasattr(model_client, "for_task")
        else model_client
    )
    provider = (
        provider_repository.get_by_id(provider_id)
        if provider_id is not None
        else provider_repository.get_default()
    )
    return client, provider["model_name"] if provider is not None else None


@router.post(
    "/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=GrillingStartResponse,
)
def start_grilling_task(
    payload: GrillingStartRequest,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
    retrieval: RetrievalServiceDep,
) -> GrillingStartResponse:
    """从一句话 / 一段描述发起主题创作，产出第一轮前沿问题集。"""
    if (
        payload.provider_id is not None
        and provider_repository.get_by_id(payload.provider_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型配置 {payload.provider_id} 不存在，请重新选择",
        )

    task_record = task_repository.create(
        "creation", _derive_title(payload.idea), provider_id=payload.provider_id
    )

    client, model_name = _model_for_task(
        task_record, provider_repository, model_client
    )

    try:
        frontier_round = start_first_round(
            task_id=task_record["id"],
            idea=payload.idea,
            message_repository=message_repository,
            open_item_repository=open_item_repository,
            model_client=client,
            model_name=model_name,
            retrieval=retrieval,
        )
    except FrontierParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型输出无法解析为前沿问题：{exc}",
        ) from exc
    except ModelCallError as exc:
        # 调用失败：任务与种子输入已落库，用户可在模型恢复后重试（不丢任何数据）。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型调用失败：{exc}",
        ) from exc

    return GrillingStartResponse(task=Task.from_record(task_record), round=frontier_round)


@router.post("/tasks/{task_id}/answers", response_model=Dialogue)
def submit_answers(
    task_id: int,
    payload: AnswerSubmitRequest,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
) -> Dialogue:
    """把某轮的用户回答写入消息表，返回写后的对话状态。

    `answers` 里为 `null`（或纯空白）的项表示该问题被「**暂时跳过**」：
    它保持未定，作为待确认事项入清单（来源轮次 = 本轮），绝不当作已定需求。
    """
    _require_task(task_repository, task_id)

    messages = message_repository.list_for_task(task_id)
    frontier = frontier_for_round(messages, payload.round_no)
    if frontier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"轮次 {payload.round_no} 不存在或尚无前沿问题",
        )
    if len(frontier) != len(payload.answers):
        raise HTTPException(
            status_code=422,
            detail=(
                f"回答数量（{len(payload.answers)}）与前沿问题数量（{len(frontier)}）不一致"
            ),
        )

    for title in skipped_items(frontier, payload.answers):
        open_item_repository.create(task_id, payload.round_no, title)

    for answer in payload.answers:
        content = SKIP_ANSWER_MARKER if is_skip_answer(answer) else (answer or "").strip()
        message_repository.append(task_id, payload.round_no, "user", content)

    # 记录本轮取消采用的引用（工单 23）。存成一条 system 消息而不是新表：
    # 这是对话的一部分（「我这次不用这些资料」），与轮次同生命周期，
    # 而且下一轮渲染提示词时正好在同一条消息流里读到它。
    if payload.rejected_chunk_ids:
        message_repository.append(
            task_id,
            payload.round_no,
            "system",
            rejected_citations_content(payload.rejected_chunk_ids),
        )

    return build_dialogue(task_id, message_repository.list_for_task(task_id))


@router.post("/tasks/{task_id}/advance", response_model=AdvanceResponse)
def advance(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    plan_repository: PlanRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
    retrieval: RetrievalServiceDep,
) -> AdvanceResponse:
    """按上一轮回答重算下一轮前沿；前沿为空即收敛并生成结构化方案草稿。"""
    task = _require_task(task_repository, task_id)
    client, model_name = _model_for_task(task, provider_repository, model_client)

    try:
        outcome = advance_round(
            task_id=task_id,
            message_repository=message_repository,
            open_item_repository=open_item_repository,
            model_client=client,
            plan_repository=plan_repository,
            model_name=model_name,
            retrieval=retrieval,
        )
    except AdvanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FrontierParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型输出无法解析为前沿问题：{exc}",
        ) from exc
    except PlanGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"方案生成失败：{exc}"
        ) from exc
    except ModelCallError as exc:
        # 调用失败：已存对话与方案不受影响，可在模型恢复后重试。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型调用失败：{exc}",
        ) from exc

    return AdvanceResponse(
        task_id=task_id,
        converged=outcome.converged,
        next_round=outcome.next_round,
        plan=outcome.plan,
    )


@router.get("/tasks/{task_id}/plan", response_model=Plan)
def get_plan(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
) -> Plan:
    """读取某任务当前的结构化方案；尚无方案返回 404。"""
    _require_task(task_repository, task_id)

    record = plan_repository.get_current(task_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 尚无结构化方案"
        )
    return Plan(**record)


@router.post("/tasks/{task_id}/plan/confirm", response_model=Plan)
def confirm_plan(
    task_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
) -> Plan:
    """方案确认：draft → confirmed 并记录 `confirmed_at`（进入生成阶段的唯一闸门）。

    仍有未处置的待确认事项时拒绝确认（409）：原型语义是「待确认事项已全部定下，可以确认
    方案」，规格 US 9 也要求未经确认的推测不得当作已定需求；若在此放行，就会造出
    「方案已确认、却因仍有 open 条目而无法生成」的尴尬中间态。

    确认同时切出成品章节并落库（ADR-0006「确认后写入」）：章节清单从此成为填充、字数
    控制与页面规划共同依赖的唯一真源。方案里没有「章节」一节时切出空清单——**不报错**，
    因为旧格式方案确实可能没有这一节，此时填充入口自会按自己的闸门拒绝（工单 9）。
    """
    _require_task(task_repository, task_id)

    unresolved = open_item_repository.open_texts(task_id)
    if unresolved:
        preview = "、".join(unresolved[:MAX_LISTED_OPEN_ITEMS])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"仍有 {len(unresolved)} 项待确认事项未处置，无法确认方案"
                f"（未确认的推测不得当作已定需求）：{preview}"
                + ("…" if len(unresolved) > MAX_LISTED_OPEN_ITEMS else "")
                + "。请先在待确认事项里确认或搁置这些条目。"
            ),
        )

    current = plan_repository.get_current(task_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 尚无结构化方案"
        )

    confirmed = plan_repository.confirm(current["id"])
    if confirmed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"方案 {current['id']} 不存在"
        )

    # 用**已确认的行**切分（含 confirm 后的状态），避免拿确认前的快照做源。
    sync_plan_sections(
        task_id=task_id, plan=confirmed, section_repository=section_repository
    )
    return Plan(**confirmed)


# --- 方案对话式修订（工单 13）--------------------------------------------------


@router.post("/tasks/{task_id}/plan/revisions", response_model=PlanRevisionResponse)
def revise(
    task_id: int,
    payload: PlanRevisionRequest,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    plan_repository: PlanRepositoryDep,
    revision_repository: PlanRevisionRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
) -> PlanRevisionResponse:
    """对已生成方案继续对话 → 方案更新，并返回差异提示（哪些部分被改动）。

    旧版本留痕（修订前 / 修订后 / 时间）落在方案版本记录里；方案本体回到 draft，
    原确认不再覆盖新内容。

    修订可能增删章节或把章节改到别的标题下，所以同时按新正文**重新切分**章节
    （ADR-0006：修订后必须重切，否则下游会按过期目录填充）。重切规则是按标题匹配，
    匹配不上的旧章废弃重建；方案回到 draft 期间清单照旧可读，只是不再代表「已确认」。
    """
    task = require_task(task_repository, task_id)
    client, model_name = _model_for_task(task, provider_repository, model_client)

    try:
        outcome = revise_plan(
            task_id=task_id,
            instruction=payload.instruction,
            message_repository=message_repository,
            open_item_repository=open_item_repository,
            plan_repository=plan_repository,
            revision_repository=revision_repository,
            model_client=client,
            model_name=model_name,
        )
    except PlanRevisionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"方案修订失败：{exc}"
        ) from exc
    except ModelCallError as exc:
        # 调用失败：方案正文与版本记录未被改动，可在模型恢复后重试。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型调用失败：{exc}",
        ) from exc

    sync_plan_sections(
        task_id=task_id,
        plan=outcome.plan.model_dump(),
        section_repository=section_repository,
    )
    return PlanRevisionResponse(plan=outcome.plan, revision=outcome.revision)


@router.get("/tasks/{task_id}/plan/revisions", response_model=PlanRevisionListResponse)
def list_revisions(
    task_id: int,
    task_repository: TaskRepositoryDep,
    revision_repository: PlanRevisionRepositoryDep,
) -> PlanRevisionListResponse:
    """读取方案的修订历史（旧版本留痕，可逐条回查）。"""
    _require_task(task_repository, task_id)
    items = [
        PlanRevision(**record) for record in revision_repository.list_for_task(task_id)
    ]
    return PlanRevisionListResponse(items=items, total=len(items))


@router.get("/tasks/{task_id}/dialogue", response_model=Dialogue)
def get_dialogue(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
) -> Dialogue:
    """读取某任务的对话 / 轮次，供前端渲染对话流。"""
    _require_task(task_repository, task_id)
    return build_dialogue(task_id, message_repository.list_for_task(task_id))


# --- 待确认事项（工单 13）------------------------------------------------------


@router.get("/tasks/{task_id}/open-items", response_model=OpenItemListResponse)
def list_open_items(
    task_id: int,
    task_repository: TaskRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
) -> OpenItemListResponse:
    """读取某任务的待确认事项清单（术语「待确认事项」；未回应不等于同意）。"""
    _require_task(task_repository, task_id)
    items = [OpenItem(**record) for record in open_item_repository.list_for_task(task_id)]
    return OpenItemListResponse(items=items, total=len(items))


@router.post("/tasks/{task_id}/open-items/{item_id}/resolve", response_model=OpenItem)
def resolve_open_item(
    task_id: int,
    item_id: int,
    payload: OpenItemResolveRequest,
    task_repository: TaskRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
) -> OpenItem:
    """用户处置一条待确认事项：confirmed（承认成为已定需求）/ dismissed（认定不需要）。

    这是打开生成闸门所需的**用户确认动作**：open 的条目在处置前一律拦截生成。
    """
    _require_task(task_repository, task_id)

    item = open_item_repository.get(item_id)
    if item is None or item["task_id"] != task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"待确认事项 {item_id} 不存在"
        )
    resolved = open_item_repository.resolve(item_id, payload.status.value)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"待确认事项 {item_id} 不存在"
        )
    return OpenItem(**resolved)