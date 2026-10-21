"""填充阶段（fill）的对外数据结构与硬约束（规格 §4；工单 9 / ADR-0006）。

状态取值与中文标签（规格 §4「填充任务表」）：进行中 / 已完成 / 中断 / 失败。本单只会
写出「进行中」，其余三态由后续工单写入（逐章串行完成、用户中断、失败留痕）。

目标字数按**汉字**计（不含标点与空白），计量唯一入口是 `app.hanzi.count_hanzi`；本模块
只承载「上限」与「缺省值」两个常量，不做计量。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.generation import GenerationResponse
from app.models.plan_section import PlanSectionItem

# ADR-0006 / US 14：目标字数的允许区间。两头都**不静默改成边界值**——
# 静默夹紧会让用户以为写了一万字，实际只写了两千（或反过来白烧额度）。
MIN_TARGET_LENGTH = 300
MAX_TARGET_LENGTH = 20000

# 常用档位（US 12）。前端参数弹窗与后端校验必须同一套值，所以放在这里而不是各写一份。
TARGET_LENGTH_PRESETS: tuple[int, ...] = (1000, 2000, 3000, 5000, 8000, 12000)

# 方案没给建议字数（plan-v2 旧格式）时的缺省目标字数；真正的按章分摊见 `app.fill.budget`。
DEFAULT_TARGET_LENGTH = 3000


class FillStatus(str, Enum):
    """填充任务状态（机器值 ↔ 中文标签见 `FILL_STATUS_LABELS`）。"""

    running = "running"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


FILL_STATUS_LABELS: dict[str, str] = {
    "running": "进行中",
    "completed": "已完成",
    "cancelled": "中断",
    "failed": "失败",
}


class FillRequest(BaseModel):
    """开始填充的请求体。

    - `target_length`：本次正文的目标字数（按汉字计）；缺省时按方案各章建议字数求和，
      方案也没给建议字数则用 `DEFAULT_TARGET_LENGTH`；
    - `section_lengths`：逐章建议字数（序号 → 字数），可选；缺省沿用方案的「建议字数」。
      只允许调整**已存在**的章节序号——不存在的序号静默忽略会让人以为分摊生效了。
    """

    model_config = ConfigDict(extra="forbid")

    target_length: int | None = Field(default=None, ge=1)
    section_lengths: dict[int, int] | None = None


class FillAllocationItem(BaseModel):
    """分摊预览里的一章：只回答「这一章分到多少字」。"""

    model_config = ConfigDict(extra="forbid")

    seq: int
    title: str
    target_length: int


class FillAllocationResponse(BaseModel):
    """目标字数的分摊预览（工单 15）：**只算不写**。

    为什么要有它：用户在参数弹窗里选完字数、还没点「确认开始填充」时，得先看见
    「哪一章多少字」才好逐章调整。若让前端自己摊一遍，就会出现两套分摊实现，
    一旦算法改动两边立刻不一致（规格 §2 点名反对的「多套实现互相错位」）。
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: int
    target_length: int
    items: list[FillAllocationItem]
    total: int


class FillTask(BaseModel):
    """一次填充任务的记录（对应 `fill_tasks` 表的一行）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    task_id: int
    plan_id: int
    target_length: int
    completed_sections: int
    status: FillStatus
    status_label: str
    error: str | None = None
    created_at: str


class FillResponse(FillTask):
    """开始填充的响应：填充任务标识 + 本次的章节清单（初始进度）。

    章节清单的字段与 `GET /api/tasks/{id}/sections` 完全一致，前端不需要为填充再写一套
    解析；`total` 与 `items` 同源，避免「总共几章」出现两个答案。
    """

    items: list[PlanSectionItem]
    total: int


class SectionWriteResponse(BaseModel):
    """写完一章的响应：刚写好的那一章 + 随即拼装出来的正文成品。

    `section` 是**章节项**（与只读清单同构），`deliverable` 是**成品记录**
    （与 `GET /generations` 列表同构）。两者都是既有结构，本单不另造一套形状。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: int
    fill_id: int
    section: PlanSectionItem
    deliverable: GenerationResponse


class SerialFillResponse(BaseModel):
    """全篇逐章填完后的响应：进度 + 章节清单 + 成品 + 字数偏差（工单 11 / 16）。

    进度文字由后端给（`progress_label` = 「第 N / M 章」），前端不必自己拼——
    两处各拼一次就会出现「第 3 章」与「第 3 / 8 章」两种说法。

    `deliverable` 在**被中断**时为 None（工单 13）：中断时还没写完整篇，
    此时出一份成品等于把「写了一半的文章」当成品交出去。

    偏差四项（工单 16）：`target_length` / `actual_length` / `deviation_ratio` /
    `deviation_note`。为什么由后端算：偏差要按**唯一计量入口** `app.hanzi.count_hanzi`
    数，前端另数一套就会得出不同的数（US 18 要求用户数出来的数与系统给的数能对上）。
    `deviation_note` 在 ±15% 以内为 None（不打扰），超出才给可读说明。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: int
    fill_id: int
    status: FillStatus
    status_label: str
    completed_sections: int
    total_sections: int
    progress_label: str
    items: list[PlanSectionItem]
    total: int
    deliverable: GenerationResponse | None = None

    # 字数偏差（工单 16）。
    target_length: int | None = None
    actual_length: int | None = None
    deviation_ratio: float | None = None
    deviation_note: str | None = None


class SectionRewriteResponse(BaseModel):
    """重写一章的响应（工单 14）：刚重写的章 + **重新拼装**的正文成品。

    成品是新拼的那一份，不是追加的第二份——旧的那份已在服务层清理。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: int
    section: PlanSectionItem
    deliverable: GenerationResponse
