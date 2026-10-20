"""历史列表与详情的响应模型（术语「任务」：状态、对话、方案、成品持久保存，可中断后继续）。

历史列表面向工作台左栏（「最近任务」+ 导航徽标），因此除任务本身外还给出：
- `dialogue_messages` / `rounds`：元信息行显示的对话条数与轮次数；
- `HistoryCounts`：创作 / 分析 / 全部的规模（排除已删除任务），供导航项 count 徽标。

详情面（`HistoryDetail`）是「打开详情并续作」的单一入口：一次拿齐复原所需的一切
（种子输入 / 各轮次 / 消息 / 方案 / 待确认事项）与下一步动作（`ResumeNext`），
前端无需为续作再拼别的状态。

分页取舍：采用 `limit` / `offset`（而非游标）——本地单用户库的数据量小，
offset 足够，且前端 pager 直接拿到 `total` 即可渲染页码。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.models.grilling import Dialogue, FrontierRound
from app.models.open_items import OpenItem
from app.models.plan import Plan
from app.models.task import Task, TaskKind, TaskStatus


class ResumeNext(str, Enum):
    """续作的下一步动作（由已持久化状态推导，见 `app.history`）。"""

    # 有前沿待作答的轮次（含「停在拷问中途」）→ 回到该轮继续作答。
    answers = "answers"
    # 轮次已答完、尚无方案 → 推进（重算下一轮或收敛出方案）。
    advance = "advance"
    # 已有方案草稿 → 待方案确认。
    plan_confirm = "plan_confirm"
    # 方案已确认 → 可请求生成成品（Word 一轨见 TB-5；单文件 HTML 见 TB-6）。
    generation = "generation"
    # 任务已完成 / 已删除（软删除留痕）。
    completed = "completed"
    deleted = "deleted"


class HistoryItem(BaseModel):
    """历史列表中的一条任务（含状态点与元信息行所需字段）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: TaskKind
    title: str | None
    status: TaskStatus
    created_at: str
    updated_at: str
    dialogue_messages: int
    rounds: int
    # 分析任务的最新来源 id（供历史「继续查看」直接打开分析页；创作类任务为 null）。
    source_id: int | None = None


class HistoryCounts(BaseModel):
    """导航徽标用的分计数（全局视角，不随列表过滤条件变化）。"""

    model_config = ConfigDict(extra="forbid")

    all: int
    creation: int
    analysis: int


class HistoryListResponse(BaseModel):
    """历史列表响应：当页条目 + 过滤后总数 + 分页参数 + 分计数。"""

    model_config = ConfigDict(extra="forbid")

    items: list[HistoryItem]
    total: int
    limit: int
    offset: int
    counts: HistoryCounts


class HistoryDetail(BaseModel):
    """任务详情 + 续作状态（「打开详情并续作」的单一入口）。

    `dialogue` 即规格 §4 `messages` 复原出的对话（种子输入 + 各轮次 + 原始消息），
    续作靠它复原，**不新建状态**。
    """

    model_config = ConfigDict(extra="forbid")

    task: Task
    deleted_at: str | None
    dialogue: Dialogue
    plan: Plan | None
    open_items: list[OpenItem]
    unresolved_open_items: int
    last_round_no: int
    pending_round: FrontierRound | None
    awaiting: ResumeNext