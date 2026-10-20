"""接线缺陷修复：按 provider 配置解析的模型客户端（`ProviderBackedModelClient`）。

缺陷背景：`app.state.model_client` 曾恒为 `UnconfiguredModelClient`，导致
拷问／方案／修订主链路从未真正调用模型。本文件用**真实**的
`ProviderBackedModelClient` + 真实 `ProviderRepository` + 内存密钥库 + 脚本化
工厂，经进程内 HTTP 驱动，断言「默认 provider 的 base_url / model_name /
密钥」确实抵达工厂（本缺陷的核心断言）。

不联网、零真实花费：工厂与密钥库均为进程内替身。
"""

from __future__ import annotations

import httpx
import pytest
from fakes import ScriptedModelClient, ScriptedModelClientFactory

from app.api.deps import get_model_client
from app.db.provider_repository import ProviderRepository
from app.providers.model_client import ModelCallError, ModelClientConfig
from app.providers.provider_backed_client import ProviderBackedModelClient

TEST_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_PROVIDER_NAME = "DeepSeek 主流程"


def _unauthorized() -> httpx.HTTPStatusError:
    """构造一个 401（DeepSeek 鉴权失败）HTTP 异常。"""
    return httpx.HTTPStatusError(
        "unauthorized",
        request=httpx.Request("POST", TEST_URL),
        response=httpx.Response(
            401,
            text='{"error":{"message":"Authentication Fails","type":"authentication_error"}}',
            request=httpx.Request("POST", TEST_URL),
        ),
    )


def _wire(app, key_store, factory) -> ProviderBackedModelClient:
    """把真实 ProviderBackedModelClient 接到 API 接缝（dependency_overrides）。"""
    client = ProviderBackedModelClient(ProviderRepository(app.state.db_path), key_store, factory)
    app.dependency_overrides[get_model_client] = lambda: client
    return client


def test_grilling_resolves_default_provider_config_and_key(client, app, key_store) -> None:
    """拷问主链路：默认 provider 的 base_url / model_name / 密钥都传到了工厂。"""
    key_store.set_key(DEFAULT_PROVIDER_NAME, "sk-live")
    factory = ScriptedModelClientFactory(ScriptedModelClient(result='{"frontier": []}'))
    _wire(app, key_store, factory)

    response = client.post("/api/grilling/tasks", json={"idea": "写一份新员工手册"})

    assert response.status_code == 201
    assert factory.create_count == 1
    assert factory.last_config == ModelClientConfig(
        base_url="https://api.deepseek.com", model_name="deepseek-flash"
    )
    assert factory.last_api_key == "sk-live"


def test_no_default_provider_returns_readable_502(client, app, key_store) -> None:
    """无默认 provider → 可读的 502，指明去设置页配置，且不构造客户端。"""
    for item in client.get("/api/providers").json()["items"]:
        client.delete(f"/api/providers/{item['id']}")
    factory = ScriptedModelClientFactory(ScriptedModelClient(result='{"frontier": []}'))
    _wire(app, key_store, factory)

    response = client.post("/api/grilling/tasks", json={"idea": "x"})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "设置页" in detail
    assert factory.create_count == 0


def test_no_default_provider_raises_model_call_error(client, app, key_store) -> None:
    """无默认 provider 时抛 `ModelCallError`（不是 `NotImplementedError`）。"""
    for item in client.get("/api/providers").json()["items"]:
        client.delete(f"/api/providers/{item['id']}")
    factory = ScriptedModelClientFactory(ScriptedModelClient(result="ok"))
    local = _wire(app, key_store, factory)

    with pytest.raises(ModelCallError, match="设置页"):
        local.complete([{"role": "user", "content": "hi"}])


def test_missing_key_still_sends_request_with_none(client, app, key_store) -> None:
    """密钥缺失不提前伪造失败：照常发请求（api_key=None），401 归 auth_error。"""
    factory = ScriptedModelClientFactory(ScriptedModelClient(error=_unauthorized()))
    _wire(app, key_store, factory)

    response = client.post("/api/grilling/tasks", json={"idea": "x"})

    assert factory.create_count == 1
    assert factory.last_api_key is None
    assert response.status_code == 502
    assert "Authentication Fails" in response.json()["detail"]


def test_explicit_model_overrides_provider_model_name(client, app, key_store) -> None:
    """调用方显式传入 model 时以调用方为准。"""
    factory = ScriptedModelClientFactory(ScriptedModelClient(result="ok"))
    local = _wire(app, key_store, factory)

    local.complete([{"role": "user", "content": "hi"}], model="deepseek-v4-pro")

    assert factory.last_config.model_name == "deepseek-v4-pro"


def test_provider_model_name_is_default_when_model_not_given(client, app, key_store) -> None:
    """未显式传 model 时用默认 provider 的 model_name。"""
    factory = ScriptedModelClientFactory(ScriptedModelClient(result="ok"))
    local = _wire(app, key_store, factory)

    local.complete([{"role": "user", "content": "hi"}])

    assert factory.last_config.model_name == "deepseek-flash"


def test_default_model_client_is_provider_backed(app) -> None:
    """生产默认模型客户端是按 provider 配置解析的实现，且复用 app.state 协作者。"""
    model_client = app.state.model_client

    assert isinstance(model_client, ProviderBackedModelClient)
    assert model_client.key_store is app.state.key_store
    assert model_client.factory is app.state.model_client_factory