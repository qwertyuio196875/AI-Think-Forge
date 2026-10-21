"""页面规划路由（工单 25 / ADR-0004）：页面规划与单页增删。

规划（#25）：`POST /api/tasks/{task_id}/page-plans`。接受「目标页数」，校验方案已确认 +
已填充正文，规划出**恰好** `target_pages` 页（含封面）的「章节 → 页列表」，落库回传。

单页增删（#26）：对某一次规划执行
- `POST /api/tasks/{task_id}/page-plans/{plan_id}/pages` 增页（在 after_index 后插一页，
  另存一份新规划）；
- `DELETE .../pages/{at_index}` 删页（封面不可删，另存一份新规划）。
实际页数**不再强制等于最初的目标页数**（增删后的真实页数才是新规划的 target_pages，
也是后续 #27 渲染 / #28 截图的对账基准）。

页数与状态拒绝口径：
- 任务 / 方案未确认 / 未处置待确认事项 → 404 / 409（复用 `require_confirmed_plan`）；
- 已确认但一章都没填充 → 409（issue #25「未填充就请求就 409」）；
- 页数不在 [3, 60] → 422（带「请选择 3–60」的提示）；
- 增删页越界 / 删封面 → 422。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    DataDirDep,
    OpenItemRepositoryDep,
    PagePlanRepositoryDep,
    PlanRepositoryDep,
    PlanSectionRepositoryDep,
    TaskRepositoryDep,
)
from app.models.page_plan import (
    PagePlanRequest,
    PagePlanResponse,
    PlannedPageItem,
)
from app.models.page_plan_edit import AddPageRequest
from app.pageplan.edit import PageEditError
from app.pageplan.planner import PagePlanError
from app.pageplan.service import (
    PlanNoBodyError,
    apply_page_edit,
    build_page_plan,
    decode_page_plan,
)

router = APIRouter(prefix="/tasks", tags=["page-plans"])

# 参数/数据不可用统一用 422。这里写字面量而不是 `status.HTTP_422_UNPROCESSABLE_ENTITY`：
# 该常量在新版 Starlette 里已改名并会发弃用警告，而旧版又没有新名字；与 fill 路由
# 的既有写法保持一致。
UNPROCESSABLE = 422


def _page_plan_response(outcome: dict) -> PagePlanResponse:
    return PagePlanResponse(
        page_plan_id=outcome["page_plan_id"],
        task_id=outcome["task_id"],
        plan_id=outcome["plan_id"],
        target_pages=outcome["target_pages"],
        actual_pages=outcome["actual_pages"],
        pages=[PlannedPageItem(**page) for page in outcome["pages"]],
    )


def _require_page_plan(
    task_id: int,
    plan_id: int,
    *,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    page_plan_repository: PagePlanRepositoryDep,
) -> dict:
    """定位某次页面规划；任务/方案闸门未过或规划不存在 → 相应 4xx。

    规划是 PPT 一轨的中间产物，与成品同受「方案已确认」闸门约束——方案改过、章节
    变过，旧的规划若不重规划就增删，会拿失效的章节布局继续拼装。
    """
    from app.api.gates import require_confirmed_plan

    require_confirmed_plan(
        task_id, task_repository, plan_repository, open_item_repository, purpose="generate"
    )
    record = page_plan_repository.get(plan_id)
    if record is None or int(record["task_id"]) != task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {task_id} 没有 id 为 {plan_id} 的页面规划",
        )
    return record


@router.post("/{task_id}/page-plans", response_model=PagePlanResponse)
def create_page_plan(
    task_id: int,
    payload: PagePlanRequest,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    section_repository: PlanSectionRepositoryDep,
    page_plan_repository: PagePlanRepositoryDep,
    data_dir: DataDirDep,
) -> PagePlanResponse:
    """按目标页数规划一次「章节 → 页列表」并落库。

    `data_dir` 当前未使用（规划本身不落盘，只落库 JSON），保留参与签名以承接
    #28 截图渲染（截图要写到 data/ 白名单）依赖的演进。
    """
    try:
        outcome = build_page_plan(
            task_id=task_id,
            target_pages=payload.target_pages,
            task_repository=task_repository,
            plan_repository=plan_repository,
            open_item_repository=open_item_repository,
            section_repository=section_repository,
            page_plan_repository=page_plan_repository,
        )
    except PlanNoBodyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc
    except PagePlanError as exc:
        raise HTTPException(status_code=UNPROCESSABLE, detail=exc.detail) from exc

    return _page_plan_response(outcome)


@router.get("/{task_id}/page-plans/{plan_id}", response_model=PagePlanResponse)
def get_page_plan(
    task_id: int,
    plan_id: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    page_plan_repository: PagePlanRepositoryDep,
) -> PagePlanResponse:
    """读取某一次页面规划（含单页增删后的结果），供前端预览。"""
    record = _require_page_plan(
        task_id,
        plan_id,
        task_repository=task_repository,
        plan_repository=plan_repository,
        open_item_repository=open_item_repository,
        page_plan_repository=page_plan_repository,
    )
    pages = decode_page_plan(record["pages_json"])
    return _page_plan_response(
        {
            "page_plan_id": record["id"],
            "task_id": task_id,
            "plan_id": record["plan_id"],
            "target_pages": record["target_pages"],
            "actual_pages": len(pages),
            "pages": pages,
        }
    )


@router.post("/{task_id}/page-plans/{plan_id}/pages", response_model=PagePlanResponse)
def add_page(
    task_id: int,
    plan_id: int,
    payload: AddPageRequest,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    page_plan_repository: PagePlanRepositoryDep,
) -> PagePlanResponse:
    """在某页之后插入一页，另存一份新规划（#26 单页增删）。"""
    record = _require_page_plan(
        task_id,
        plan_id,
        task_repository=task_repository,
        plan_repository=plan_repository,
        open_item_repository=open_item_repository,
        page_plan_repository=page_plan_repository,
    )
    try:
        outcome = apply_page_edit(
            page_plan_id=record["id"],
            task_id=task_id,
            pages_json=record["pages_json"],
            plan_id=record["plan_id"],
            operation="add",
            index=payload.after_index,
            page_plan_repository=page_plan_repository,
        )
    except PageEditError as exc:
        raise HTTPException(status_code=UNPROCESSABLE, detail=exc.detail) from exc

    return _page_plan_response(outcome)


@router.delete("/{task_id}/page-plans/{plan_id}/pages/{at_index}", response_model=PagePlanResponse)
def delete_page(
    task_id: int,
    plan_id: int,
    at_index: int,
    task_repository: TaskRepositoryDep,
    plan_repository: PlanRepositoryDep,
    open_item_repository: OpenItemRepositoryDep,
    page_plan_repository: PagePlanRepositoryDep,
) -> PagePlanResponse:
    """删除某一页（封面不可删），另存一份新规划（#26 单页增删）。"""
    record = _require_page_plan(
        task_id,
        plan_id,
        task_repository=task_repository,
        plan_repository=plan_repository,
        open_item_repository=open_item_repository,
        page_plan_repository=page_plan_repository,
    )
    try:
        outcome = apply_page_edit(
            page_plan_id=record["id"],
            task_id=task_id,
            pages_json=record["pages_json"],
            plan_id=record["plan_id"],
            operation="delete",
            index=at_index,
            page_plan_repository=page_plan_repository,
        )
    except PageEditError as exc:
        raise HTTPException(status_code=UNPROCESSABLE, detail=exc.detail) from exc

    return _page_plan_response(outcome)