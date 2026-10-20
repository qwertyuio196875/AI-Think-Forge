"""成品章节解析：从方案「章节」一节解析出章节清单（工单 6 / ADR-0006）。

术语（GLOSSARY）：**方案分节**是方案里的 `##` 级段落（目标、读者、章节……）；
**成品章节**是成品正文的章，其清单只来自方案「章节」那一节里的条目。
二者不可互换——所以本解析器不拿 `##` 切分结果当成品目录。

这是下游工单 7（章节表与章节切分）的唯一入口。旧格式（plan-v2）方案必须仍能读：
解析不出建议字数就给 `None`（下游按缺省权重处理），
解析不出章节条目就返回空清单，任何情况下都不抛异常。
"""

from __future__ import annotations

from app.grilling.plan_sections import parse_plan_sections

V3_PLAN_MD = """# 面向新员工的产品培训

## 目标
让新员工在入职两周内掌握产品全貌。

## 章节
- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600
- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400

## 待确认事项
- 是否需要配套练习？
"""


def test_parses_v3_chapter_entries_in_order() -> None:
    """plan-v3 方案：每章一行解析为标题、要点、建议字数，顺序即章节顺序。"""
    sections = parse_plan_sections(V3_PLAN_MD)

    assert [section.title for section in sections] == ["产品全景", "第一次上手"]
    assert [section.key_points for section in sections] == [
        "从三个真实场景切入讲清主线",
        "第一天要做的五件事",
    ]
    assert [section.suggested_length for section in sections] == [600, 400]
    assert [section.seq for section in sections] == [1, 2]


def test_v2_plan_without_suggested_length_degrades_to_none() -> None:
    """旧格式（plan-v2）方案：章节一节在、但没写建议字数 —— 不给长度，照样给出清单。

    历史方案的 `content_md` 是 plan-v2 生成的，读取方不得因此报错；
    缺建议字数时由下游按缺省权重处理（issues/2.md:143）。
    """
    v2_plan_md = """# 面向新员工的产品培训

## 目标
让新员工在入职两周内掌握产品全貌。

## 章节
- 产品全景：讲清产品主线
- 第一次上手：第一天要做的五件事

## 待确认事项
- 是否需要配套练习？
"""

    sections = parse_plan_sections(v2_plan_md)

    assert [section.title for section in sections] == ["产品全景", "第一次上手"]
    assert [section.key_points for section in sections] == [
        "讲清产品主线",
        "第一天要做的五件事",
    ]
    assert [section.suggested_length for section in sections] == [None, None]


def test_v2_plan_with_prose_chapter_section_returns_empty_list() -> None:
    """旧格式的「章节」一节写成叙述（没有条目）—— 返回空清单，不猜、不报错。"""
    v2_prose_md = """# 面向新员工的产品培训

## 目标
让新员工在入职两周内掌握产品全貌。

## 章节
本章围绕产品全景与第一次上手两条主线展开，具体篇幅按现场情况调整。

## 待确认事项
- 是否需要配套练习？
"""

    assert parse_plan_sections(v2_prose_md) == []


def test_plan_without_chapter_section_returns_empty_list_not_headings() -> None:
    """没有「章节」一节时返回空清单 —— 其余 `##` 是方案分节，不是成品章节。"""
    no_chapter_md = """# 面向新员工的产品培训

## 目标
让新员工在入职两周内掌握产品全貌。

## 读者
入职两周内的新员工。

## 待确认事项
- 是否需要配套练习？
"""

    assert parse_plan_sections(no_chapter_md) == []


def test_v2_plan_using_subheadings_per_chapter_is_not_treated_as_sections() -> None:
    """旧方案把每章写成 `###` 小标题 —— 不按标题层级退化切分，返回空清单。

    ADR-0006:36：解析不出章节条目时明确拒绝并提示返回修订方案，不猜测。
    """
    v2_subheadings_md = """# 面向新员工的产品培训

## 目标
让新员工在入职两周内掌握产品全貌。

## 章节
### 产品全景
讲清产品主线，约 600 字。

### 第一次上手
第一天要做的五件事，约 400 字。
"""

    assert parse_plan_sections(v2_subheadings_md) == []


def test_heading_named_chapter_elsewhere_does_not_swallow_neighbours() -> None:
    """「章节」一节只取到下一个同级分节为止，不吞掉后面的方案分节。"""
    trailing_md = """# 方案

## 章节
- 标题：产品全景 ｜ 要点：讲清主线 ｜ 建议字数：600

## 待确认事项
- 标题：这不属于章节 ｜ 要点：只是待确认的一条 ｜ 建议字数：10
"""

    sections = parse_plan_sections(trailing_md)

    assert [section.title for section in sections] == ["产品全景"]
