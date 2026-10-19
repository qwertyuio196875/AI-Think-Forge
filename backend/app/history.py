"""续作状态推导：把「打开详情」变成「知道该从哪儿继续」。

术语（GLOSSARY）**任务**：一次主题创作或资料分析的实例，状态、对话、方案、成品持久保存，
可中断后继续。因此详情页必须能回答两件事：**停在哪儿**（哪一轮待作答）与**下一步做什么**。

纪律：推导只依据规格 §4 已持久化的数据（任务的 status、`messages` 复原出的轮次、
`plans.status`），**不新建任何状态**——重启后同一份数据必然推导出同一个结论。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.grilling import FrontierRound
from app.models.history import ResumeNext

# 仅种子输入、尚无轮次时的「已发生轮次」记 0（种子输入记为第 0 轮，见 app.grilling.service）。
SEED_ROUND_NO = 0


@dataclass(frozen=True)
class ResumeState:
    """续作状态：已发生的最后轮次、待作答轮次（若有）、下一步动作。"""

    last_round_no: int
    pending_round: FrontierRound | None
    awaiting: ResumeNext


def _pending_round(rounds: list[FrontierRound]) -> FrontierRound | None:
    """第一个「前沿已提出但尚未答完」的轮次；没有则 None。

    这就是「停在拷问中途」的形态：用户关掉系统时该轮问题还在屏幕上、还没答完，
    重开后回到这一轮继续作答即可（回答按位落库，不产生半轮垃圾数据）。
    """
    for round_ in rounds:
        if len(round_.answers) < len(round_.frontier):
            return round_
    return None


def derive_resume(
    *,
    task_status: str,
    rounds: list[FrontierRound],
    plan: dict | None,
) -> ResumeState:
    """按已持久化状态推导「停在哪儿 + 下一步做什么」。"""
    pending = _pending_round(rounds)
    last_round_no = rounds[-1].round_no if rounds else SEED_ROUND_NO

    if task_status == "deleted":
        awaiting = ResumeNext.deleted
    elif task_status == "completed":
        awaiting = ResumeNext.completed
    elif pending is not None:
        awaiting = ResumeNext.answers
    elif plan is None:
        awaiting = ResumeNext.advance
    elif plan["status"] == "draft":
        awaiting = ResumeNext.plan_confirm
    else:
        awaiting = ResumeNext.generation

    return ResumeState(last_round_no=last_round_no, pending_round=pending, awaiting=awaiting)