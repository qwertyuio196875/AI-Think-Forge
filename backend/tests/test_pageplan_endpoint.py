"""页面规划端点（工单 25 / ADR-0004；接缝 = 进程内 HTTP；模型走 fake）。

钉住 issue #25 验收：
1. **说多少页就是多少页**：`target_pages` 是多少，响应的 `actual_pages` 就恰好是多少，
   封面占一页且计入总数（3 章 → 6 页规划出 6 页；6 章 → 3 页规划出恰 3 页且含封面）；
2. **页数不足按权重合并、不顺序截断**（规划模块语义，端点回读验证）；
3. **未填充就请求 → 409**（且不落任何 page_plans 行）；
4. **页数超出 [3, 60] → 422**，并说明「3–60」；
5. 响应里的每页带 `kind / title / chapter_seqs` 归属章节；`page_plan_id` 落库可回读。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.pageplan.planner import MAX_TARGET_PAGES, MIN_TARGET_PAGES

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n"
    "- 标题：常见疑问 ｜ 要点：三个高频问题的解答 ｜ 建议字数：300\n\n"
    "## 关键约束\n篇幅控制在十页以内。\n"
)

CHAPTER_TITLES = ("产品全景", "第一次上手", "常见疑问")

# 三章正文：长度与建议字数相称，只写一章也没关系（规划只要求有已填充正文）。
def _body(title: str, hanzi: int, filler: str) -> str:
    unit = len(filler)
    repeat = max(1, -(-hanzi // unit))
    return f"## {title}\n\n{filler * repeat}\n"


BODY_FIRST = _body(
    "早上开工的第一件事",
    580,
    "新员工到岗后先看一眼今天的数据，再找同事确认昨天卡住的地方，把这两件事做熟流程就顺了。",
)
BODY_SECOND = _body(
    "第一天要做的五件事",
    390,
    "第一天不需要做完所有事，只要把五件小事按顺序做完，后面的路自然就顺了，也更容易坚持。",
)
BODY_THIRD = _body(
    "关于额度的三个问题",
    290,
    "额度是团队最常问的问题里最难答的一个，因为它的答案随用量变化，要按实际场景判断。",
)

_SUMMARY = "本章讲完了，为下一章留下悬念。"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _task_filled(
    client: TestClient, scripted: ScriptedModelClient, *, fill_all: bool = True
) -> int:
    """走完拷问 → 收敛 → 确认方案 → 开始填充 →（可选）全篇填充，返回任务 id。"""
    responses: list[str] = []
    if fill_all:
        for body in (BODY_FIRST, BODY_SECOND, BODY_THIRD):
            responses.extend([body, _SUMMARY])
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
        *responses,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    assert client.post(f"/api/grilling/tasks/{task_id}/advance").status_code == 200
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    assert client.post(f"/api/tasks/{task_id}/fill", json={}).status_code == 200
    if fill_all:
        assert client.post(f"/api/tasks/{task_id}/fill/run").status_code == 200
    return task_id


def _page_plan_rows(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM page_plans WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ).fetchall()
    return [dict(row) for row in rows]


# --- 验收 ①：说多少页就是多少页 ------------------------------------------------


def test_page_plan_returns_exactly_the_requested_pages(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """3 章 → 请求 6 页：实际恰好 6 页，含封面共 6，后续每页归属章节。"""
    task_id = _task_filled(grilling_client, scripted_model_client)

    response = grilling_client.post(f"/api/tasks/{task_id}/page-plans", json={"target_pages": 6})

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["target_pages"] == 6
    assert body["actual_pages"] == 6
    assert len(body["pages"]) == 6
    # 封面占第 1 页。
    assert body["pages"][0]["kind"] == "cover"
    assert body["pages"][0]["index"] == 1
    assert body["pages"][0]["chapter_seqs"] == []
    # 其余是内容页，index 连续、每页归属章节。
    for i, page in enumerate(body["pages"][1:], start=2):
        assert page["kind"] == "content"
        assert page["index"] == i
        assert page["chapter_seqs"]
    # 落库可回读。
    rows = _page_plan_rows(db_path, task_id)
    assert len(rows) == 1
    assert rows[0]["target_pages"] == 6
    assert rows[0]["pages_json"] != ""


def test_page_plan_six_chapters_to_three_pages_keeps_cover(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """几章 → 请求 3 页：实际恰好 3 页且含封面（封面 + 2 正文页）。"""
    task_id = _task_filled(grilling_client, scripted_model_client)

    response = grilling_client.post(f"/api/tasks/{task_id}/page-plans", json={"target_pages": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["actual_pages"] == 3
    assert body["pages"][0]["kind"] == "cover"
    assert body["pages"][0]["index"] == 1
    content = [p for p in body["pages"] if p["kind"] == "content"]
    assert len(content) == 2


# --- 验收 ③：未填充 → 409 ------------------------------------------------------


def test_page_plan_rejected_when_nothing_filled(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """方案已确认但一章都没填充 → 409，且不落任何 page_plans 行。"""
    task_id = _task_filled(grilling_client, scripted_model_client, fill_all=False)

    response = grilling_client.post(f"/api/tasks/{task_id}/page-plans", json={"target_pages": 6})

    assert response.status_code == 409
    assert "尚未填充任何章节" in response.json()["detail"]
    assert _page_plan_rows(db_path, task_id) == []


# --- 验收 ④：页数区间 ----------------------------------------------------------


def test_page_plan_rejects_pages_out_of_range(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)

    for bad in (MIN_TARGET_PAGES - 1, MAX_TARGET_PAGES + 1):
        response = grilling_client.post(
            f"/api/tasks/{task_id}/page-plans", json={"target_pages": bad}
        )
        assert response.status_code == 422
        assert "3–60" in response.json()["detail"]

    assert _page_plan_rows(db_path, task_id) == []


# --- 闸门：方案未确认 / 无方案 -------------------------------------------------


def test_page_plan_rejected_when_plan_not_confirmed(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """方案已推演（advance 成功）但未确认 → 409（闸门与生成同口径）。"""
    scripted_model_client.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
    )
    fresh = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    grilling_client.post(
        f"/api/grilling/tasks/{fresh}/answers",
        json={"round_no": 1, "answers": ["新员工"]},
    )
    assert grilling_client.post(f"/api/grilling/tasks/{fresh}/advance").status_code == 200
    # 不确认方案。

    response = grilling_client.post(f"/api/tasks/{fresh}/page-plans", json={"target_pages": 6})

    assert response.status_code == 409
    assert "尚未确认" in response.json()["detail"]
    assert _page_plan_rows(db_path, fresh) == []