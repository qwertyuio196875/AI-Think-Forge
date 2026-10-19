"""两个 fake 注入点的接缝 smoke 测试。

证明「模型客户端」与「URL 抓取器」两个抽象都能通过 FastAPI 的
`dependency_overrides` 被替换为测试替身（零真实花费、不联网）。
本单不实现业务，只验证接缝可注入。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import ModelClientDep, UrlFetcherDep, get_model_client, get_url_fetcher


class _FakeModelClient:
    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        return "fake-model-response"


class _FakeUrlFetcher:
    def fetch(self, url: str, *, timeout: float = 15.0, max_bytes: int = 5 * 1024 * 1024) -> bytes:
        return b"fake-body"


def _add_type_probe(app) -> None:
    """挂一个只回显依赖类型名的最小探针路由（仅测试期存在）。"""

    @app.get("/api/_seam_probe")
    def probe(model_client: ModelClientDep, url_fetcher: UrlFetcherDep) -> dict[str, str]:
        return {
            "model_client": type(model_client).__name__,
            "url_fetcher": type(url_fetcher).__name__,
        }


def test_seams_defaults_wire_real_implementations(app) -> None:
    """未注入时：模型客户端是按 provider 配置解析的真实实现（接线缺陷修复后），
    URL 抓取器仍为显式失败的占位实现（其实现属后续工单）。"""
    _add_type_probe(app)

    with TestClient(app) as client:
        body = client.get("/api/_seam_probe").json()

    assert body == {
        "model_client": "ProviderBackedModelClient",
        "url_fetcher": "UnconfiguredUrlFetcher",
    }


def test_model_client_can_be_overridden(app) -> None:
    """模型客户端接缝可被 dependency_overrides 替换。"""
    _add_type_probe(app)
    app.dependency_overrides[get_model_client] = lambda: _FakeModelClient()

    with TestClient(app) as client:
        body = client.get("/api/_seam_probe").json()

    assert body["model_client"] == "_FakeModelClient"


def test_url_fetcher_can_be_overridden(app) -> None:
    """URL 抓取器接缝可被 dependency_overrides 替换。"""
    _add_type_probe(app)
    app.dependency_overrides[get_url_fetcher] = lambda: _FakeUrlFetcher()

    with TestClient(app) as client:
        body = client.get("/api/_seam_probe").json()

    assert body["url_fetcher"] == "_FakeUrlFetcher"
