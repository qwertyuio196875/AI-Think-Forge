"""拷问的 LangGraph 状态机（规格 §2：拷问流程用 LangGraph）。

本单落地**最小节点图**，一次 `invoke` 推进一轮：

    分析输入 → 生成前沿问题 →（有前沿）落库并返回 /（前沿为空）收敛停止

扩展点（供 TB-3 多轮重算 / TB-4 修订）：
- `analyze_input` 将扩展为识别目标 / 背景 / 约束 / 已知信息，并纳入历轮消息；
- `generate_frontier` 将基于「已确定决策 + 历轮问答」重算前沿。

状态存储纪律：轮次与消息的持久化只走规格 §4 的 SQLite `messages` 表，图内状态是
请求内的临时值，**不引入第二套隐藏状态存储**。
"""

from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.db.message_repository import MessageRepository
from app.grilling.frontier import parse_frontier
from app.grilling.prompts import render_frontier_messages
from app.providers.model_client import ModelClient


class GrillingState(TypedDict, total=False):
    """一次请求内推进一轮所需的最小状态。"""

    task_id: int
    known_input: str
    round_no: int
    frontier: list[dict]
    frontier_empty: bool


def build_grilling_graph(
    model_client: ModelClient,
    message_repository: MessageRepository,
    *,
    model_name: str | None = None,
):
    """构建并编译拷问最小节点图（依赖以闭包注入，路由按请求构造）。"""

    def analyze_input(state: GrillingState) -> GrillingState:
        """分析输入：归一用户已知信息（TB-3 将扩展为结构化识别）。"""
        return {"known_input": state["known_input"].strip()}

    def generate_frontier(state: GrillingState) -> GrillingState:
        """生成前沿问题：把已知信息喂进提示词，经模型客户端取得问题集。"""
        messages = render_frontier_messages(state["known_input"])
        raw = model_client.complete(messages, model=model_name)
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