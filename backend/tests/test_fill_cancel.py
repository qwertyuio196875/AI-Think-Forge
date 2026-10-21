"""填充中断与续写（工单 13 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 13 的四条验收：

1. **中断后已完成章节的正文逐字不变**；
2. **续写从下一章开始，不重跑已完成章节**；
3. **中断本身不产生成品文件，也不报错**；
4. **进度文字与实际完成章节数一致**。

中断发生在**章节边界**上：正在写的那一章必须写完才能停，写到一半停下会在库里
留下半章正文。所以「中断」是「置标记 + 在下一个边界停下」，不是「立刻打断」。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n"
    "- 标题：常见疑问 ｜ 要点：三个高频问题的解答 ｜ 建议字数：300\n"
)

BODY_FIRST = "## 早上开工\n\n第一篇正文，讲产品主线是怎么串起来的。\n"
BODY_SECOND = "## 第一天\n\n第二篇正文，讲第一天要做的五件事。\n"
BODY_THIRD = "## 额度问题\n\n第三篇正文，讲三个高频问题的答案。\n"

_SUMMARY = "本章讲完了主线，给下一章留下了承接点。"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _start_fill(
    client: TestClient, scripted: ScriptedModelClient, *responses: str
) -> int:
    """走完拷问 → 确认方案 → 开始填充，返回任务 id。"""
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
    return task_id


def _section_rows(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT seq, title, content_md, status FROM plan_sections"
            " WHERE task_id = ? ORDER BY seq ASC",
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fill_row(db_path: Path, task_id: int) -> dict:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM fill_tasks WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)
        ).fetchone()
    return dict(row)


def _generation_rows(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM generations WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ).fetchall()
    return [dict(row) for row in rows]


# --- 验收 ①③：中断保留已写正文、不产出成品 ----------------------------------------


def test_cancel_marks_the_fill_task_and_creates_no_deliverable(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """请求中断：填充任务被标记，且**不产生成品文件**（还没写完整篇）。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        _SUMMARY,
        BODY_SECOND,
        _SUMMARY,
        BODY_THIRD,
        _SUMMARY,
    )

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["deliverable"] is None
    assert body["status"] == "running", "中断标记只在章节边界生效，此时还在等当前章写完"
    row = _fill_row(db_path, task_id)
    assert int(row["cancel_requested"]) == 1
    assert _generation_rows(db_path, task_id) == []


def test_cancel_without_active_fill_returns_409(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """没有进行中的填充任务 → 409（没什么可中断的）。"""
    scripted_model_client.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
    )
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"][
        "id"
    ]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")
    grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/cancel")

    assert response.status_code == 409
    assert "填充" in response.json()["detail"]


def test_cancelled_run_stops_without_deliverable(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """先置中断标记再跑：串行循环在第一个章节边界就停下，不出成品、不报错。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        _SUMMARY,
        BODY_SECOND,
        _SUMMARY,
        BODY_THIRD,
        _SUMMARY,
    )
    assert grilling_client.post(f"/api/tasks/{task_id}/fill/cancel").status_code == 200

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    # 中断不是错误。
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["status_label"] == "中断"
    assert body["deliverable"] is None
    assert body["completed_sections"] == 0
    assert _generation_rows(db_path, task_id) == []


# --- 验收 ①②④：续写从下一章继续、已完成章节逐字不变 -------------------------------


def test_resume_after_cancel_continues_from_the_next_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """中断后重新开始填充：从下一章继续，已完成章节逐字不变，最终成品完整。

    这条用例走的是**真实的两段式**：先跑一次被中断，再开一次新的填充跑完。
    中断标记在第一个章节边界就停下，所以第一次跑一章都不写。
    """
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        _SUMMARY,
        BODY_SECOND,
        _SUMMARY,
        BODY_THIRD,
        _SUMMARY,
    )

    # 第一步：先置中断标记再跑 → 第一个章节边界就停，什么都不写。
    assert grilling_client.post(f"/api/tasks/{task_id}/fill/cancel").status_code == 200
    first_run = grilling_client.post(f"/api/tasks/{task_id}/fill/run").json()
    assert first_run["status"] == "cancelled"
    assert first_run["completed_sections"] == 0
    assert [row["content_md"] for row in _section_rows(db_path, task_id)] == ["", "", ""]

    # 第二步：重新开始一次填充 → 三章全部写完（旧任务已 cancelled，不再是 running）。
    restarted = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})
    assert restarted.status_code == 200
    second_run = grilling_client.post(f"/api/tasks/{task_id}/fill/run").json()

    assert second_run["status"] == "completed"
    assert second_run["completed_sections"] == 3
    assert second_run["deliverable"] is not None

    rows = _section_rows(db_path, task_id)
    assert rows[0]["content_md"] == BODY_FIRST.strip()
    assert rows[1]["content_md"] == BODY_SECOND.strip()
    assert rows[2]["content_md"] == BODY_THIRD.strip()


def test_progress_matches_completed_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """进度文字与实际完成章节数一致（不各算一套）。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        _SUMMARY,
        BODY_SECOND,
        _SUMMARY,
        BODY_THIRD,
        _SUMMARY,
    )

    body = grilling_client.post(f"/api/tasks/{task_id}/fill/run").json()

    rows = _section_rows(db_path, task_id)
    completed = sum(1 for row in rows if row["status"] == "completed")
    assert body["completed_sections"] == completed == 3
    assert body["total_sections"] == len(rows) == 3
    assert body["progress_label"] == f"第 {completed} / {len(rows)} 章"
