"""大纲导出路径收口（工单 18 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 18 的三条验收：
1. **大纲导出的文件名带 `outline-` 前缀，填充后的成品不带**——两种产物一眼能分清；
2. 既有 Word 与 HTML 导出行为无回归（格式、可打开、结构完整、外链为零）；
3. 跳过填充也能立刻拿到文件，不多走一步（不需要先建填充任务）。

术语（GLOSSARY）：**大纲导出** = 跳过填充、直接把方案正文渲染成的成品，文件名以
`outline-` 前缀标识；**正文成品** = 填充后的成品，不带该前缀。两者都记在
`generations` 表里，靠 `source` 列区分——但文件名也必须能自己说明身份，
因为用户是从文件管理器里双击打开的。
"""

from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.generation.service import BODY_FILE_PREFIX, OUTLINE_FILE_PREFIX

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
)

BODY_MD = (
    "## 早上开工的第一件事\n\n"
    "新员工到岗的第一个上午，其实不需要读完任何手册，先看看别人每天是怎么用的。\n"
)


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _confirmed_task(
    client: TestClient, scripted: ScriptedModelClient, *, start_fill: bool = False
) -> int:
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
        BODY_MD,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    assert client.post(f"/api/grilling/tasks/{task_id}/advance").status_code == 200
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    if start_fill:
        assert client.post(f"/api/tasks/{task_id}/fill", json={}).status_code == 200
    return task_id


def _file_name(path: str) -> str:
    return Path(path).name


def test_outline_word_export_has_outline_prefix(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """跳过填充直接导出 Word：文件名带 `outline-` 前缀。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    response = grilling_client.post(f"/api/tasks/{task_id}/generations", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "outline"
    name = _file_name(body["file_path"])
    assert name.startswith(OUTLINE_FILE_PREFIX), f"大纲导出文件名没有 outline- 前缀：{name}"
    # 既有结构仍然正确：能被 Word 打开。
    document = Document(body["file_path"])
    assert any("第" in paragraph.text or "章" in paragraph.text for paragraph in document.paragraphs)


def test_outline_html_export_has_outline_prefix(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """大纲导出走 HTML 一轨时同样带前缀，且既有「零外链」约束不回归。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "outline"
    name = _file_name(body["file_path"])
    assert name.startswith(OUTLINE_FILE_PREFIX), f"HTML 大纲导出没有 outline- 前缀：{name}"
    assert body["integrity_ok"] is True
    assert body["external_resources"] == []
    assert Path(body["file_path"]).read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_body_deliverable_has_no_outline_prefix(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """填充后的正文成品不带 `outline-` 前缀（它带 `body-`），两种产物一眼可分。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, start_fill=True)

    written = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")
    assert written.status_code == 200
    path = written.json()["deliverable"]["file_path"]
    name = _file_name(path)

    assert not name.startswith(OUTLINE_FILE_PREFIX), f"正文成品不该带 outline- 前缀：{name}"
    assert name.startswith(BODY_FILE_PREFIX)
    assert written.json()["deliverable"]["source"] == "body"


def test_outline_and_body_can_coexist_and_are_distinguishable(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """同一任务同时有大纲导出与正文成品：两条记录、两个文件、文件名各自身份清楚。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, start_fill=True)

    outline = grilling_client.post(f"/api/tasks/{task_id}/generations", json={})
    assert outline.status_code == 201
    body = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")
    assert body.status_code == 200

    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, source, file_path FROM generations WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    sources = [row["source"] for row in rows]
    assert sources == ["outline", "body"]

    names = [_file_name(row["file_path"]) for row in rows]
    assert names[0].startswith(OUTLINE_FILE_PREFIX)
    assert names[1].startswith(BODY_FILE_PREFIX)
    # 两个文件都真实存在且互不相同。
    assert len(set(names)) == 2
    assert all(Path(row["file_path"]).is_file() for row in rows)


def test_outline_export_does_not_require_a_fill_task(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """跳过填充也能立刻拿到文件：不需要先建填充任务，也不调模型。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/generations", json={})

    assert response.status_code == 201
    # 导出是确定性渲染，不调模型。
    assert len(scripted_model_client.calls) == calls_before


def test_outline_file_name_still_carries_plan_id_and_timestamp(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """前缀之外保留既有的「方案号 + 时间戳」结构，同秒重复导出也不覆盖已有文件。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    first = grilling_client.post(f"/api/tasks/{task_id}/generations", json={})
    second = grilling_client.post(f"/api/tasks/{task_id}/generations", json={})

    assert first.status_code == 201
    assert second.status_code == 201
    first_name = _file_name(first.json()["file_path"])
    second_name = _file_name(second.json()["file_path"])
    assert first_name != second_name
    assert first_name.startswith(f"{OUTLINE_FILE_PREFIX}plan-")
    assert first_name.endswith(".docx")
