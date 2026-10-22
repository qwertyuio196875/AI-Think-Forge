"""页面规划的业务逻辑（工单 25 / ADR-0004）。

闸门与一致性：
- **方案必须已确认且无未定事项**（复用 `require_confirmed_plan`，与填充 / 生成同口径）；
- **必须已有完成填充的正文**：一份 plan 连一个 `completed` 章节都没有，规划就是无米之炊——
  抛 409，绝不产出空规划（issue #25「未填充就请求 → 409」）；
- 页数区间 [3, 60] 由规划模块判（`PagePlanError` → 422）。

页面结构由 `app.pageplan.planner.plan_pages` 算（纯函数），本模块只负责：
把章节行（`plan_sections`）翻成规划输入（章序号 / 标题 / 权重=建议字数）、执行规划、
把计划页落库（`page_plans`）、组装响应结构。权重回源头读章节行的 `target_length`
（方案建议字数，ADRP-0006 同源），缺失/非正数由规划模块退化为均分。
"""

from __future__ import annotations

import json

from app.api.gates import require_confirmed_plan
from app.db.open_item_repository import OpenItemRepository
from app.db.page_plan_repository import PagePlanRepository
from app.db.plan_repository import PlanRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.db.task_repository import TaskRepository
from app.pageplan.planner import (
    Chapter,
    PlannedPage,
    plan_pages,
    validate_target_pages,
)


class PlanNoBodyError(Exception):
    """没有可规划的成品正文（未填充 → 409）。"""

    detail = (
        "尚未填充任何章节，无法规划 PPT 页数"
        "（请先完成填充，让正文落地后再规划页数）"
    )


def _page_to_dict(page: PlannedPage) -> dict:
    return {
        "index": page.index,
        "kind": page.kind,
        "title": page.title,
        "chapter_seqs": list(page.chapter_seqs),
    }


def build_page_plan(
    *,
    task_id: int,
    target_pages: int,
    task_repository: TaskRepository,
    plan_repository: PlanRepository,
    open_item_repository: OpenItemRepository,
    section_repository: PlanSectionRepository,
    page_plan_repository: PagePlanRepository,
) -> dict:
    """已确认方案 + 已填充正文 → 落库一份页面规划，返回响应结构。

    任一步失败：`PagePlanError`（页数区间）→ 422；`PlanNoBodyError`（未填充）→ 409。
    """
    plan = require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="generate"
    )

    validate_target_pages(target_pages)

    rows = section_repository.list_for_plan(plan["id"])
    filled = [row for row in rows if row.get("status") == "completed"]
    if not filled:
        raise PlanNoBodyError()

    chapters = [
        Chapter(seq=int(row["seq"]), title=str(row["title"]), weight=row.get("target_length"))
        for row in filled
    ]

    # 封面标题用**任务标题**（用户起的题目），不能用 task_id：那会让封面渲染成
    # 一个数字。取不到标题时退回一个中性占位，绝不把内部主键当内容展示。
    task = task_repository.get(task_id) or {}
    deck_title = str(task.get("title") or "").strip() or "演示"

    result = plan_pages(target_pages=target_pages, chapters=chapters, deck_title=deck_title)

    record = page_plan_repository.create(
        task_id=task_id,
        plan_id=plan["id"],
        target_pages=result.target_pages,
        pages=[_page_to_dict(page) for page in result.pages],
    )

    return {
        "page_plan_id": record["id"],
        "task_id": task_id,
        "plan_id": plan["id"],
        "target_pages": result.target_pages,
        "actual_pages": result.actual_pages,
        "pages": [_page_to_dict(page) for page in result.pages],
    }


def decode_page_plan(pages_json: str) -> list[dict]:
    """回读落库的 `pages_json`；脏数据退为空清单（与 references_json 同口径）。"""
    try:
        pages = json.loads(pages_json or "[]")
        return pages if isinstance(pages, list) else []
    except (ValueError, TypeError):
        return []


def apply_page_edit(
    *,
    page_plan_id: int,
    task_id: int,
    pages_json: str,
    plan_id: int,
    operation: str,
    index: int,
    page_plan_repository: PagePlanRepository,
) -> dict:
    """对某一次规划执行单页增删，另存一份新规划，返回响应结构。

    `operation`：add（在 after_index 之后插一页）/ delete（删 at_index 这一页）。
    失败：`PageEditError`（越界 / 删封面 / 空规划）→ 由调用方翻 422。
    """
    from app.pageplan.edit import add_page, delete_page

    pages = decode_page_plan(pages_json)
    if operation == "add":
        new_pages = add_page(pages, after_index=index)
    elif operation == "delete":
        new_pages = delete_page(pages, at_index=index)
    else:  # 调用方保证只传这两种；兜底抛错避免静默走错分支
        raise ValueError(f"unknown page-plan operation: {operation}")

    record = page_plan_repository.create(
        task_id=task_id,
        plan_id=plan_id,
        target_pages=len(new_pages),
        pages=new_pages,
    )
    return {
        "page_plan_id": record["id"],
        "task_id": task_id,
        "plan_id": plan_id,
        "target_pages": len(new_pages),
        "actual_pages": len(new_pages),
        "pages": new_pages,
    }