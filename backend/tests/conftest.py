"""TB-0 测试夹具：唯一接缝 = 进程内 HTTP 客户端。

所有测试通过 FastAPI 的进程内客户端（`TestClient`，底层 httpx.ASGITransport）
驱动，不起真实端口、不开浏览器、不联网；数据库指向 pytest 的临时目录，
与运行时的 data/ 完全隔离。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import InMemoryKeyStore, ScriptedModelClient
from fastapi.testclient import TestClient

from app.api.deps import get_key_store, get_model_client
from app.main import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """每个测试使用独立的临时 SQLite 库，互不干扰。"""
    return tmp_path / "thinkforge-test.db"


@pytest.fixture
def key_store() -> InMemoryKeyStore:
    """内存密钥库替身；测试永不触碰 Windows 凭据管理器。"""
    return InMemoryKeyStore()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """每个测试独立的运行时数据目录（成品落此处），与仓库 data/ 隔离。"""
    return tmp_path / "data"


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """每个测试独立的模板目录（含内置默认模板），与仓库 templates/ 隔离。"""
    return tmp_path / "templates"


@pytest.fixture
def app(db_path: Path, key_store: InMemoryKeyStore, data_dir: Path, templates_dir: Path):
    """按可配置库路径构建应用实例（同一进程内多次重建，用于续作语义验证）。

    密钥存储接缝经 `dependency_overrides` 注入内存替身（与 TB-0 的接缝风格一致）；
    数据目录与模板目录指向 pytest 临时目录，测试不写仓库 `data/`、`templates/`。
    """
    application = create_app(
        db_path=db_path,
        mount_frontend=False,
        data_dir=data_dir,
        templates_dir=templates_dir,
    )
    application.dependency_overrides[get_key_store] = lambda: key_store
    return application


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    """进程内 HTTP 客户端；上下文管理器会触发应用 lifespan（建表）。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def scripted_model_client() -> ScriptedModelClient:
    """脚本化模型客户端（fake 注入点）；默认返回空前沿，测试按需 set_result。"""
    return ScriptedModelClient(result='{"frontier": []}')


@pytest.fixture
def grilling_app(app, scripted_model_client: ScriptedModelClient):
    """在既有 app 上把模型客户端替换为脚本化 fake（拷问接缝测试用）。"""
    app.dependency_overrides[get_model_client] = lambda: scripted_model_client
    return app


@pytest.fixture
def grilling_client(grilling_app) -> Iterator[TestClient]:
    """注入 fake 模型客户端后的进程内 HTTP 客户端。"""
    with TestClient(grilling_app) as test_client:
        yield test_client
