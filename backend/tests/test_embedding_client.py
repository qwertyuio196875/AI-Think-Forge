"""嵌入客户端适配层（工单 20）测试：只验外部行为，全程用 MockTransport 离线。

同类先例见 `test_model_client.py`：注入 `httpx.Client(transport=MockTransport)`，
断言真实请求路径 / 请求体 / 鉴权头，以及失败如何收敛成可读错误——**不联网、
不真调百炼**，也不产生任何费用。
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.providers.embedding_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_NAME,
    ConfiguredEmbeddingClient,
    EmbeddingCallError,
    EmbeddingDimensionError,
    OpenAICompatibleEmbeddingClient,
    embeddings_url,
)

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _client(handler, *, base_url: str = BASE_URL) -> OpenAICompatibleEmbeddingClient:
    """用 MockTransport 构造客户端：请求不出进程。"""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleEmbeddingClient(
        base_url=base_url,
        model_name=DEFAULT_MODEL_NAME,
        api_key="sk-embedding-secret",
        http_client=http,
    )


def test_embedding_request_shape_and_response_order() -> None:
    """POST 到 /embeddings，带模型与输入；响应按 index 归位，不依赖返回顺序。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [3.0, 4.0]},
                    {"index": 0, "embedding": [1.0, 2.0]},
                ]
            },
        )

    vectors = _client(handler).embed(["第一段", "第二段"])

    assert seen["method"] == "POST"
    assert seen["url"] == f"{BASE_URL}/embeddings"
    assert f'"model":"{DEFAULT_MODEL_NAME}"' in seen["body"]
    assert "第一段" in seen["body"]
    assert seen["authorization"] == "Bearer sk-embedding-secret"
    # 响应乱序返回也必须还原成输入顺序，否则向量会与分块错位。
    assert vectors == [[1.0, 2.0], [3.0, 4.0]]


def test_empty_input_makes_no_request() -> None:
    """空输入不发起请求（避免为 0 条分块白花一次调用）。"""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不该被调用
        raise AssertionError(f"不应发起请求：{request.url}")

    assert _client(handler).embed([]) == []


def test_http_error_is_readable_and_redacted(caplog: pytest.LogCaptureFixture) -> None:
    """HTTP 失败收敛为 EmbeddingCallError，日志里不出现密钥原文。"""
    secret = "sk-embedding-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"bad key {secret}"}})

    with (
        caplog.at_level(logging.WARNING, logger="app.providers.embedding_client"),
        pytest.raises(EmbeddingCallError),
    ):
        _client(handler).embed(["一段文字"])

    assert secret not in caplog.text
    assert "***" in caplog.text


def test_network_error_becomes_embedding_call_error() -> None:
    """网络异常同样收敛为 EmbeddingCallError（上层据此把资料标记索引失败）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(EmbeddingCallError):
        _client(handler).embed(["一段文字"])


def test_malformed_response_becomes_embedding_call_error() -> None:
    """响应缺字段 / 条数不符都算调用失败，不静默返回残缺向量。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})

    with pytest.raises(EmbeddingCallError):
        _client(handler).embed(["第一段", "第二段"])


def test_ragged_response_raises_dimension_error() -> None:
    """同一批向量维度不一致时明确报错，绝不当成可比较的相似度。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 2.0]},
                    {"index": 1, "embedding": [1.0, 2.0, 3.0]},
                ]
            },
        )

    with pytest.raises(EmbeddingDimensionError) as excinfo:
        _client(handler).embed(["第一段", "第二段"])

    assert "维度" in str(excinfo.value)


def test_embeddings_url_tolerates_trailing_slash() -> None:
    """base_url 带不带尾斜杠都拼成同一个端点，不出现 `//embeddings`。"""
    assert embeddings_url("https://example.com/v1/") == "https://example.com/v1/embeddings"
    assert embeddings_url("https://example.com/v1") == "https://example.com/v1/embeddings"


def test_configured_client_requires_api_key() -> None:
    """未配置密钥时给出可读原因（提到该设哪个环境变量），而不是静默无向量。"""
    client = ConfiguredEmbeddingClient(env={})

    with pytest.raises(EmbeddingCallError) as excinfo:
        client.embed(["一段文字"])

    assert "THINKFORGE_EMBEDDING_API_KEY" in str(excinfo.value)


def test_configured_client_uses_environment_settings() -> None:
    """配置齐全时按环境变量里的 base_url / model 发请求，默认值仍可回退。"""

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.25]}]})

    seen: dict = {}
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = ConfiguredEmbeddingClient(
        env={
            "THINKFORGE_EMBEDDING_API_KEY": "sk-env",
            "THINKFORGE_EMBEDDING_BASE_URL": "https://embedding.example.com/v1",
            "THINKFORGE_EMBEDDING_MODEL": "text-embedding-v3",
        },
        http_client=http,
    )

    assert client.embed(["一段文字"]) == [[0.5, 0.25]]
    assert seen["url"] == "https://embedding.example.com/v1/embeddings"
    assert "text-embedding-v3" in seen["body"]
    assert client.model_name == "text-embedding-v3"


def test_configured_client_defaults_to_bailian_embedding() -> None:
    """只配密钥时的默认值就是百炼 text-embedding-v4（ADR-0005）。"""
    client = ConfiguredEmbeddingClient(env={"THINKFORGE_EMBEDDING_API_KEY": "sk-env"})

    assert client.model_name == DEFAULT_MODEL_NAME
    assert DEFAULT_MODEL_NAME == "text-embedding-v4"
    assert DEFAULT_BASE_URL == "https://dashscope.aliyuncs.com/compatible-mode/v1"
