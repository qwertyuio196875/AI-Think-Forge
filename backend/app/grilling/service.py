"""拷问流程的应用编排（把状态机接进 API 层）。

职责边界：路由负责校验与响应组织；本模块负责「一次请求推进一轮」的编排——
落种子输入、跑图、把图结果组装成轮次模型。
"""

from __future__ import annotations

from app.db.message_repository import MessageRepository
from app.grilling.graph import build_grilling_graph
from app.models.grilling import FrontierQuestion, FrontierRound
from app.providers.model_client import ModelClient

# 种子输入（用户最初的一句话 / 一段描述）记为第 0 轮，使对话流可从头复原。
SEED_ROUND_NO = 0
# 前沿问题从第 1 轮开始。
FIRST_ROUND_NO = 1


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
        {"task_id": task_id, "known_input": idea, "round_no": FIRST_ROUND_NO}
    )

    frontier = [FrontierQuestion(**item) for item in state.get("frontier", [])]
    return FrontierRound(round_no=FIRST_ROUND_NO, frontier=frontier, answers=[])