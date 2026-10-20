"""任务接缝测试：创建 / 回读 / 列表过滤 / 续作 / 404。

断言只覆盖规格允许的三类可观察结果中的前两类：
① API 返回的任务状态；② 持久化数据（重建 app 与客户端后再读）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

TASK_FIELDS = {
    "id",
    "kind",
    "title",
    "status",
    "provider_id",
    "created_at",
    "updated_at",
}


def test_create_task_returns_201_and_fields(client: TestClient) -> None:
    """创建任务返回 201 与固定的 Task JSON 字段集。"""
    response = client.post("/api/tasks", json={"kind": "creation", "title": "写一篇产品介绍"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == TASK_FIELDS
    assert body["kind"] == "creation"
    assert body["title"] == "写一篇产品介绍"
    assert body["status"] == "in_progress"
    assert isinstance(body["id"], int)
    # 时间戳为 ISO8601 字符串
    assert "T" in body["created_at"]
    assert "T" in body["updated_at"]


def test_create_task_without_title_defaults_to_null(client: TestClient) -> None:
    """title 允许缺省（规格 §4 最小集），缺省时为 null。"""
    response = client.post("/api/tasks", json={"kind": "analysis"})

    assert response.status_code == 201
    assert response.json()["title"] is None


def test_create_task_rejects_unknown_kind(client: TestClient) -> None:
    """kind 只允许 creation / analysis，其它取值被校验拒绝。"""
    response = client.post("/api/tasks", json={"kind": "unknown"})

    assert response.status_code == 422


def test_read_back_matches_created(client: TestClient) -> None:
    """按 id 回读的字段与创建响应一致。"""
    created = client.post("/api/tasks", json={"kind": "analysis", "title": "读一份 PDF"}).json()

    response = client.get(f"/api/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_list_returns_items_and_total(client: TestClient) -> None:
    """无过滤时返回全部任务与正确 total。"""
    client.post("/api/tasks", json={"kind": "creation", "title": "A"})
    client.post("/api/tasks", json={"kind": "analysis", "title": "B"})
    client.post("/api/tasks", json={"kind": "creation", "title": "C"})

    response = client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["title"] for item in body["items"]] == ["A", "B", "C"]


def test_list_filters_by_kind_and_status(client: TestClient) -> None:
    """kind / status 过滤生效，total 反映过滤后的数量。"""
    client.post("/api/tasks", json={"kind": "creation", "title": "A"})
    client.post("/api/tasks", json={"kind": "analysis", "title": "B"})
    client.post("/api/tasks", json={"kind": "creation", "title": "C"})

    creation = client.get("/api/tasks", params={"kind": "creation"}).json()
    assert creation["total"] == 2
    assert {item["kind"] for item in creation["items"]} == {"creation"}

    in_progress = client.get("/api/tasks", params={"status": "in_progress"}).json()
    assert in_progress["total"] == 3

    deleted = client.get("/api/tasks", params={"status": "deleted"}).json()
    assert deleted["total"] == 0
    assert deleted["items"] == []


def test_get_missing_task_returns_404(client: TestClient) -> None:
    """读取不存在的任务返回 404 且带 detail。"""
    response = client.get("/api/tasks/9999")

    assert response.status_code == 404
    assert "detail" in response.json()


def test_task_survives_app_and_client_rebuild(db_path: Path) -> None:
    """续作语义最小证明：重建 app 与客户端后任务仍在（持久化生效）。"""
    first_app = create_app(db_path=db_path)
    with TestClient(first_app) as first_client:
        created = first_client.post(
            "/api/tasks", json={"kind": "creation", "title": "关掉重开仍在"}
        ).json()

    second_app = create_app(db_path=db_path)
    with TestClient(second_app) as second_client:
        response = second_client.get(f"/api/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created

    # 列表也应看到这条任务
    with TestClient(create_app(db_path=db_path)) as third_client:
        assert third_client.get("/api/tasks").json()["total"] == 1
