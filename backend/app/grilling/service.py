"""拷问流程的应用编排（把状态机接进 API 层）。

职责边界：路由负责校验与响应组织；本模块负责「一次请求推进一轮」的编排——
落种子输入、从消息表复原历轮问答、跑图、把图结果组装成轮次模型；收敛时生成结构化方案草稿。

轮次复原只从规格 §4 的 `messages` 表来（`rounds_from_messages`），
**不引入第二套隐藏状态存储**：图内的 `rounds` / `determined` 都在请求内由消息派生。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.message_repository import MessageRepository
from app.db.open_item_repository import OpenItemRepository
from app.db.plan_repository import PlanRepository
from app.db.plan_revision_repository import PlanRevisionRepository
from app.grilling.frontier import FrontierParseError, frontier_from_content
from app.grilling.graph import build_grilling_graph, derive_determined
from app.grilling.prompts import render_plan_messages, render_revision_messages
from app.grilling.retrieval import rejected_chunk_ids
from app.grilling.revision import compute_changes
from app.models.grilling import Dialogue, DialogueMessage, FrontierQuestion, FrontierRound
from app.models.plan import Plan, PlanRevision
from app.providers.model_client import ModelClient, complete_text

# 种子输入（用户最初的一句话 / 一段描述）记为第 0 轮，使对话流可从头复原。
SEED_ROUND_NO = 0
# 前沿问题从第 1 轮开始。
FIRST_ROUND_NO = 1


class AdvanceError(ValueError):
    """无法推进：没有可据以重算的上一轮问答。"""


class PlanGenerationError(ValueError):
    """方案生成失败：模型未返回可用的方案内容。"""


class PlanRevisionError(ValueError):
    """无法修订：该任务尚无已生成的结构化方案。"""


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


def accepted_citations(messages: list[dict]) -> list[dict]:
    """读出最近一轮**用户已采用**的引用片段（工单 23）。

    做法：取最新一轮 assistant 消息里的 `citations`（那是当时给出的卡片），
    再剔除用户在提交回答时取消掉的 chunk_id。用户没勾掉的默认采用——
    「默认全选」这条规格要求落在这里，而不是在前端的复选框初始值上。
    """
    rejected = rejected_chunk_ids(messages)
    latest: list[dict] = []
    for message in messages:
        if message["role"] != "assistant":
            continue
        try:
            frontier = frontier_from_content(message["content"])
        except FrontierParseError:
            continue
        collected: list[dict] = []
        for question in frontier:
            for citation in question.citations:
                collected.append(citation.model_dump())
        if collected:
            latest = collected

    return [
        citation
        for citation in latest
        if int(citation.get("chunk_id", -1)) not in rejected
        and citation.get("adopted", True)
    ]


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
    determined: list[str] | None = None,
    open_items: list[str] | None = None,
    model_name: str | None = None,
) -> str:
    """收敛后生成结构化方案正文（Markdown）；章节随任务类型裁剪。

    `determined`（已定决策）与 `open_items`（未定待确认事项）分列喂进提示词：
    未定的推测只能落在方案「待确认事项」一节，绝不写成已定需求。
    """
    messages = render_plan_messages(known_input, rounds, determined, open_items)
    content = complete_text(model_client, messages, model=model_name).strip()
    if not content:
        raise PlanGenerationError("模型未返回方案内容")
    return content


def start_first_round(
    *,
    task_id: int,
    idea: str,
    message_repository: MessageRepository,
    open_item_repository: OpenItemRepository,
    model_client: ModelClient,
    model_name: str | None = None,
    retrieval=None,
) -> FrontierRound:
    """发起主题创作的第一轮：落种子输入 → 跑状态机 → 返回前沿问题集。

    `retrieval`（工单 23）为 None 时不检索：没有知识库也能正常拷问，
    引用卡片为空即可——这不是特例分支，而是「知识库可选」的正常形态。
    """
    message_repository.append(task_id, SEED_ROUND_NO, "user", idea)

    graph = build_grilling_graph(
        model_client, message_repository, model_name=model_name, retrieval=retrieval
    )
    state = graph.invoke(
        {
            "task_id": task_id,
            "known_input": idea,
            "round_no": FIRST_ROUND_NO,
            "rounds": [],
            "open_items": open_item_repository.open_texts(task_id),
        }
    )

    frontier = [FrontierQuestion(**item) for item in state.get("frontier", [])]
    return FrontierRound(round_no=FIRST_ROUND_NO, frontier=frontier, answers=[])


def advance_round(
    *,
    task_id: int,
    message_repository: MessageRepository,
    open_item_repository: OpenItemRepository,
    model_client: ModelClient,
    plan_repository: PlanRepository,
    model_name: str | None = None,
    retrieval=None,
) -> AdvanceOutcome:
    """按上一轮回答重算下一轮前沿；前沿为空即收敛，并生成结构化方案草稿。

    方案由**触发收敛的那一轮**（最后一轮问答）产生，故 `round_no` 记最后一轮。

    **该任务尚无任何轮次时**（典型：首轮提问因模型不可用而 502，任务与种子输入留在库里）
    不返回 422，而是走**等价于发起第一轮**的路径：让 `derive_resume` 给出的
    `awaiting="advance"` 成为真话，首轮失败的任务因此自动可恢复（TB-10 遗留 a）。
    若此时模型也未提出任何问题（前沿为空），则按「前沿为空即收敛」产出草稿方案，
    方案记由种子输入（第 0 轮）产生——绝不让用户停在一个没有出路的「继续」上。
    """
    messages = message_repository.list_for_task(task_id)
    rounds = rounds_from_messages(messages)
    known_input = _seed_input(messages)
    open_items = open_item_repository.open_texts(task_id)
    # 上一轮用户勾选保留的引用（工单 23）：取消过的不再进提示词。
    citations = accepted_citations(messages)
    graph = build_grilling_graph(
        model_client, message_repository, model_name=model_name, retrieval=retrieval
    )

    if not rounds:
        return _advance_without_rounds(
            task_id=task_id,
            known_input=known_input,
            open_items=open_items,
            graph=graph,
            model_client=model_client,
            plan_repository=plan_repository,
            model_name=model_name,
            citations=citations,
        )

    last_round_no = rounds[-1]["round_no"]
    next_round_no = last_round_no + 1

    state = graph.invoke(
        {
            "task_id": task_id,
            "known_input": known_input,
            "round_no": next_round_no,
            "rounds": rounds,
            "open_items": open_items,
            "citations": citations,
        }
    )

    if state.get("frontier"):
        frontier = [FrontierQuestion(**item) for item in state["frontier"]]
        return AdvanceOutcome(
            next_round=FrontierRound(round_no=next_round_no, frontier=frontier, answers=[]),
            plan=None,
        )

    content_md = generate_plan(
        known_input,
        rounds,
        model_client=model_client,
        determined=state.get("determined", []),
        open_items=open_items,
        model_name=model_name,
    )
    record = plan_repository.create(task_id, content_md, round_no=last_round_no)
    return AdvanceOutcome(next_round=None, plan=Plan(**record))


def _advance_without_rounds(
    *,
    task_id: int,
    known_input: str,
    open_items: list[str],
    graph,
    model_client: ModelClient,
    plan_repository: PlanRepository,
    model_name: str | None,
    citations: list[dict] | None = None,
) -> AdvanceOutcome:
    """尚无任何轮次时的推进：等价于「发起第一轮」。

    种子输入（用户最初给的一句话 / 一段描述）已落库，故这里只跑状态机、不重复落种子。
    没有任何输入的任务（例如直接建的空任务）仍抛 `AdvanceError`（422）：没有可据以提问的内容。
    """
    if not known_input.strip():
        raise AdvanceError("尚无已作答的轮次，也没有种子输入可据以提问")

    state = graph.invoke(
        {
            "task_id": task_id,
            "known_input": known_input,
            "round_no": FIRST_ROUND_NO,
            "rounds": [],
            "open_items": open_items,
            "citations": citations or [],
        }
    )

    if state.get("frontier"):
        frontier = [FrontierQuestion(**item) for item in state["frontier"]]
        return AdvanceOutcome(
            next_round=FrontierRound(round_no=FIRST_ROUND_NO, frontier=frontier, answers=[]),
            plan=None,
        )

    content_md = generate_plan(
        known_input,
        [],
        model_client=model_client,
        determined=state.get("determined", []),
        open_items=open_items,
        model_name=model_name,
    )
    record = plan_repository.create(task_id, content_md, round_no=SEED_ROUND_NO)
    return AdvanceOutcome(next_round=None, plan=Plan(**record))


@dataclass(frozen=True)
class RevisionOutcome:
    """一次对话式修订的结果：更新后的方案 + 本次修订的版本记录。"""

    plan: Plan
    revision: PlanRevision


def revise_plan(
    *,
    task_id: int,
    instruction: str,
    message_repository: MessageRepository,
    open_item_repository: OpenItemRepository,
    plan_repository: PlanRepository,
    revision_repository: PlanRevisionRepository,
    model_client: ModelClient,
    model_name: str | None = None,
) -> RevisionOutcome:
    """对已生成方案继续对话：按用户修订指令更新方案正文，并留痕旧版本。

    步骤：取当前方案正文 → 渲染修订提示词（当前方案 + 指令 + 已定 + 未定）→ 模型返回新正文
    → 计算差异提示 → 就地更新方案（置回 draft）→ 追加一条版本记录（修订前 / 修订后 / 时间）。
    """
    current = plan_repository.get_current(task_id)
    if current is None:
        raise PlanRevisionError(f"任务 {task_id} 尚无结构化方案，无法修订")

    messages = message_repository.list_for_task(task_id)
    rounds = rounds_from_messages(messages)

    prompt = render_revision_messages(
        current["content_md"],
        instruction,
        _seed_input(messages),
        rounds,
        derive_determined(rounds),
        open_item_repository.open_texts(task_id),
    )
    content_md = complete_text(model_client, prompt, model=model_name).strip()
    if not content_md:
        raise PlanGenerationError("模型未返回修订后的方案内容")

    changes = compute_changes(current["content_md"], content_md)
    updated = plan_repository.update_content(current["id"], content_md)
    if updated is None:
        raise PlanRevisionError(f"方案 {current['id']} 不存在，无法修订")

    revision = revision_repository.create(
        current["id"],
        task_id,
        instruction,
        current["content_md"],
        content_md,
        changes,
    )
    return RevisionOutcome(plan=Plan(**updated), revision=PlanRevision(**revision))