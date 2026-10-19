"""TB-9 URL 安全校验器（SSRF 防护）的纯函数负测。

接缝 = `app.security.url_guard` 的公开纯函数（`validate_url` / `classify_address`），
不经 HTTP、不联网：域名解析以注入的 resolver 代替真实 DNS，字面量 IP 用例则用
「一旦被调用即断言失败」的 resolver 钉住「解析前就拦住」。
"""

from __future__ import annotations

import socket

import pytest

from app.security.url_guard import (
    MAX_REDIRECTS,
    UrlSecurityError,
    classify_address,
    validate_url,
)


def _no_dns(host: str, port: int) -> list[str]:
    """字面量地址不应触发解析：被调用即失败。"""
    raise AssertionError(f"不该对 {host}:{port} 发起解析")


def _resolver_returning(*addresses: str):
    def resolve(host: str, port: int) -> list[str]:
        resolve.calls.append((host, port))  # type: ignore[attr-defined]
        return list(addresses)

    resolve.calls = []  # type: ignore[attr-defined]
    return resolve


# --- 地址分类（纯函数，逐类负测） ---------------------------------------------


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("127.0.0.1", "loopback"),
        ("127.255.255.254", "loopback"),
        ("10.1.2.3", "private"),
        ("172.16.5.5", "private"),
        ("172.31.255.254", "private"),
        ("192.168.1.1", "private"),
        ("169.254.1.1", "link_local"),
        ("169.254.169.254", "metadata"),
        ("0.0.0.0", "unspecified"),
        ("224.0.0.1", "multicast"),
        ("239.255.255.250", "multicast"),
        ("240.0.0.1", "reserved"),
        ("255.255.255.255", "reserved"),
        ("100.64.0.1", "private"),
        ("::1", "loopback"),
        ("::", "unspecified"),
        ("fc00::1", "private"),
        ("fd00::1", "private"),
        ("fd00:ec2::254", "metadata"),
        ("fe80::1", "link_local"),
        ("ff02::1", "multicast"),
        ("2001:db8::1", "reserved"),
        ("::ffff:127.0.0.1", "loopback"),
        ("::ffff:10.0.0.1", "private"),
    ],
)
def test_blocked_addresses_are_classified(address: str, reason: str) -> None:
    """禁止地址按类别命中（环回 / 私网 / 链路本地 / 元数据 / 未指定 / 组播 / 保留）。"""
    assert classify_address(address) == reason


@pytest.mark.parametrize(
    "address",
    ["93.184.216.34", "1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"],
)
def test_public_addresses_are_allowed(address: str) -> None:
    """公网地址不被拦（避免「一律拒绝」把功能一起掐死）。"""
    assert classify_address(address) is None


# --- 协议与凭据 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/a",
        "file:///etc/passwd",
        "gopher://example.com/",
        "data:text/html,<h1>x</h1>",
        "javascript:alert(1)",
        "example.com/a",
        "//example.com/a",
        "",
        "   ",
    ],
)
def test_rejects_non_http_scheme(url: str) -> None:
    """只允许 http/https；其余协议（含缺协议）明确拒绝。"""
    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url(url, resolver=_no_dns)

    assert excinfo.value.reason == "scheme_not_allowed"
    assert "http" in str(excinfo.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:secret@example.com/a",
        "https://user@example.com/a",
        "http://example.com@10.0.0.1/a",
    ],
)
def test_rejects_embedded_credentials(url: str) -> None:
    """URL 内嵌用户名 / 密码 → 拒绝（凭据不进抓取器、不进日志）。"""
    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url(url, resolver=_no_dns)

    assert excinfo.value.reason == "credentials_not_allowed"
    assert "用户名" in str(excinfo.value) or "密码" in str(excinfo.value)


