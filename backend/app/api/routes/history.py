"""历史路由：工作台左栏的历史列表 / 详情续作。

术语（GLOSSARY）：**任务**——一次主题创作或资料分析的实例，状态、对话、方案、成品持久保存，
可中断后继续。本模块只负责「列表」与「详情续作」两个读入口：
- 列表默认排除已删除任务（软删除留痕在库，不影响历史视图）；
- 详情一次拿齐复原所需的一切 + 下一步动作，续作靠既有 `messages` / `plans` 复原，不新建状态。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    MessageRepositoryDep,
    OpenItemRepositoryDep,
    PlanRepositoryDep,
    TaskRepositoryDep,
)
from app.grilling.service import build_dialogue
from app.history import derive_resume
from app.models.history import HistoryCounts, HistoryDetail, HistoryItem, HistoryListResponse
from app.models.open_items import OpenItem
from app.models.plan import Plan
from app.models.task import Task, TaskKind, TaskStatus

router = APIRouter(prefix="/history", tags=["history"])

# 一页默认 20 条（本地单用户规模足够一屏 + pager）；上限 100 防一次拉爆。
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@router.get("", response_model=HistoryListResponse)
def list_history(
    repository: TaskRepositoryDep,
    kind: TaskKind | None = None,
    status: TaskStatus | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    """历史列表：按分类 / 状态过滤，按最近（id 倒序）分页。

    `status` 缺省时**排除已删除任务**；显式传 `status=deleted` 时返回已删除任务（留痕查看）。
    """
    kind_value = kind.value if kind is not None else None
    status_value = status.value if status is not None else None

    records = repository.list_history(
        kind=kind_value, status=status_value, limit=limit, offset=offset
    )
    items = [HistoryItem(**record) for record in records]
    return HistoryListResponse(
        items=items,
        total=repository.count_history(kind=kind_value, status=status_value),
        limit=limit,
        offset=offset,
        counts=HistoryCounts(**repository.counts_by_kind()),
    )


@router.get("/{task_id}", response_model=HistoryDetail)
def get_history_detail(
    task_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
) -> HistoryDetail:
    """打开任务详情并拿到续作所需的一切（含停在拷问中途的任务）。

    续作状态由既有持久化数据推导（`app.history.derive_resume`），不新建状态：
    关闭系统再打开，同一份对话与方案必然推导出同一处「从哪继续」。
    """
    task = task_repository.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在"
        )

    dialogue = build_dialogue(task_id, message_repository.list_for_task(task_id))
    plan_record = plan_repository.get_current(task_id)
    open_item_records = open_item_repository.list_for_task(task_id)
    resume = derive_resume(
        task_status=task["status"], rounds=dialogue.rounds, plan=plan_record
    )

    return HistoryDetail(
        task=Task.from_record(task),
        deleted_at=task["deleted_at"],
        dialogue=dialogue,
        plan=Plan(**plan_record) if plan_record is not None else None,
        open_items=[OpenItem(**record) for record in open_item_records],
        unresolved_open_items=sum(
            1 for record in open_item_records if record["status"] == "open"
        ),
        last_round_no=resume.last_round_no,
        pending_round=resume.pending_round,
        awaiting=resume.awaiting,
    )