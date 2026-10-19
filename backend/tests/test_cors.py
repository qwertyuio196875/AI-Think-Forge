"""TB-1 追加：仅开发用的 CORS（本机 Vite 源）。

前端开发服务器不做代理、浏览器跨源直连后端，故后端只放行本机开发源
（`http://localhost:5173` / `http://127.0.0.1:5173`）；未在允许列表的来源
不得拿到 `access-control-allow-origin`，且不使用通配来源。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DISALLOWED_ORIGIN = "http://evil.example"


def test_preflight_from_dev_origin_is_allowed(client: TestClient) -> None:
    """5173 源的预检被放行，回该来源的 allow-origin。"""
    response = client.options(
        "/api/providers",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_actual_request_from_dev_origins_has_allow_origin(client: TestClient) -> None:
    """两个本机开发源的实际请求都带 allow-origin。"""
    for origin in ALLOWED_ORIGINS:
        response = client.get("/api/providers", headers={"Origin": origin})

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin


def test_disallowed_origin_gets_no_allow_origin_header(client: TestClient) -> None:
    """未在允许列表的来源拿不到 allow-origin。"""
    response = client.get("/api/providers", headers={"Origin": DISALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_disallowed_origin_preflight_is_not_allowed(client: TestClient) -> None:
    """未在允许列表的来源预检同样不被放行。"""
    response = client.options(
        "/api/providers",
        headers={"Origin": DISALLOWED_ORIGIN, "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_never_uses_wildcard(client: TestClient) -> None:
    """绝不用通配来源。"""
    response = client.get("/api/providers", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] != "*"