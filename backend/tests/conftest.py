"""TB-0 测试夹具：唯一接缝 = 进程内 HTTP 客户端。

所有测试通过 FastAPI 的进程内客户端（`TestClient`，底层 httpx.ASGITransport）
驱动，不起真实端口、不开浏览器、不联网；数据库指向 pytest 的临时目录，
与运行时的 data/ 完全隔离。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import (
    FakeEmbeddingClient,
    FakeUrlFetcher,
    InMemoryKeyStore,
    ScriptedModelClient,
    ScriptedModelClientFactory,
)
from fastapi.testclient import TestClient

from app.api.deps import get_key_store, get_model_client
from app.db.provider_repository import ProviderRepository
from app.main import create_app
from app.providers.tiered_client import TieredModelClient


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
def embedding_client() -> FakeEmbeddingClient:
    """嵌入客户端替身（fake 注入点 3）：确定性假向量，测试绝不真调百炼。"""
    return FakeEmbeddingClient()


@pytest.fixture
def app(
    db_path: Path,
    key_store: InMemoryKeyStore,
    data_dir: Path,
    templates_dir: Path,
    embedding_client: FakeEmbeddingClient,
):
    """按可配置库路径构建应用实例（同一进程内多次重建，用于续作语义验证）。

    密钥存储接缝经 `dependency_overrides` 注入内存替身（与 TB-0 的接缝风格一致）；
    数据目录与模板目录指向 pytest 临时目录，测试不写仓库 `data/`、`templates/`。
    嵌入客户端默认也换成替身：任何测试都不该真的连上百炼（离线、零费用）。
    """
    application = create_app(
        db_path=db_path,
        mount_frontend=False,
        data_dir=data_dir,
        templates_dir=templates_dir,
    )
    application.dependency_overrides[get_key_store] = lambda: key_store
    application.state.embedding_client = embedding_client
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


@pytest.fixture
def scripted_model_client_factory(
    scripted_model_client: ScriptedModelClient,
) -> ScriptedModelClientFactory:
    """记录配置、固定返回同一替身客户端的工厂（验证档位解析用）。"""
    return ScriptedModelClientFactory(scripted_model_client)


@pytest.fixture
def analysis_app(
    app,
    scripted_model_client_factory: ScriptedModelClientFactory,
    key_store: InMemoryKeyStore,
    db_path: Path,
):
    """在既有 app 上把「按档位解析」的模型客户端换成脚本化替身。

    主流程（拷问 / 方案）仍走 `get_model_client` 的 fake；本夹具只替换资料分析的
    档位解析器——两者互不影响，正好钉住「主流程行为不变」。
    """
    app.state.tiered_model_client = TieredModelClient(
        ProviderRepository(db_path),
        key_store,
        scripted_model_client_factory,
    )
    return app


@pytest.fixture
def analysis_client(analysis_app) -> Iterator[TestClient]:
    """资料分析测试用的进程内 HTTP 客户端（lifespan 会播种三档 provider）。"""
    with TestClient(analysis_app) as test_client:
        yield test_client


@pytest.fixture
def url_fetcher() -> FakeUrlFetcher:
    """URL 抓取替身（fake 注入点 2），测试按需预置页面或失败。"""
    return FakeUrlFetcher()


@pytest.fixture
def url_app(analysis_app, url_fetcher: FakeUrlFetcher):
    """在分析用 app 上把 URL 抓取器换成替身：URL 分析测试全程离线。"""
    analysis_app.state.url_fetcher = url_fetcher
    return analysis_app


@pytest.fixture
def url_client(url_app) -> Iterator[TestClient]:
    """URL 分析测试用的进程内 HTTP 客户端。"""
    with TestClient(url_app) as test_client:
        yield test_client
