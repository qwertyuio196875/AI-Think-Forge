"""拷问的 LangGraph 状态机（规格 §2：拷问流程用 LangGraph）。

一次 `invoke` 推进一轮：

    分析输入 → 生成前沿问题 →（有前沿）落库并返回 /（前沿为空）收敛停止

TB-3 扩展（工单 12）：
- `analyze_input` 归一已知信息，并把**历轮问答**解析为**已确定决策**；
- `generate_frontier` 基于「已知信息 + 已确定决策 + 历轮问答」重算前沿——
  每轮问题集随上一轮回答变化，而不是固定问题集。

状态存储纪律：轮次与消息的持久化只走规格 §4 的 SQLite `messages` 表，
`rounds` / `determined` 都是请求内由消息复原的临时值，**不引入第二套隐藏状态存储**。

工单 23 扩展（ADR-0005）：前沿问题生成后先判定「哪些需要外部依据」，只对事实型问题
检索知识库，并把引用挂到问题上。判定规则在 `fact_check_v1.md` 资产里，不在代码里。
检索不可用不阻断拷问——`retrieval_status` 会明示「本次未使用知识库」。
"""

from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.db.message_repository import MessageRepository
from app.grilling.frontier import parse_frontier
from app.grilling.open_items import is_skip_answer
from app.grilling.prompts import render_frontier_messages
from app.grilling.retrieval import attach_citations, judge_questions
from app.providers.model_client import ModelClient, complete_text


class GrillingState(TypedDict, total=False):
    """一次请求内推进一轮所需的最小状态。"""

    task_id: int
    known_input: str
    round_no: int
    # 历轮问答：`[{"round_no", "frontier", "answers"}, ...]`，由消息表复原。
    rounds: list[dict]
    # 已确定决策（分析输入产出）：`["<问题标题> → <用户回答>", ...]`。
    determined: list[str]
    # 未定的待确认事项条目（跳过的问题），单列并不参与「已定」判定。
    open_items: list[str]
    # 本轮已采用的知识库引用（工单 23）：上一轮用户勾选保留的片段。
    citations: list[dict]
    frontier: list[dict]
    frontier_empty: bool


def knowledge_base_has_sources(retrieval) -> bool:
    """知识库里是否有已入库的资料（没有就完全跳过判定与检索）。

    为什么这条短路放在这里而不是让检索层「查了但没有结果」：判定本身要花一次模型
    调用。知识库空着的时候，这次调用必然得出「没资料」，是纯粹的浪费；而且它会让
    「没有知识库」这个正常状态在调用序列上留下痕迹，干扰所有不关心检索的路径。
    """
    store = getattr(retrieval, "_store", None)
    counter = getattr(store, "stored_source_count", None)
    if not callable(counter):
        return False
    try:
        return int(counter()) > 0
    except Exception:  # noqa: BLE001 - 计数失败按「没有资料」处理，不阻断拷问
        return False


def _normalize_rounds(rounds: list[dict]) -> list[dict]:
    """归一历轮问答：去掉回答两端空白，保持与问题一一对应的顺序。"""
    return [
        {
            "round_no": round_info["round_no"],
            "frontier": round_info.get("frontier", []),
            "answers": [answer.strip() for answer in round_info.get("answers", [])],
        }
        for round_info in rounds
    ]


def derive_determined(rounds: list[dict]) -> list[str]:
    """从历轮问答派生「已确定决策」清单（问题标题 → 用户回答）。

    被「暂时跳过」的作答**不算已定决策**：用户未回应不等于同意，它只进待确认事项。
    """
    determined: list[str] = []
    for round_info in rounds:
        answers = round_info.get("answers", [])
        for index, question in enumerate(round_info.get("frontier", [])):
            answer = answers[index] if index < len(answers) else None
            if answer and not is_skip_answer(answer):
                determined.append(f"{question['title']} → {answer}")
    return determined


def build_grilling_graph(
    model_client: ModelClient,
    message_repository: MessageRepository,
    *,
    model_name: str | None = None,
    retrieval=None,
):
    """构建并编译拷问最小节点图（依赖以闭包注入，路由按请求构造）。

    `retrieval` 是 `RetrievalService`（工单 23）；为 None 时不检索——引用卡片为空，
    拷问照常推进。测试与「知识库还没建」的场景都走这条路径，因此它不是特例分支，
    而是「没有知识库也能用」的正常形态。
    """

    def analyze_input(state: GrillingState) -> GrillingState:
        """分析输入：归一已知信息，把历轮问答解析为已确定决策，并保留未定项。"""
        rounds = _normalize_rounds(state.get("rounds", []))
        return {
            "known_input": state["known_input"].strip(),
            "rounds": rounds,
            "determined": derive_determined(rounds),
            "open_items": list(state.get("open_items", [])),
        }

    def generate_frontier(state: GrillingState) -> GrillingState:
        """生成前沿问题：把已知信息 + 已确定决策 + 未定 + 历轮问答喂进提示词重算。

        生成后立刻判断「哪些问题需要外部依据」，只对事实型问题检索（工单 23）。
        判定与检索都在这里做，因为它们是「出题」的一部分：出题时就该带上依据，
        等用户作答后再补资料已经晚了。

        **知识库为空时整段跳过**：既没有资料可检索，判定就没有意义，多调一次模型
        只是白花额度。这条短路不是性能优化而是语义正确——没有知识库时不该表现出
        任何检索迹象（引用卡片为空，也不该有「未使用知识库」的提示去打扰用户）。
        """
        messages = render_frontier_messages(
            state["known_input"],
            state.get("rounds", []),
            state.get("determined", []),
            state.get("open_items", []),
            state.get("citations", []),
        )
        raw = complete_text(model_client, messages, model=model_name)
        questions = parse_frontier(raw)
        payloads = [question.model_dump() for question in questions]

        if payloads and retrieval is not None and knowledge_base_has_sources(retrieval):
            checks = judge_questions(payloads, model_client=model_client, model_name=model_name)
            payloads = attach_citations(payloads, checks, retrieval=retrieval)

        return {
            "frontier": payloads,
            "frontier_empty": not questions,
        }

    def persist_round(state: GrillingState) -> GrillingState:
        """落库并返回：问题集以结构化 JSON 写入本轮 assistant 消息。"""
        content = json.dumps({"frontier": state["frontier"]}, ensure_ascii=False)
        message_repository.append(state["task_id"], state["round_no"], "assistant", content)
        return {}

    def has_frontier(state: GrillingState) -> str:
        """收敛判定：前沿为空即停止，不再提问。"""
        return "persist" if state.get("frontier") else "stop"

    graph = StateGraph(GrillingState)
    graph.add_node("analyze_input", analyze_input)
    graph.add_node("generate_frontier", generate_frontier)
    graph.add_node("persist_round", persist_round)
    graph.add_edge(START, "analyze_input")
    graph.add_edge("analyze_input", "generate_frontier")
    graph.add_conditional_edges(
        "generate_frontier", has_frontier, {"persist": "persist_round", "stop": END}
    )
    graph.add_edge("persist_round", END)
    return graph.compile()