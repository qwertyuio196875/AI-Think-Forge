"""健康检查接缝测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """GET /api/health 返回 200 且 status 为 ok。"""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
