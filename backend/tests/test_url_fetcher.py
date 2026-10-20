"""TB-9 真实 URL 抓取器（`HttpUrlFetcher`）的行为测试。

接缝 = `UrlFetcher.fetch`（fake 注入点 2 的协议）。**不联网**：HTTP 走
`httpx.MockTransport` 拦截，DNS 走注入的假解析器；两者都不触碰真实网络。
覆盖：重定向每一跳重新校验（含跳到私网）、重定向超限、需登录 / 权限、超时、
下载超限、元数据记录。
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.url_fetcher import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    FetchedPage,
    HttpUrlFetcher,
    UnconfiguredUrlFetcher,
    UrlFetcher,
    UrlFetchError,
)

PUBLIC_ADDRESS = "93.184.216.34"


def _public(host: str, port: int) -> list[str]:
    """任何域名都解析到公网地址（真实实现与解析解耦，测试才确定）。"""
    return [PUBLIC_ADDRESS]


def _resolver_returning(*addresses: str):
    return lambda host, port: list(addresses)


def _fetcher(handler, *, resolver=_public) -> HttpUrlFetcher:
    """用 MockTransport 造一个真实抓取器（不发真实请求）。"""
    transport = httpx.MockTransport(handler)
    return HttpUrlFetcher(
        resolver=resolver,
        client_factory=lambda: httpx.Client(transport=transport, follow_redirects=False),
    )


def test_fetches_page_and_records_metadata() -> None:
    """正常抓取：正文入库前先拿到 final_url / status / content_type / size / 时间。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content="<html><body><p>正文</p></body></html>".encode(),
        )

    page = _fetcher(handler).fetch("https://example.com/post")

    assert isinstance(page, FetchedPage)
    assert page.status == 200
    assert page.final_url == "https://example.com/post"
    assert page.content_type == "text/html; charset=utf-8"
    assert page.size == len(page.body)
    assert page.redirects == 0
    assert page.fetched_at  # ISO 时间戳，供来源元数据留痕


def test_follows_redirect_within_limit_and_records_final_url() -> None:
    """一次重定向：跟随并记录最终地址（来源元数据里 final_url ≠ 原始地址）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>x</p>")

    page = _fetcher(handler).fetch("https://example.com/old")

    assert page.redirects == 1
    assert page.final_url == "https://example.com/new"


def test_redirect_to_private_address_is_revalidated_and_blocked() -> None:
    """重定向到私网地址 → 每一跳重新校验并拦下（不跟着跳进内网）。"""
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://10.0.0.1/secret"})

    fetcher = _fetcher(handler)

    with pytest.raises(UrlFetchError) as excinfo:
        fetcher.fetch("https://example.com/start")

    assert excinfo.value.reason == "blocked_address"
    assert "内网" in str(excinfo.value)
    # 只发出了第一次请求；私网目标在发起前就被拦。
    assert hits == ["https://example.com/start"]


def test_redirect_beyond_limit_is_refused() -> None:
    """重定向超过 3 次 → 明确拒绝，不无限跟随。"""

    def handler(request: httpx.Request) -> httpx.Response:
        step = int(request.url.path.strip("/") or "1")
        return httpx.Response(302, headers={"location": f"/{step + 1}"})

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("https://example.com/1")

    assert excinfo.value.reason == "redirect_limit"
    assert "重定向" in str(excinfo.value)


def test_literal_private_address_is_blocked_before_any_request() -> None:
    """初始地址就是内网 → 一次请求都不发。"""
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return httpx.Response(200, content=b"<p>x</p>")

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("http://192.168.1.5/admin")

    assert excinfo.value.reason == "blocked_address"
    assert hits == []


def test_hostname_resolving_to_loopback_is_blocked() -> None:
    """域名解析到环回（DNS rebinding）→ 拦在请求之前。"""
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return httpx.Response(200, content=b"<p>x</p>")

    fetcher = _fetcher(handler, resolver=_resolver_returning("127.0.0.1"))

    with pytest.raises(UrlFetchError) as excinfo:
        fetcher.fetch("http://internal-looking.example/")

    assert excinfo.value.reason == "blocked_address"
    assert "环回" in str(excinfo.value)
    assert hits == []


def test_metadata_address_is_blocked_with_reason() -> None:
    """云元数据地址 → 拒绝原因直指元数据（演示证据要求）。"""
    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(lambda request: httpx.Response(200)).fetch(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
        )

    assert excinfo.value.reason == "blocked_address"
    assert "元数据" in str(excinfo.value)


@pytest.mark.parametrize("status_code", [401, 403, 407])
def test_login_required_statuses_report_readable_message(status_code: int) -> None:
    """401 / 403 / 407 → 「需登录或无权访问」如实提示，绝不绕过。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=b"denied")

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("https://example.com/private")

    assert excinfo.value.reason == "login_required"
    assert "登录" in str(excinfo.value) or "权限" in str(excinfo.value)


def test_other_http_errors_report_status() -> None:
    """5xx 等其它错误 → 带状态码的可读提示。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"busy")

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("https://example.com/")

    assert excinfo.value.reason == "http_error"
    assert "503" in str(excinfo.value)


def test_timeout_is_reported_as_timeout() -> None:
    """超时 → 明确「超时」提示（上限 15s，测试注入 fake 传输层模拟）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("模拟：读取超时")

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("https://slow.example/")

    assert excinfo.value.reason == "timeout"
    assert "超时" in str(excinfo.value)


def test_network_error_is_reported_readably() -> None:
    """连接失败 / DNS 之外的网络异常 → 可读提示，不抛出原始异常。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("模拟：连接被拒绝")

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("https://down.example/")

    assert excinfo.value.reason == "network_error"
    assert "连接" in str(excinfo.value) or "网络" in str(excinfo.value)


def test_body_over_limit_is_refused() -> None:
    """下载超过上限 → 拒绝（默认 5MB，测试用更小上限走同一段真实逻辑）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"a" * 2048)

    with pytest.raises(UrlFetchError) as excinfo:
        _fetcher(handler).fetch("https://example.com/big", max_bytes=1024)

    assert excinfo.value.reason == "body_too_large"
    assert "上限" in str(excinfo.value)


def test_non_html_body_is_returned_as_is() -> None:
    """非 HTML 正文也照原样返回（能否提炼由正文提取层判断，不在抓取层猜）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"plain")

    page = _fetcher(handler).fetch("https://example.com/raw.txt")

    assert page.body == b"plain"
    assert page.content_type == "text/plain"


def test_defaults_match_spec() -> None:
    """默认边界 = 规格 §2：超时 15s、下载 5MB。"""
    assert DEFAULT_TIMEOUT_SECONDS == 15.0
    assert DEFAULT_MAX_BYTES == 5 * 1024 * 1024


def test_protocol_and_unconfigured_fetcher() -> None:
    """接缝一致性：真实抓取器满足协议；未配置占位实现显式失败。"""
    assert isinstance(_fetcher(lambda request: httpx.Response(200)), UrlFetcher)

    with pytest.raises(NotImplementedError):
        UnconfiguredUrlFetcher().fetch("https://example.com/")
