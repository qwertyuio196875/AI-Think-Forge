"""拷问路由：发起主题创作的第一轮、提交回答、读取对话。

沿用 `/api` 前缀与 `app/api/deps.py` 注入风格。路由只负责校验与响应组织：
- 状态机编排在 `app.grilling.service`（一次请求推进一轮）；
- 持久化只走规格 §4 的 `messages` 表（LangGraph 不另立隐藏状态）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    MessageRepositoryDep,
    ModelClientDep,
    ProviderRepositoryDep,
    TaskRepositoryDep,
)
from app.grilling.frontier import FrontierParseError, frontier_from_content
from app.grilling.service import FIRST_ROUND_NO, SEED_ROUND_NO, start_first_round
from app.models.grilling import (
    AnswerSubmitRequest,
    Dialogue,
    DialogueMessage,
    FrontierQuestion,
    FrontierRound,
    GrillingStartRequest,
    GrillingStartResponse,
)
from app.models.task import Task

router = APIRouter(prefix="/grilling", tags=["grilling"])

# 任务标题取种子输入首行、截断，供历史列表显示可读标签。
TITLE_MAX_LENGTH = 60


def _derive_title(idea: str) -> str:
    """从一句话 / 一段描述派生任务标题（首行截断）。"""
    first_line = idea.strip().splitlines()[0] if idea.strip() else ""
    return first_line[:TITLE_MAX_LENGTH]


def _frontier_for_round(messages: list[dict], round_no: int) -> list[FrontierQuestion] | None:
    """取某轮 assistant 消息中的前沿问题集；该轮无提问则返回 None。"""
    for message in messages:
        if message["round_no"] == round_no and message["role"] == "assistant":
            return frontier_from_content(message["content"])
    return None


def _build_dialogue(task_id: int, messages: list[dict]) -> Dialogue:
    """把消息流复原为「种子输入 + 各轮次 + 原始消息」。"""
    seed_input = next(
        (m["content"] for m in messages if m["round_no"] == SEED_ROUND_NO), None
    )

    rounds: dict[int, FrontierRound] = {}
    for message in messages:
        if message["round_no"] < FIRST_ROUND_NO:
            continue
        frontier_round = rounds.setdefault(
            message["round_no"],
            FrontierRound(round_no=message["round_no"], frontier=[], answers=[]),
        )
        if message["role"] == "assistant":
            frontier_round.frontier = frontier_from_content(message["content"])
        elif message["role"] == "user":
            frontier_round.answers.append(message["content"])

    return Dialogue(
        task_id=task_id,
        seed_input=seed_input,
        rounds=[rounds[no] for no in sorted(rounds)],
        messages=[
            DialogueMessage(
                id=message["id"],
                round_no=message["round_no"],
                role=message["role"],
                content=message["content"],
                created_at=message["created_at"],
            )
            for message in messages
        ],
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
    if task_repository.get(task_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )

    messages = message_repository.list_for_task(task_id)
    frontier = _frontier_for_round(messages, payload.round_no)
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

    return _build_dialogue(task_id, message_repository.list_for_task(task_id))


@router.get("/tasks/{task_id}/dialogue", response_model=Dialogue)
def get_dialogue(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
) -> Dialogue:
    """读取某任务的对话 / 轮次，供前端渲染对话流。"""
    if task_repository.get(task_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )
    return _build_dialogue(task_id, message_repository.list_for_task(task_id))