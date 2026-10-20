"""成品章节（`plan_sections`）的响应模型（工单 7 / ADR-0006）。

契约要点：
- **只读**：本单不提供改名 / 排序 / 增删章节的接口——那是把方案编辑提前，超出范围；
- `status` 给机器值（`pending` / `completed` / `failed`），`status_label` 同时给中文
  （待写 / 已完成 / 失败），避免前端各自翻译（与知识库 `index_status_label` 同风格）；
- `hanzi_count` 是**已写汉字数**，由后端按唯一入口 `app.hanzi.count_hanzi` 现算，
  前端不另写一套；`target_length` 是方案给的建议字数，旧格式方案可能为空。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

# 状态取值域与中文标签。ADR-0006：三态必须能把「没写 / 写完 / 写挂了」分开。
SECTION_STATUS_LABELS: dict[str, str] = {
    "pending": "待写",
    "completed": "已完成",
    "failed": "失败",
}


class PlanSectionStatus(str, Enum):
    """成品章节状态：待写 / 已完成 / 失败。"""

    pending = "pending"
    completed = "completed"
    failed = "failed"


class PlanSectionItem(BaseModel):
    """成品目录里的一章（标题 / 要点 / 状态 / 字数 / 建议字数）。

    **不含已写正文**：正文由填充模块写库、由成品文件呈现，清单只回答「目录长什么样、
    写到哪一步了」；把正文塞进清单会让列表接口随正文体积膨胀。
    """

    model_config = ConfigDict(extra="forbid")

    seq: int
    title: str
    key_points: str = ""
    target_length: int | None = None
    hanzi_count: int
    status: PlanSectionStatus
    status_label: str
    completed_at: str | None = None


class PlanSectionListResponse(BaseModel):
    """某任务的成品章节清单（只读）；方案没有可切分章节时是空清单而不是错误。"""

    model_config = ConfigDict(extra="forbid")

    plan_id: int
    items: list[PlanSectionItem]
    total: int
