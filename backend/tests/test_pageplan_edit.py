"""页面规划的单页增删（工单 26 / ADR-0004；接缝 = 进程内 HTTP；模型走 fake）。

钉住 issue #26 验收：
1. **预览**：`GET /api/tasks/{task_id}/page-plans/{plan_id}` 回读某次规划（含增删后的
   结果），页面 index 连续；
2. **增页**：`POST .../pages`（after_index 后插入）→ 另存一份新规划，新 `page_plan_id`、
   `actual_pages = 原页数 + 1`，被插入页归属对应章节（正文页复制其章节归属摊开），
   历史规划不改；
3. **删页**：`DELETE .../pages/{at_index}` → 另存一份新规划，`actual_pages = 原页数 − 1`；
4. **封面不可删 / 越界 / 方案闸门**：删封面、越界 → 422；未确认方案 → 409。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient
from tests.test_pageplan_endpoint import _task_filled

from app.db.database import connect


# 复用规划正例的造任务（含全篇填充）。
def _create_plan(client: TestClient, scripted: ScriptedModelClient, task_id: int) -> dict:
    """走一次规划，返回响应体（6 页：封面 + 5 内容页）。"""
    response = client.post(f"/api/tasks/{task_id}/page-plans", json={"target_pages": 6})
    assert response.status_code == 200
    return response.json()


def _plan_rows(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM page_plans WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ).fetchall()
    return [dict(row) for row in rows]


# --- 验收 ①：预览回读 ----------------------------------------------------------


def test_get_page_plan_returns_saved_plan(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)

    response = grilling_client.get(f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["page_plan_id"] == created["page_plan_id"]
    assert body["actual_pages"] == 6
    # index 连续 1..6，封面在前。
    indices = [p["index"] for p in body["pages"]]
    assert indices == list(range(1, 7))
    assert body["pages"][0]["kind"] == "cover"


def test_get_missing_page_plan_404(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    response = grilling_client.get(f"/api/tasks/{task_id}/page-plans/99999")
    assert response.status_code == 404


# --- 验收 ②：增页 --------------------------------------------------------------


def test_add_page_after_content_page_creates_new_plan(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)
    after_index = 2  # 第一张正文页之后

    response = grilling_client.post(
        f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}/pages",
        json={"after_index": after_index},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["actual_pages"] == 7
    assert body["page_plan_id"] != created["page_plan_id"]
    assert [p["index"] for p in body["pages"]] == list(range(1, 8))
    # 插入位置后的那一页归属第 2 页（原来）的章节。
    assert body["pages"][3]["chapter_seqs"] == created["pages"][2]["chapter_seqs"]
    # 历史规划不改，库里有新旧两条（新 id 更大）。
    rows = _plan_rows(db_path, task_id)
    assert len(rows) == 2
    assert rows[-1]["target_pages"] == 7


def test_add_page_after_cover_doubles_first_chapter(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}/pages",
        json={"after_index": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["actual_pages"] == 7
    # 封面后紧接一页正文，归属第一章。
    assert body["pages"][1]["kind"] == "content"
    assert body["pages"][1]["chapter_seqs"] == created["pages"][1]["chapter_seqs"]


def test_add_page_out_of_range_422(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)

    for bad in (0, 99):
        response = grilling_client.post(
            f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}/pages",
            json={"after_index": bad},
        )
        assert response.status_code == 422


# --- 验收 ③：删页 --------------------------------------------------------------


def test_delete_content_page_creates_new_plan(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)

    response = grilling_client.delete(
        f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}/pages/3"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["actual_pages"] == 5
    assert body["page_plan_id"] != created["page_plan_id"]
    assert [p["index"] for p in body["pages"]] == list(range(1, 6))
    # 0-based：删了原 index 3（0-based 2），原第 4 页顺延到新 index 3。
    assert body["pages"][2]["chapter_seqs"] == created["pages"][3]["chapter_seqs"]


def test_delete_cover_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)

    response = grilling_client.delete(
        f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}/pages/1"
    )

    assert response.status_code == 422
    assert "封面不可删除" in response.json()["detail"]


def test_delete_out_of_range_422(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    task_id = _task_filled(grilling_client, scripted_model_client)
    created = _create_plan(grilling_client, scripted_model_client, task_id)

    response = grilling_client.delete(
        f"/api/tasks/{task_id}/page-plans/{created['page_plan_id']}/pages/99"
    )
    assert response.status_code == 422


# --- 验收 ④：闸门 --------------------------------------------------------------


def test_page_edit_rejected_when_plan_not_confirmed(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """增页也受「方案已确认」闸门约束：未确认任务 → 409。"""
    scripted_model_client.set_sequence(
        json.dumps({"frontier": []}, ensure_ascii=False),
    )
    fresh = grilling_client.post("/api/grilling/tasks", json={"idea": "测试"}).json()["task"][
        "id"
    ]
    response = grilling_client.post(
        f"/api/tasks/{fresh}/page-plans/1/pages", json={"after_index": 2}
    )
    assert response.status_code == 409