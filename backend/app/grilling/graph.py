"""拷问的 LangGraph 状态机（规格 §2：拷问流程用 LangGraph）。

一次 `invoke` 推进一轮：

    分析输入 → 生成前沿问题 →（有前沿）落库并返回 /（前沿为空）收敛停止

TB-3 扩展（工单 12）：
- `analyze_input` 归一已知信息，并把**历轮问答**解析为**已确定决策**；
- `generate_frontier` 基于「已知信息 + 已确定决策 + 历轮问答」重算前沿——
  每轮问题集随上一轮回答变化，而不是固定问题集。

状态存储纪律：轮次与消息的持久化只走规格 §4 的 SQLite `messages` 表，
`rounds` / `determined` 都是请求内由消息复原的临时值，**不引入第二套隐藏状态存储**。
"""

from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.db.message_repository import MessageRepository
from app.grilling.frontier import parse_frontier
from app.grilling.open_items import is_skip_answer
from app.grilling.prompts import render_frontier_messages
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
    frontier: list[dict]
    frontier_empty: bool


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
):
    """构建并编译拷问最小节点图（依赖以闭包注入，路由按请求构造）。"""

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
        """生成前沿问题：把已知信息 + 已确定决策 + 未定 + 历轮问答喂进提示词重算。"""
        messages = render_frontier_messages(
            state["known_input"],
            state.get("rounds", []),
            state.get("determined", []),
            state.get("open_items", []),
        )
        raw = complete_text(model_client, messages, model=model_name)
        questions = parse_frontier(raw)
        return {
            "frontier": [question.model_dump() for question in questions],
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