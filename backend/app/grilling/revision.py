"""方案修订的**差异提示**（哪些部分被改动）与会话式修订的纯逻辑。

术语（GLOSSARY）：「结构化方案 = 拷问收敛后的阶段性产物」「方案确认 = 用户显式批准」。
对话式修订只改方案文本，**不改已确认状态的含义**：内容一变，原确认不再覆盖新内容，
因此修订把方案置回草稿（由 `PlanRepository.update_content` 负责）。

差异粒度取 **Markdown 章节**（`#` 标题）：对用户而言「哪一节被改了」比字符级 diff 可读，
也正好对上工单 13「返回差异提示（哪些部分被改动）」。
"""

from __future__ import annotations

import re

# 差异提示里的改动类型。
CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"
CHANGE_MODIFIED = "modified"

# 无章节时的兜底标题（整篇即一节）。
WHOLE_DOCUMENT = "全文"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def sections(markdown: str) -> dict[str, str]:
    """把 Markdown 拆成「标题 → 正文」；标题文本不含 `#` 前缀。"""
    result: dict[str, str] = {}
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if heading is not None:
            result[heading] = "\n".join(buffer).strip()

    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            heading = match.group(2)
            buffer = []
        elif heading is not None:
            buffer.append(line)
    flush()
    return result


def compute_changes(previous_md: str, current_md: str) -> list[dict]:
    """比较两份方案正文，返回改动过的章节清单（`[{"kind", "heading"}, ...]`）。

    顺序：先按新文档顺序给出新增 / 修改的章节，再按旧文档顺序给出删除的章节。
    两份都无标题时退化为整篇比较（"全文"）。
    """
    previous = sections(previous_md)
    current = sections(current_md)

    if not previous and not current:
        if previous_md.strip() == current_md.strip():
            return []
        return [{"kind": CHANGE_MODIFIED, "heading": WHOLE_DOCUMENT}]

    changes: list[dict] = []
    for heading, body in current.items():
        if heading not in previous:
            changes.append({"kind": CHANGE_ADDED, "heading": heading})
        elif previous[heading] != body:
            changes.append({"kind": CHANGE_MODIFIED, "heading": heading})
    for heading in previous:
        if heading not in current:
            changes.append({"kind": CHANGE_REMOVED, "heading": heading})
    return changes