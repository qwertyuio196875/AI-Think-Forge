"""待确认事项（open items）的纯逻辑：**暂时跳过**的判定与条目派生。

术语（GLOSSARY）：「待确认事项 = 系统标记的、尚未决定的关键信息清单。用户未回应不等于同意。」

「暂时跳过」是本应用对拷问规则的**扩展**（ADR-0001：偏离须显式记录）：
原规则只要求用户逐题作答；本应用允许用户把某个问题标记为跳过以示「现在不确定」，
被跳过的问题保持**未定**——进入待确认事项清单，绝不作为已定需求进入下游。

落库约定：
- 跳过的作答在 `messages` 表里以 `SKIP_ANSWER_MARKER` 占位，保持「问题 ↔ 回答」按位对齐
  （`rounds_from_messages` 依赖按位配对）；该标记既不是已定决策，也不参与下游判定。
- 每条待确认事项的 `text` 取被跳过问题的**标题**（正文已在历轮问答里可回指）。
"""

from __future__ import annotations

from app.models.grilling import FrontierQuestion

# 跳过占位：写入 `messages` 表的 user 消息内容（保证按位对齐）。
SKIP_ANSWER_MARKER = "（暂时跳过）"


def is_skip_answer(answer: str | None) -> bool:
    """该作答是否表示「暂时跳过」：未作答（None）、纯空白，或跳过占位。"""
    if answer is None:
        return True
    stripped = answer.strip()
    return not stripped or stripped == SKIP_ANSWER_MARKER


def skipped_items(frontier: list[FrontierQuestion], answers: list[str | None]) -> list[str]:
    """派生本轮进入待确认事项的条目（跳过问题的标题），按问题顺序。"""
    return [
        frontier[index].title
        for index, answer in enumerate(answers)
        if index < len(frontier) and is_skip_answer(answer)
    ]