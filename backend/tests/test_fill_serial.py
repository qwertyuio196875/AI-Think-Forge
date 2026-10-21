"""全篇逐章串行填充（工单 11 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 11 的四条验收：

1. **最终成品的章节数等于章节清单的章节数**；
2. **任一章节生成失败时不产出残缺成品**，并明确报错指出是哪一章；
3. **逐章进度可被前端读取**（第 N / M 章）；
4. **不得把两章内容写进同一章，也不得漏章**。

本单只做「把剩余章节一章一章写完」。前情提要 #12、中断续写 #13、单章重写 #14、
字数分摊 #15、偏差修正 #16、长章分段 #17 都不在这里——它们各自接在
`app.fill.writer.write_section` 之上。

写作调用仍只发生在「写某一章」这一个动作上：串行编排是**依次**调用它，
因此工单 10 的既有契约（单章端点、失败留痕、不产出半成品）一条都不改。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from docx import Document
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect

IDEA = "帮我准备一份面向新员工的产品培训"

# plan-v3 形状的方案：三章，各带要点与建议字数。
PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n"
    "- 标题：常见疑问 ｜ 要点：三个高频问题的解答 ｜ 建议字数：300\n\n"
    "## 关键约束\n篇幅控制在十页以内。\n"
)

CHAPTER_TITLES = ("产品全景", "第一次上手", "常见疑问")

# 三章各自的正文：形态各异，才能验证「没有把两章写进同一章」。
BODY_FIRST = (
    "## 早上开工的第一件事\n\n"
    "新员工到岗的第一个上午，其实不需要读完任何手册。"
    "真正要做的是把手从键盘上挪开一次，先看看别人每天是怎么用它的。\n"
)
BODY_SECOND = (
    "## 第一天要做的五件事\n\n"
    "第一天不需要做完所有事，只要把五件小事做完，后面的路就顺了。\n"
)
BODY_THIRD = (
    "## 关于额度的三个问题\n\n"
    "额度是团队最常问的三个问题里最难答的一个，因为它的答案随用量变化。\n"
)

# 摘要调用（工单 12）的固定应答：这些用例只关心正文与进度，不关心摘要内容。
_SUMMARY = "本章讲完了产品主线，为下一章留下了「先做哪五件事」的悬念。"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _task_with_started_fill(
    client: TestClient, scripted: ScriptedModelClient, *bodies: str
) -> int:
    """走完拷问 → 收敛 → 确认方案 → 开始填充，返回任务 id。

    `bodies` 是逐章写作的应答（按章顺序）；不给就用 `BODY_FIRST`。

    **每章正文后跟着一次摘要调用**（工单 12）：`set_sequence` 是按调用顺序取应答的，
    所以这里要把「正文 / 摘要」交错排好，否则摘要调用会吃掉下一章的正文应答。
    摘要给一段固定短文本即可——这些用例关心的是正文与进度，不是摘要内容。
    """
    responses: list[str] = []
    for body in bodies or (BODY_FIRST,):
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


def _paragraphs(document, style_name: str) -> list[str]:
    return [p.text for p in document.paragraphs if p.style.name == style_name]


# --- 验收 ①：成品章节数等于清单章节数 ---------------------------------------------


def test_serial_fill_writes_every_remaining_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """一次跑完全篇：三章都写完，状态全为「已完成」。"""
    task_id = _task_with_started_fill(
        grilling_client, scripted_model_client, BODY_FIRST, BODY_SECOND, BODY_THIRD
    )

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 200
    rows = _section_rows(db_path, task_id)
    assert [row["status"] for row in rows] == ["completed"] * 3
    assert [row["title"] for row in rows] == list(CHAPTER_TITLES)


def test_serial_fill_produces_a_deliverable_with_one_chapter_per_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """成品里的章标题与章节清单逐一同序同数（防「第三章写进第四章」）。"""
    task_id = _task_with_started_fill(
        grilling_client, scripted_model_client, BODY_FIRST, BODY_SECOND, BODY_THIRD
    )

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 200
    artifact = Path(response.json()["deliverable"]["file_path"])
    document = Document(str(artifact))
    headings = _paragraphs(document, "Heading 1")
    assert headings == [
        "第 1 章 · 产品全景",
        "第 2 章 · 第一次上手",
        "第 3 章 · 常见疑问",
    ]


def test_each_chapter_keeps_its_own_body(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """两章内容不混：每章正文只出现在自己那一章里。"""
    task_id = _task_with_started_fill(
        grilling_client, scripted_model_client, BODY_FIRST, BODY_SECOND, BODY_THIRD
    )

    grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    rows = _section_rows(db_path, task_id)
    assert rows[0]["content_md"] == BODY_FIRST.strip()
    assert rows[1]["content_md"] == BODY_SECOND.strip()
    assert rows[2]["content_md"] == BODY_THIRD.strip()


# --- 验收 ②：失败不产出残缺成品，且指出是哪一章 ---------------------------------


def test_failure_in_a_later_section_leaves_no_partial_deliverable(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """第二章失败 → 报错指出第 2 章，且磁盘上不出现残缺的正文成品。"""
    task_id = _task_with_started_fill(
        grilling_client, scripted_model_client, BODY_FIRST
    )
    # 拷问阶段已调用模型 3 次；再放行 1 次（第一章），之后起抛错 → 第二章失败。
    scripted_model_client.fail_after(
        len(scripted_model_client.calls) + 1, httpx.ConnectError("boom")
    )

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 502
    assert "第 2 章" in response.json()["detail"]
    # 失败留痕：第一章写成了，第二章标失败。
    rows = _section_rows(db_path, task_id)
    assert rows[0]["status"] == "completed"
    assert rows[1]["status"] == "failed"
    assert rows[2]["status"] == "pending"
    # 残缺成品不交付。
    assert [row["source"] for row in _generation_rows(db_path, task_id)] == []


def test_failed_fill_task_records_which_section_failed(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """填充任务标「失败」并留痕是第几章（不是一句笼统的「生成失败」）。"""
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    scripted_model_client.fail_after(
        len(scripted_model_client.calls), httpx.ConnectError("boom")
    )

    grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    row = _fill_row(db_path, task_id)
    assert row["status"] == "failed"
    assert "第 1 章" in (row["error"] or "")


# --- 验收 ③：逐章进度可被前端读取 --------------------------------------------------


def test_progress_is_readable_while_fill_runs(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """跑完之后进度是「已完成 / 共 N 章」，前端据此显示「第 N / M 章」。"""
    task_id = _task_with_started_fill(
        grilling_client, scripted_model_client, BODY_FIRST, BODY_SECOND, BODY_THIRD
    )

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    body = response.json()
    assert body["completed_sections"] == 3
    assert body["total_sections"] == 3
    assert body["status"] == "completed"
    assert body["status_label"] == "已完成"
    # 进度文字由后端给，前端不必自己拼「第 N / M」。
    assert body["progress_label"] == "第 3 / 3 章"
    assert _fill_row(db_path, task_id)["completed_sections"] == 3


def test_serial_fill_response_carries_the_section_list(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """响应带章节清单（与只读清单同构），前端不必再发一次请求。"""
    task_id = _task_with_started_fill(
        grilling_client, scripted_model_client, BODY_FIRST, BODY_SECOND, BODY_THIRD
    )

    body = grilling_client.post(f"/api/tasks/{task_id}/fill/run").json()

    assert body["total"] == 3
    assert [item["seq"] for item in body["items"]] == [1, 2, 3]
    assert all(item["status"] == "completed" for item in body["items"])


# --- 负测与既有契约 ----------------------------------------------------------------


def test_serial_fill_requires_a_started_fill(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """没有进行中的填充任务 → 409（填充是独立阶段，得先「确认开始填充」）。"""
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

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 409
    assert "填充" in response.json()["detail"]


def test_serial_fill_is_rejected_while_plan_is_not_confirmed(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案未确认 → 409，绝不写正文。"""
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

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 409
    assert "确认" in response.json()["detail"]
