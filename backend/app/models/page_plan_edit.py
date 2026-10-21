"""页面规划的单页增删请求 / 响应模型（工单 26 / ADR-0004）。

契约要点：
- 增删页都以 `page_plan_id` 定位**某一次规划**，结果**另存一份新规划**（新 `page_plan_id`、
  新 `target_pages` = 新实际页数）——历史规划不改；
- `AddPageRequest.after_index` 是**1 起的真实页码**（含封面）；增页语义见
  `app.pageplan.edit`（封面前后 / 正文页复制拆分）；
- 响应与 `PagePlanResponse` 相同（新规划的完整页列表 + 新 id），前端拿到后直接刷新预览。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AddPageRequest(BaseModel):
    """在某页之后插入一页（1 起页码，含封面）。"""

    model_config = ConfigDict(extra="forbid")

    after_index: int


class DeletePageRequest(BaseModel):
    """删除某一页（1 起页码，含封面）。"""

    model_config = ConfigDict(extra="forbid")

    at_index: int