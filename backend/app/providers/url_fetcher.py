"""URL 抓取接缝（fake 注入点 2）：协议 + 真实实现 + 安全边界。

业务代码只依赖 `UrlFetcher` 协议；真实实现 `HttpUrlFetcher` 在每次请求前与**每一跳
重定向**后都调用 `app.security.url_guard.validate_url` 重新校验，以缓解 DNS rebinding
（连接前后复核）；仍有解析 / 连接之间的 TOCTOU 窗口，见工单 18 遗留风险。同时强制
超时与下载大小上限。抓取结论一律是 `FetchedPage`（含
`final_url` / `status` / `content_type` / `size` / `fetched_at` 元数据）或带可读原因的
`UrlFetchError`——**绝不绕过**站点权限边界，也绝不用空内容冒充成功。

测试经 `dependency_overrides[get_url_fetcher]` 注入假响应，全程不联网；真实实现自身
的行为由 `httpx.MockTransport` 覆盖（同样不联网）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin

import httpx

from app.security.url_guard import (
    MAX_REDIRECTS,
    AddressResolver,
    UrlSecurityError,
    validate_url,
)

# 安全边界默认值（规格 08 / 约定 10）：超时 15s、下载上限 5MB。
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024

# 重定向状态码（手动跟随，才能逐跳重新校验）。
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
# 需登录 / 无权访问：如实提示，不做任何绕过尝试（不带 Cookie 试探、不改 UA 伪装）。
_LOGIN_STATUSES = frozenset({401, 403, 407})

# 取自真实浏览器的普通 UA，避免把「默认库 UA」当成被拒原因。
_USER_AGENT = "Mozilla/5.0 (compatible; ThinkForge/0.1; +local-workbench)"

FETCH_ERROR_TEXT = {
    "blocked_address": "该地址被安全策略拒绝",
    "redirect_limit": "重定向次数超过上限",
    "timeout": "抓取超时",
    "login_required": "页面需登录或无权访问",
    "http_error": "页面返回错误状态",
    "body_too_large": "网页内容超过下载上限",
    "network_error": "网络连接失败",
}


class UrlFetchError(Exception):
    """抓取被拒 / 失败（可读中文 `message` + 机器可读 `reason`）。"""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class FetchedPage:
    """一次抓取的结果：正文字节 + 如实记录的元数据。"""

    url: str
    final_url: str
    status: int
    content_type: str | None
    body: bytes
    fetched_at: str
    redirects: int = 0

    @property
    def size(self) -> int:
        """下载字节数（落进来源元数据）。"""
        return len(self.body)


@runtime_checkable
class UrlFetcher(Protocol):
    """公开网页 URL 抓取抽象。"""

    def fetch(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> FetchedPage:
        """抓取 URL 内容并返回正文与元数据。"""
        ...


class UnconfiguredUrlFetcher:
    """未配置抓取器时的占位实现：显式失败，绝不发起真实请求。"""

    def fetch(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> FetchedPage:
        raise NotImplementedError("URL 抓取器尚未配置（TB-9 落地真实实现）")


class HttpUrlFetcher:
    """真实抓取器：httpx 手动跟随重定向 + 逐跳安全校验 + 超时 / 大小上限。

    注入接缝：`resolver`（域名解析，测试离线）与 `client_factory`（HTTP 客户端，
    测试用 `httpx.MockTransport`）。二者默认都是真实实现。
    """

    def __init__(
        self,
        *,
        resolver: AddressResolver | None = None,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._resolver = resolver
        self._client_factory = client_factory or _default_client

    def fetch(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> FetchedPage:
        """抓取 URL：重定向最多 3 跳，每跳先校验再请求；超限 / 超时如实报错。"""
        client = self._client_factory()
        try:
            return self._fetch(client, url, timeout=timeout, max_bytes=max_bytes)
        finally:
            client.close()

    # --- 内部 ---------------------------------------------------------------

    def _fetch(
        self, client: httpx.Client, url: str, *, timeout: float, max_bytes: int
    ) -> FetchedPage:
        current = url
        redirects = 0

        while True:
            validated = self._validate(current)
            try:
                with client.stream(
                    "GET",
                    validated.url,
                    timeout=timeout,
                    headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*"},
                ) as response:
                    position = response.headers.get("location")
                    if response.status_code in _REDIRECT_STATUSES:
                        if redirects >= MAX_REDIRECTS:
                            raise UrlFetchError(
                                f"{FETCH_ERROR_TEXT['redirect_limit']}"
                                f"（最多 {MAX_REDIRECTS} 次）：{url}",
                                reason="redirect_limit",
                            )
                        if not position:
                            raise UrlFetchError(
                                f"页面要求跳转但未给出目标地址（{response.status_code}）："
                                f"{current}",
                                reason="http_error",
                            )
                        current = urljoin(str(response.url), position)
                        redirects += 1
                        continue

                    if response.status_code in _LOGIN_STATUSES:
                        raise UrlFetchError(
                            f"{FETCH_ERROR_TEXT['login_required']}"
                            f"（HTTP {response.status_code}）：请改用可公开访问的页面，"
                            "本系统不绕过登录或访问控制",
                            reason="login_required",
                        )
                    if response.status_code >= 400:
                        raise UrlFetchError(
                            f"{FETCH_ERROR_TEXT['http_error']}"
                            f"（HTTP {response.status_code}）：{current}",
                            reason="http_error",
                        )

                    body = self._read_limited(response, max_bytes=max_bytes, url=current)
                    return FetchedPage(
                        url=url,
                        final_url=str(response.url),
                        status=response.status_code,
                        content_type=response.headers.get("content-type"),
                        body=body,
                        fetched_at=datetime.now(UTC).isoformat(),
                        redirects=redirects,
                    )
            except httpx.TimeoutException as exc:
                raise UrlFetchError(
                    f"{FETCH_ERROR_TEXT['timeout']}（上限 {timeout:g} 秒）：{current}",
                    reason="timeout",
                ) from exc
            except httpx.HTTPError as exc:
                raise UrlFetchError(
                    f"{FETCH_ERROR_TEXT['network_error']}（{type(exc).__name__}）：{current}",
                    reason="network_error",
                ) from exc

    def _validate(self, url: str):
        """安全校验：不通过时翻译成抓取错误（携带可读原因，供前端展示）。"""
        try:
            return validate_url(url, resolver=self._resolver)
        except UrlSecurityError as exc:
            raise UrlFetchError(str(exc), reason="blocked_address") from exc

    @staticmethod
    def _read_limited(
        response: httpx.Response, *, max_bytes: int, url: str
    ) -> bytes:
        """流式读取并强制大小上限；超限即中止，不把超大响应读进内存。"""
        limit_mb = max(1, max_bytes // (1024 * 1024))
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise UrlFetchError(
                    f"{FETCH_ERROR_TEXT['body_too_large']}"
                    f"（上限 {limit_mb} MB）：{url}",
                    reason="body_too_large",
                )
            chunks.append(chunk)
        return b"".join(chunks)


def _default_client() -> httpx.Client:
    """生产客户端：不自动跟随重定向（逐跳校验必须自己控制）。"""
    return httpx.Client(follow_redirects=False, timeout=DEFAULT_TIMEOUT_SECONDS)
