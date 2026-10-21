"""页面规划的请求 / 响应模型（工单 25 / ADR-0004）。

契约要点：
- 请求只有 `target_pages`（页数）：权重来自方案建议字数、封面恒占一页都由后端规划模块
  决定，前端不传权重、不传章节清单——规划里的每页归属由后端按权重合并/拆分得出；
- 响应里每个页都给 `index`（1 起，含封面）、`kind`（cover/content）、`title`、
  `chapter_seqs`（该页内容来源章节：封面为空元组，正文页恒有）；`actual_pages`
  恒等于 `target_pages`（「说多少页就是多少页」），`page_plan_id` 供后续
  #26 预览与单页增删寻址这份规划。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.pageplan.planner import (
    PAGE_KIND_CONTENT,
    PAGE_KIND_COVER,
)


class PagePlanRequest(BaseModel):
    """一次页面规划的输入：目标页数。

    页数区间 [3, 60] 由规划模块校验（区间外由服务层翻 422，带「请选择 3–60」的提示）。
    """

    model_config = ConfigDict(extra="forbid")

    target_pages: int = Field(
        description="目标页数（含封面一页），3–60 之间；区间外由规划模块判并翻 422",
    )


class PlannedPageItem(BaseModel):
    """规划里的一个页。"""

    model_config = ConfigDict(extra="forbid")

    index: int
    kind: str = Field(
        pattern=f"^(?:{PAGE_KIND_COVER}|{PAGE_KIND_CONTENT})$",
        description="页类型：cover 封面 / content 内容页",
    )
    title: str
    chapter_seqs: list[int] = Field(default_factory=list)


class PagePlanResponse(BaseModel):
    """一次规划的完整结果。"""

    model_config = ConfigDict(extra="forbid")

    page_plan_id: int
    task_id: int
    plan_id: int
    target_pages: int
    actual_pages: int
    pages: list[PlannedPageItem]