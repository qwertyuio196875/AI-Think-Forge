"""拷问提示词资产：版本化加载与渲染。

设计要点（工单 11 / ADR-0001）：
- 提示词以**版本化资产**固化在 `grilling_v1.md`，代码只经 `GRILLING_PROMPT_VERSION`
  引用，规则不散落在多个文件里；
- 资产保留 MIT 署名（基于 Matt Pocock 的 grilling 技能规则适配），并显式记录移植偏离；
- 渲染函数把用户原始输入作为「已知信息」写进提示词——这一渲染可被测试断言，
  对应「不重复询问输入中已明确的信息」。

资产中的 `%%MAX_QUESTIONS%%` 占位在渲染时替换为 `MAX_FRONTIER_QUESTIONS`，
保证「每轮问题数上限」只有一个来源。
"""

from __future__ import annotations

from pathlib import Path

# 每轮问题数上限：对原规则的显式移植偏离（原规则未设上限）。
MAX_FRONTIER_QUESTIONS = 5

GRILLING_PROMPT_VERSION = "grilling-v1"

_ASSET_BY_VERSION = {GRILLING_PROMPT_VERSION: "grilling_v1.md"}

_MAX_QUESTIONS_TOKEN = "%%MAX_QUESTIONS%%"


def load_asset(version: str = GRILLING_PROMPT_VERSION) -> str:
    """读取指定版本的提示词资产原文（未替换占位）。"""
    filename = _ASSET_BY_VERSION.get(version)
    if filename is None:
        raise ValueError(f"未知的拷问提示词版本：{version}")
    return (Path(__file__).parent / filename).read_text(encoding="utf-8")


def render_frontier_messages(known_input: str) -> list[dict]:
    """渲染「生成前沿问题」的对话消息：系统规则 + 用户已知信息。

    用户原始输入以「已知信息」显式喂入，并要求不重复询问，从提示词层面消除
    「已提供却被再问」的问题。
    """
    system = load_asset().replace(_MAX_QUESTIONS_TOKEN, str(MAX_FRONTIER_QUESTIONS))
    user = (
        "## 已知信息（用户已提供，视为已确定，绝不再问）\n"
        f"{known_input}\n\n"
        "## 本轮任务\n"
        f"请基于以上已知信息，提出当前「前沿」的全部问题（1~{MAX_FRONTIER_QUESTIONS} 个，"
        "相互独立），每个问题给出推荐答案；严格按输出契约返回 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]