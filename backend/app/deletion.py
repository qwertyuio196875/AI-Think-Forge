"""删除影响范围的核算（规格 User Story 27：删除操作明示影响范围）。

删除是**软删除**（留痕、不物理清库），因此影响范围说的是「影响用户能看到什么」，
而不是「会毁掉什么数据」——两件事必须在文案里分清，否则用户无法判断要不要确认。

数字一律来自已持久化数据：成品文件数按 `generations` 表如实计数（TB-5 已落地 Word 一轨）。
"""

from __future__ import annotations

from app.models.task import TaskDeletionImpact

# 未命名任务的显示名（用户可能只给了标题为空的任务）。
UNTITLED_TASK_LABEL = "未命名任务"


def build_impact(
    task: dict,
    *,
    dialogue_messages: int,
    rounds: int,
    plans: int,
    plan_revisions: int,
    open_items: int,
    deliverable_files: int,
) -> TaskDeletionImpact:
    """把各表计数汇总为可读的影响范围。"""
    title = task["title"] or UNTITLED_TASK_LABEL
    summary = (
        f"删除「{title}」将影响：对话 {dialogue_messages} 条（{rounds} 轮）、"
        f"结构化方案 {plans} 份（修订记录 {plan_revisions} 条）、"
        f"待确认事项 {open_items} 条、成品文件 {deliverable_files} 个。"
        "删除为软删除：数据仍留在本地库中可留痕，但任务不再出现在历史列表。"
    )
    return TaskDeletionImpact(
        task_id=task["id"],
        title=task["title"],
        kind=task["kind"],
        status=task["status"],
        dialogue_messages=dialogue_messages,
        rounds=rounds,
        plans=plans,
        plan_revisions=plan_revisions,
        open_items=open_items,
        deliverable_files=deliverable_files,
        summary=summary,
    )