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
    PlanRepositoryDep,
    ProviderRepositoryDep,
    TaskRepositoryDep,
)
from app.db.task_repository import TaskRepository
from app.grilling.frontier import FrontierParseError
from app.grilling.service import (
    AdvanceError,
    PlanGenerationError,
    advance_round,
    build_dialogue,
    frontier_for_round,
    start_first_round,
)
from app.models.grilling import (
    AdvanceResponse,
    AnswerSubmitRequest,
    Dialogue,
    GrillingStartRequest,
    GrillingStartResponse,
)
from app.models.plan import Plan
from app.models.task import Task

router = APIRouter(prefix="/grilling", tags=["grilling"])

# 任务标题取种子输入首行、截断，供历史列表显示可读标签。
TITLE_MAX_LENGTH = 60


def _derive_title(idea: str) -> str:
    """从一句话 / 一段描述派生任务标题（首行截断）。"""
    first_line = idea.strip().splitlines()[0] if idea.strip() else ""
    return first_line[:TITLE_MAX_LENGTH]


def _require_task(task_repository: TaskRepository, task_id: int) -> None:
    """任务不存在时抛 404。"""
    if task_repository.get(task_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )


@router.post(
    "/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=GrillingStartResponse,
)
def start_grilling_task(
    payload: GrillingStartRequest,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
) -> GrillingStartResponse:
    """从一句话 / 一段描述发起主题创作，产出第一轮前沿问题集。"""
    task_record = task_repository.create("creation", _derive_title(payload.idea))

    default_provider = provider_repository.get_default()
    model_name = default_provider["model_name"] if default_provider else None

    try:
        frontier_round = start_first_round(
            task_id=task_record["id"],
            idea=payload.idea,
            message_repository=message_repository,
            model_client=model_client,
            model_name=model_name,
        )
    except FrontierParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型输出无法解析为前沿问题：{exc}",
        ) from exc

    return GrillingStartResponse(task=Task(**task_record), round=frontier_round)


@router.post("/tasks/{task_id}/answers", response_model=Dialogue)
def submit_answers(
    task_id: int,
    payload: AnswerSubmitRequest,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
) -> Dialogue:
    """把某轮的用户回答写入消息表，返回写后的对话状态。"""
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

    for answer in payload.answers:
        message_repository.append(task_id, payload.round_no, "user", answer)

    return build_dialogue(task_id, message_repository.list_for_task(task_id))


@router.post("/tasks/{task_id}/advance", response_model=AdvanceResponse)
def advance(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    plan_repository: PlanRepositoryDep,
    provider_repository: ProviderRepositoryDep,
    model_client: ModelClientDep,
) -> AdvanceResponse:
    """按上一轮回答重算下一轮前沿；前沿为空即收敛并生成结构化方案草稿。"""
    _require_task(task_repository, task_id)

    default_provider = provider_repository.get_default()
    model_name = default_provider["model_name"] if default_provider else None

    try:
        outcome = advance_round(
            task_id=task_id,
            message_repository=message_repository,
            model_client=model_client,
            plan_repository=plan_repository,
            model_name=model_name,
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
) -> Plan:
    """方案确认：draft → confirmed 并记录 `confirmed_at`（进入生成阶段的唯一闸门）。"""
    _require_task(task_repository, task_id)

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
    return Plan(**confirmed)


@router.get("/tasks/{task_id}/dialogue", response_model=Dialogue)
def get_dialogue(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
) -> Dialogue:
    """读取某任务的对话 / 轮次，供前端渲染对话流。"""
    _require_task(task_repository, task_id)
    return build_dialogue(task_id, message_repository.list_for_task(task_id))