# --- 解析前：字面量地址 -------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "reason", "readable"),
    [
        ("http://127.0.0.1/", "loopback", "环回"),
        ("http://127.1.2.3:8080/x", "loopback", "环回"),
        ("https://[::1]/", "loopback", "环回"),
        ("http://10.0.0.5/", "private", "内网"),
        ("http://172.16.0.1/", "private", "内网"),
        ("http://192.168.1.10/", "private", "内网"),
        ("http://[fd00::1]/", "private", "内网"),
        ("http://169.254.1.1/", "link_local", "链路本地"),
        ("http://[fe80::1]/", "link_local", "链路本地"),
        ("http://169.254.169.254/latest/meta-data/", "metadata", "元数据"),
        ("http://[fd00:ec2::254]/", "metadata", "元数据"),
        ("http://0.0.0.0/", "unspecified", "未指定"),
        ("http://224.0.0.1/", "multicast", "组播"),
        ("http://240.0.0.1/", "reserved", "保留"),
    ],
)
def test_rejects_forbidden_literal_addresses_without_dns(
    url: str, reason: str, readable: str
) -> None:
    """字面量禁止地址在解析前就被拦（不依赖 DNS，提示可读）。"""
    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url(url, resolver=_no_dns)

    assert excinfo.value.reason == reason
    assert readable in str(excinfo.value)
    assert excinfo.value.status_code == 400


# --- 解析后：DNS 结果（防 DNS rebinding） -------------------------------------


@pytest.mark.parametrize(
    ("address", "reason", "readable"),
    [
        ("127.0.0.1", "loopback", "环回"),
        ("10.0.0.1", "private", "内网"),
        ("169.254.169.254", "metadata", "元数据"),
        ("fe80::1", "link_local", "链路本地"),
    ],
)
def test_rejects_hostname_resolving_to_forbidden_address(
    address: str, reason: str, readable: str
) -> None:
    """域名解析到禁止地址 → 拦截（解析后二次校验，防 DNS rebinding）。"""
    resolver = _resolver_returning(address)

    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url("http://public-looking.example/page", resolver=resolver)

    assert excinfo.value.reason == reason
    assert readable in str(excinfo.value)


def test_rejects_when_any_resolved_address_is_forbidden() -> None:
    """解析出多个地址时，任一命中禁止段即整体拒绝（不挑好走的那个）。"""
    resolver = _resolver_returning("93.184.216.34", "10.0.0.1")

    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url("http://mixed.example/", resolver=resolver)

    assert excinfo.value.reason == "private"


def test_allows_hostname_resolving_to_public_address() -> None:
    """解析到公网地址 → 放行，并把实际解析到的地址回传（可观测）。"""
    resolver = _resolver_returning("93.184.216.34")

    validated = validate_url("https://example.com/article?x=1", resolver=resolver)

    assert validated.scheme == "https"
    assert validated.host == "example.com"
    assert validated.port == 443
    assert validated.addresses == ("93.184.216.34",)
    assert resolver.calls == [("example.com", 443)]  # type: ignore[attr-defined]


def test_rejects_dns_failure_with_readable_message() -> None:
    """解析失败（域名不存在 / DNS 不可用）→ 可读拒绝，不是静默放行。"""

    def failing(host: str, port: int) -> list[str]:
        raise socket.gaierror("Name or service not known")

    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url("http://nonexistent.invalid/", resolver=failing)

    assert excinfo.value.reason == "dns_failure"
    assert "解析" in str(excinfo.value)


def test_http_default_port_and_explicit_port_are_kept() -> None:
    """默认端口按协议补全（80 / 443），显式端口原样保留。"""
    resolver = _resolver_returning("93.184.216.34")
    assert validate_url("http://example.com/", resolver=resolver).port == 80
    assert (
        validate_url("http://example.com:8080/", resolver=resolver).port == 8080
    )


def test_redirect_limit_constant_is_three() -> None:
    """重定向上限 = 3（规格 §2）。"""
    assert MAX_REDIRECTS == 3


def test_precheck_mode_skips_dns_but_keeps_literal_checks() -> None:
    """`resolve=False`（路由层前置拒绝）不发起 DNS，但仍拦字面量禁止地址与非法形态。"""
    validated = validate_url("http://example.com/page", resolver=_no_dns, resolve=False)
    assert validated.host == "example.com"
    assert validated.addresses == ()

    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url("http://10.0.0.1/", resolver=_no_dns, resolve=False)
    assert excinfo.value.reason == "private"

    with pytest.raises(UrlSecurityError) as excinfo:
        validate_url("ftp://example.com/", resolver=_no_dns, resolve=False)
    assert excinfo.value.reason == "scheme_not_allowed"
