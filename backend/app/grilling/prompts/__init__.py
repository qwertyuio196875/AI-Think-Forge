"""拷问提示词资产：版本化加载与渲染。

设计要点（工单 11 / 12，ADR-0001）：
- 提示词以**版本化资产**固化在 `grilling_v1.md` / `plan_v1.md`，代码只经版本常量引用，
  规则不散落在多个文件里；
- 资产保留 MIT 署名（基于 Matt Pocock 的 grilling 技能规则适配），并显式记录移植偏离；
- 渲染函数把用户原始输入作为「已知信息」、把**历轮问答与已确定决策**一并喂进提示词：
  这是「下一轮问题按上一轮回答重算」而非固定问题集的依据，也可被测试断言。

资产中的 `%%MAX_QUESTIONS%%` 占位在渲染时替换为 `MAX_FRONTIER_QUESTIONS`，
保证「每轮问题数上限」只有一个来源。

历轮问答以 `rounds` 传入——结构为 `[{"round_no", "frontier", "answers"}, ...]`，
由 `app.grilling.service` 从规格 §4 的 `messages` 表复原，**不引入第二套隐藏状态存储**。
"""

from __future__ import annotations

from pathlib import Path

# 每轮问题数上限：对原规则的显式移植偏离（原规则未设上限）。
MAX_FRONTIER_QUESTIONS = 5

GRILLING_PROMPT_VERSION = "grilling-v1"
PLAN_PROMPT_VERSION = "plan-v1"

_ASSET_BY_VERSION = {
    GRILLING_PROMPT_VERSION: "grilling_v1.md",
    PLAN_PROMPT_VERSION: "plan_v1.md",
}

_MAX_QUESTIONS_TOKEN = "%%MAX_QUESTIONS%%"

_NO_HISTORY = "（暂无：这是第一轮）"


def load_asset(version: str = GRILLING_PROMPT_VERSION) -> str:
    """读取指定版本的提示词资产原文（未替换占位）。"""
    filename = _ASSET_BY_VERSION.get(version)
    if filename is None:
        raise ValueError(f"未知的提示词版本：{version}")
    return (Path(__file__).parent / filename).read_text(encoding="utf-8")


def _render_history(rounds: list[dict] | None) -> str:
    """把历轮问答渲染成可读文本（问题标题 → 用户回答）。"""
    if not rounds:
        return _NO_HISTORY

    blocks: list[str] = []
    for round_info in rounds:
        lines = [f"### 第 {round_info['round_no']} 轮"]
        answers = round_info.get("answers", [])
        for index, question in enumerate(round_info.get("frontier", [])):
            answer = answers[index] if index < len(answers) else "（未回答）"
            lines.append(f"- Q: {question['title']}　→　用户回答：{answer}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_frontier_messages(
    known_input: str,
    rounds: list[dict] | None = None,
    determined: list[str] | None = None,
) -> list[dict]:
    """渲染「生成前沿问题」的对话消息：系统规则 + 已知信息 + 历轮问答 + 已确定决策。

    已知信息、历轮问答与已确定决策都在提示词里显式给出并要求不重复询问，从提示词层面
    消除「已提供 / 已决定却被再问」的问题；历轮问答与已确定决策同时是
    「按上轮回答重算」的输入。
    """
    system = load_asset(GRILLING_PROMPT_VERSION).replace(
        _MAX_QUESTIONS_TOKEN, str(MAX_FRONTIER_QUESTIONS)
    )
    determined_block = "（暂无：这是第一轮）"
    if determined:
        determined_block = "\n".join(f"- {item}" for item in determined)
    user = (
        "## 已知信息（用户已提供，视为已确定，绝不再问）\n"
        f"{known_input}\n\n"
        "## 已确定决策（来自历轮问答，视为已定，绝不再问）\n"
        f"{determined_block}\n\n"
        "## 历轮问答（据此把前沿向外推）\n"
        f"{_render_history(rounds)}\n\n"
        "## 本轮任务\n"
        f"请基于以上已知信息与历轮问答，提出当前「前沿」的全部问题（1~{MAX_FRONTIER_QUESTIONS} 个，"
        "相互独立，且只问尚未解决的关键问题）；每个问题给出推荐答案；"
        "若关键问题都已解决，输出空前沿以收敛（不要为延续对话而提问）。严格按输出契约返回 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_plan_messages(known_input: str, rounds: list[dict] | None = None) -> list[dict]:
    """渲染「生成结构化方案」的对话消息：已知信息 + 全部历轮问答。

    方案在收敛时生成：章节随任务类型裁剪（结构灵活，不强求同一结构）；
    未经确认的推测只写进「待确认事项」，绝不写成已定需求。
    """
    system = load_asset(PLAN_PROMPT_VERSION)
    user = (
        "## 已知信息（用户最初提供的输入）\n"
        f"{known_input}\n\n"
        "## 全部历轮问答（已确定的决策）\n"
        f"{_render_history(rounds)}\n\n"
        "## 本轮任务\n"
        "请把以上共识整理为一份结构化的 Markdown 方案（直接输出 Markdown，不要输出 JSON）；"
        "章节按任务类型裁剪，未与用户确认的推测只放进「待确认事项」。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]