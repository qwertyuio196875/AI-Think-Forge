"""TB-0 测试夹具：唯一接缝 = 进程内 HTTP 客户端。

所有测试通过 FastAPI 的进程内客户端（`TestClient`，底层 httpx.ASGITransport）
驱动，不起真实端口、不开浏览器、不联网；数据库指向 pytest 的临时目录，
与运行时的 data/ 完全隔离。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """每个测试使用独立的临时 SQLite 库，互不干扰。"""
    return tmp_path / "thinkforge-test.db"


@pytest.fixture
def app(db_path: Path):
    """按可配置库路径构建应用实例（同一进程内多次重建，用于续作语义验证）。"""
    return create_app(db_path=db_path)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    """进程内 HTTP 客户端；上下文管理器会触发应用 lifespan（建表）。"""
    with TestClient(app) as test_client:
        yield test_client
