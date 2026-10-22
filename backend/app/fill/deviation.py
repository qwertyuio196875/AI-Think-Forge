"""字数偏差的收尾校验与一次性补写（工单 16 / ADR-0006）。

规格（issue #2 §字数控制）原文：

> 生成时把「本章目标字数 + 剩余字数」作为上下文传给模型。
> 收尾校验：实际总字数与目标的偏差超过阈值（±15%）时，只对最短的那一章重生成一次；
> 重生成仍不达标则**明示偏差**，不静默接受。

本模块只做三件确定性的事，不调模型：

1. `measure()`：用唯一计量入口 `app.hanzi.count_hanzi` 数出「已写多少、还差多少」；
2. `pick_regeneration_target()`：挑出最短的那一章（并列时取序号最小的，避免随机性）；
3. `deviation_report()`：算出偏差比例并给出面向用户的说明。

**为什么重生成只做一次**：连写两遍还写不到目标，说明目标本身与这一章的内容体量不匹配
（或模型能力就到这儿）。再重试只会继续烧额度，用户看到的仍是同样的偏差——那时该说的
是「差多少」，把决定权交回用户（调字数、改要点、或接受现状）。

**为什么不补写（注水）**：把「还差 500 字」拆成额外段落塞进去，产出的是灌水正文。
规格明确禁止：「不为了凑字数注水」。所以补写走的是**重写整章**，而不是追加无意义段落。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.hanzi import count_hanzi

# ±15% 的偏差阈值（规格明文）。超过才重生成；恰好等于不算超过——边界上不额外烧额度。
DEVIATION_THRESHOLD = 0.15


@dataclass(frozen=True)
class Deviation:
    """一次填充的字数偏差快照。"""

    target_length: int
    actual_length: int

    @property
    def ratio(self) -> float:
        """偏差比例（实际相对目标）。目标为 0 时返回 0.0，避免除零。"""
        if self.target_length <= 0:
            return 0.0
        return (self.actual_length - self.target_length) / self.target_length

    @property
    def within_threshold(self) -> bool:
        """偏差是否在 ±15% 以内（含边界）。"""
        return abs(self.ratio) <= DEVIATION_THRESHOLD

    @property
    def note(self) -> str | None:
        """面向用户的偏差说明；在阈值内返回 None（不打扰）。"""
        if self.within_threshold:
            return None
        direction = "多" if self.ratio > 0 else "少"
        percent = abs(self.ratio) * 100
        return (
            f"全文实际 {self.actual_length} 字，目标 {self.target_length} 字，"
            f"{direction}了 {abs(self.actual_length - self.target_length)} 字"
            f"（{percent:.0f}%，超出 ±{DEVIATION_THRESHOLD * 100:.0f}%）。"
            "已对最短的一章重写过一次，仍未达到目标——请调整目标字数或补充该章要点。"
        )


def measure(rows: list[dict], target_length: int) -> Deviation:
    """数出全部章节的已写汉字数，返回偏差快照。"""
    actual = sum(count_hanzi(row.get("content_md") or "") for row in rows)
    return Deviation(target_length=target_length, actual_length=actual)


def remaining_length(rows: list[dict], target_length: int) -> int:
    """还剩多少字可写（不小于 0）：逐章喂给模型，避免总字数一路超出去。"""
    used = sum(count_hanzi(row.get("content_md") or "") for row in rows)
    return max(0, target_length - used)


def pick_regeneration_target(rows: list[dict]) -> dict | None:
    """挑出**最短**的那一章作为重生成目标；没有可写的章时返回 None。

    并列时取序号最小的那一章（`rows` 已按序号升序，`min` 稳定返回第一个）：
    否则同一份数据两次运行可能挑不同的章，用户会觉得系统在乱改。

    只考虑**已完成**的章：失败或待写的章本来就要写，不属于「重生成」。
    """
    completed = [row for row in rows if row.get("status") == "completed"]
    if not completed:
        return None
    return min(completed, key=lambda row: count_hanzi(row.get("content_md") or ""))
