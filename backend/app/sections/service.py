"""成品章节的业务逻辑：从方案切分章节并落库（工单 7 / ADR-0006）。

切分本身**不在这里**：唯一真源是 `app.grilling.plan_sections.parse_plan_sections`
（工单 6 交付），本模块只负责「什么时候切、切完怎么落」。再写一套解析器就等于给
规格 §2 已经点名的「三套切分器互相不一致」再添第四套。

调用时机（ADR-0006「确认后写入」）：
- 方案确认时（`POST /api/grilling/tasks/{id}/plan/confirm`）切分并落库；
- 方案修订后（`POST /api/grilling/tasks/{id}/plan/revisions`）重新切分，因为修订可能
  增删章节、把章节改到别的标题下；不重切，下游就会按过期的目录去填充。

重复确认是幂等的：同一份正文切出的清单与旧清单标题一致，按标题匹配后正文与状态都保留。
方案没有「章节」一节时切出空清单——**空清单不是错误**（验收 ②）。
"""

from __future__ import annotations

from app.db.plan_section_repository import PlanSectionRepository
from app.grilling.plan_sections import parse_plan_sections
from app.hanzi import count_hanzi
from app.models.plan_section import SECTION_STATUS_LABELS, PlanSectionItem


def to_section_items(records: list[dict]) -> list[PlanSectionItem]:
    """把章节行转成对外结构（含现算的汉字数与中文状态标签）。

    只读清单（`GET /sections`）与填充入口的初始进度（`POST /fill`）必须给出**同一份**
    章节数据，否则前端会看到两个「第几章、多少字」。所以构造只有这一处。
    """
    return [
        PlanSectionItem(
            seq=record["seq"],
            title=record["title"],
            key_points=record["key_points"],
            target_length=record["target_length"],
            hanzi_count=count_hanzi(record["content_md"]),
            status=record["status"],
            status_label=SECTION_STATUS_LABELS.get(record["status"], record["status"]),
            completed_at=record["completed_at"],
        )
        for record in records
    ]


def sync_plan_sections(
    *, task_id: int, plan: dict, section_repository: PlanSectionRepository
) -> list[dict]:
    """按方案正文重新切分章节并落库，返回落库后的章节行（按序号升序）。

    `plan` 是 `plans` 表的一行（需要 `id` 与 `content_md`）。解析不出章节时写入空清单，
    顺带清掉这份方案的旧行——方案被改成没有章节了，旧目录必须一起消失，不能留残影。
    """
    parsed = parse_plan_sections(plan["content_md"])
    sections = [
        {
            "seq": section.seq,
            "title": section.title,
            "key_points": section.key_points,
            "target_length": section.suggested_length,
        }
        for section in parsed
    ]
    return section_repository.replace(task_id, plan["id"], sections)
