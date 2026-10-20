"""(接缝 smoke 测试。

证明「模型客户端」与「URL 抓取器」两个抽象都能通过 FastAPI 的
`dependency_overrides` 被替换为测试替身（零真实花费、不联网）。
TB-9 已把 URL 抓取器的真实实现接上，此处改为钉住「默认接线是真实实现 +
仍可被替身覆盖」。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import ModelClientDep, UrlFetcherDep, get_model_client, get_url_fetcher
from app.providers.url_fetcher import FetchedPage


class _FakeModelClient:
    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        return "fake-model-response"


class _FakeUrlFetcher:
    def fetch(
        self,
        url: str,
        *,
        timeout: float = 15.0,
        max_bytes: int = 5 * 1024 * 1024,
    ) -> FetchedPage:
        return FetchedPage(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            body=b"fake-body",
            fetched_at="2026-10-19T00:00:00+00:00",
        )


def _add_type_probe(app) -> None:
    """挂一个只回显依赖类型名的最小探针路由（仅测试期存在）。"""

    @app.get("/api/_seam_probe")
    def probe(model_client: ModelClientDep, url_fetcher: UrlFetcherDep) -> dict[str, str]:
        return {
            "model_client": type(model_client).__name__,
            "url_fetcher": type(url_fetcher).__name__,
        }


def test_seams_defaults_wire_real_implementations(app) -> None:
    """未注入时：模型客户端按 provider 配置解析真实实现；URL 抓取器是真实抓取器
    （TB-9 落地：逐跳 SSRF 校验 + 超时 / 大小 / 重定向上限）。"""
    _add_type_probe(app)

    with TestClient(app) as client:
        body = client.get("/api/_seam_probe").json()

    assert body == {
        "model_client": "ProviderBackedModelClient",
        "url_fetcher": "HttpUrlFetcher",
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


def test_seam_fake_model_client_accepts_per_call_parameters() -> None:
    """协议扩容后，接缝替身也得接受按次参数，否则替身会先在测试里崩掉（#3）。"""
    assert (
        _FakeModelClient().complete(
            [{"role": "user", "content": "hi"}], max_tokens=8192, timeout=180.0
        )
        == "fake-model-response"
    )
