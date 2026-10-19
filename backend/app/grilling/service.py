"""拷问流程的应用编排（把状态机接进 API 层）。

职责边界：路由负责校验与响应组织；本模块负责「一次请求推进一轮」的编排——
落种子输入、从消息表复原历轮问答、跑图、把图结果组装成轮次模型；收敛时生成结构化方案草稿。

轮次复原只从规格 §4 的 `messages` 表来（`rounds_from_messages`），
**不引入第二套隐藏状态存储**：图内的 `rounds` / `determined` 都在请求内由消息派生。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.message_repository import MessageRepository
from app.db.plan_repository import PlanRepository
from app.grilling.frontier import frontier_from_content
from app.grilling.graph import build_grilling_graph
from app.grilling.prompts import render_plan_messages
from app.models.grilling import Dialogue, DialogueMessage, FrontierQuestion, FrontierRound
from app.models.plan import Plan
from app.providers.model_client import ModelClient

# 种子输入（用户最初的一句话 / 一段描述）记为第 0 轮，使对话流可从头复原。
SEED_ROUND_NO = 0
# 前沿问题从第 1 轮开始。
FIRST_ROUND_NO = 1


class AdvanceError(ValueError):
    """无法推进：没有可据以重算的上一轮问答。"""


class PlanGenerationError(ValueError):
    """方案生成失败：模型未返回可用的方案内容。"""


@dataclass(frozen=True)
class AdvanceOutcome:
    """一次推进的结果：要么给出下一轮前沿，要么收敛并产出方案草稿。"""

    next_round: FrontierRound | None
    plan: Plan | None

    @property
    def converged(self) -> bool:
        """是否已收敛（无下一轮可问）。"""
        return self.next_round is None


def _seed_input(messages: list[dict]) -> str:
    """取第 0 轮的种子输入（用户最初提供的信息）。"""
    return next(
        (m["content"] for m in messages if m["round_no"] == SEED_ROUND_NO), ""
    )


def rounds_from_messages(messages: list[dict]) -> list[dict]:
    """从消息表复原历轮问答：`[{"round_no", "frontier", "answers"}, ...]`。

    frontier 取自该轮 assistant 消息（结构化 JSON），answers 取自该轮 user 消息（按序）。
    """
    grouped: dict[int, dict] = {}
    for message in messages:
        if message["round_no"] < FIRST_ROUND_NO:
            continue
        entry = grouped.setdefault(
            message["round_no"],
            {"round_no": message["round_no"], "frontier": [], "answers": []},
        )
        if message["role"] == "assistant":
            entry["frontier"] = [
                question.model_dump()
                for question in frontier_from_content(message["content"])
            ]
        elif message["role"] == "user":
            entry["answers"].append(message["content"])
    return [grouped[no] for no in sorted(grouped)]


def frontier_for_round(messages: list[dict], round_no: int) -> list[FrontierQuestion] | None:
    """取某轮 assistant 消息中的前沿问题集；该轮无提问则返回 None。"""
    for message in messages:
        if message["round_no"] == round_no and message["role"] == "assistant":
            return frontier_from_content(message["content"])
    return None


def build_dialogue(task_id: int, messages: list[dict]) -> Dialogue:
    """把消息流复原为「种子输入 + 各轮次 + 原始消息」。"""
    rounds = [
        FrontierRound(
            round_no=entry["round_no"],
            frontier=[FrontierQuestion(**item) for item in entry["frontier"]],
            answers=entry["answers"],
        )
        for entry in rounds_from_messages(messages)
    ]
    return Dialogue(
        task_id=task_id,
        seed_input=_seed_input(messages) if messages else None,
        rounds=rounds,
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


def generate_plan(
    known_input: str,
    rounds: list[dict],
    *,
    model_client: ModelClient,
    model_name: str | None = None,
) -> str:
    """收敛后生成结构化方案正文（Markdown）；章节随任务类型裁剪。"""
    messages = render_plan_messages(known_input, rounds)
    content = model_client.complete(messages, model=model_name).strip()
    if not content:
        raise PlanGenerationError("模型未返回方案内容")
    return content


def start_first_round(
    *,
    task_id: int,
    idea: str,
    message_repository: MessageRepository,
    model_client: ModelClient,
    model_name: str | None = None,
) -> FrontierRound:
    """发起主题创作的第一轮：落种子输入 → 跑状态机 → 返回前沿问题集。"""
    message_repository.append(task_id, SEED_ROUND_NO, "user", idea)

    graph = build_grilling_graph(model_client, message_repository, model_name=model_name)
    state = graph.invoke(
        {"task_id": task_id, "known_input": idea, "round_no": FIRST_ROUND_NO, "rounds": []}
    )

    frontier = [FrontierQuestion(**item) for item in state.get("frontier", [])]
    return FrontierRound(round_no=FIRST_ROUND_NO, frontier=frontier, answers=[])


def advance_round(
    *,
    task_id: int,
    message_repository: MessageRepository,
    model_client: ModelClient,
    plan_repository: PlanRepository,
    model_name: str | None = None,
) -> AdvanceOutcome:
    """按上一轮回答重算下一轮前沿；前沿为空即收敛，并生成结构化方案草稿。

    方案由**触发收敛的那一轮**（最后一轮问答）产生，故 `round_no` 记最后一轮。
    """
    messages = message_repository.list_for_task(task_id)
    rounds = rounds_from_messages(messages)
    if not rounds:
        raise AdvanceError("尚无已作答的轮次，无法推进")

    known_input = _seed_input(messages)
    last_round_no = rounds[-1]["round_no"]
    next_round_no = last_round_no + 1

    graph = build_grilling_graph(model_client, message_repository, model_name=model_name)
    state = graph.invoke(
        {
            "task_id": task_id,
            "known_input": known_input,
            "round_no": next_round_no,
            "rounds": rounds,
        }
    )

    if state.get("frontier"):
        frontier = [FrontierQuestion(**item) for item in state["frontier"]]
        return AdvanceOutcome(
            next_round=FrontierRound(round_no=next_round_no, frontier=frontier, answers=[]),
            plan=None,
        )

    content_md = generate_plan(
        known_input, rounds, model_client=model_client, model_name=model_name
    )
    record = plan_repository.create(task_id, content_md, round_no=last_round_no)
    return AdvanceOutcome(next_round=None, plan=Plan(**record))