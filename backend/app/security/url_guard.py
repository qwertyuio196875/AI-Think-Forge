"""URL 安全校验（SSRF 防护）——**纯函数**，可脱离网络独立负测。

清单来自规格 §2「URL 抓取防护清单」与 US 15：

- 仅 `http` / `https`；拒绝 URL 内嵌用户名 / 密码；
- 封禁环回（127/8、::1）、私网（10/8、172.16/12、192.168/16、fc00::/7 等）、
  链路本地（169.254/16、fe80::/10）、云元数据（169.254.169.254、fd00:ec2::254）、
  未指定（0.0.0.0、::）、组播（224/4、ff00::/8）与保留地址（240/4、2001:db8::/32 等）；
- **解析前 + 解析后双检**：字面量地址直接判，域名先判形态再解析、逐个复核解析结果，
  防止「解析前是公网域名、解析后变成内网地址」的 DNS rebinding；
- 重定向上限 `MAX_REDIRECTS = 3`，抓取器每一跳都重新调用本模块校验（见
  `app.providers.url_fetcher`）。

设计纪律：本模块只做判断，**不发起任何网络请求**；DNS 解析经 `resolver` 注入，
测试全程离线且确定。校验结论一律是显式异常 + 可读中文原因，绝不静默放行。
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# 允许的协议：仅 http / https。
ALLOWED_SCHEMES = frozenset({"http", "https"})
# 重定向上限（规格 §2）。
MAX_REDIRECTS = 3
# 默认端口（未显式给出时按协议补全）。
DEFAULT_PORTS = {"http": 80, "https": 443}

# 云元数据服务地址：单独命名，使拒绝原因可精确到「元数据」而非泛化的链路本地。
METADATA_ADDRESSES = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP IPv4 IMDS
        "fd00:ec2::254",  # AWS IPv6 IMDS
    }
)

# 禁止网段 → 拒绝原因。顺序即优先级（元数据在地址分类处先行判定）。
_FORBIDDEN_NETWORKS: tuple[tuple[str, str], ...] = (
    ("0.0.0.0/8", "unspecified"),
    ("10.0.0.0/8", "private"),
    ("100.64.0.0/10", "private"),  # RFC 6598 运营商级 NAT 共享地址
    ("127.0.0.0/8", "loopback"),
    ("169.254.0.0/16", "link_local"),
    ("172.16.0.0/12", "private"),
    ("192.0.0.0/24", "reserved"),
    ("192.0.2.0/24", "reserved"),
    ("192.88.99.0/24", "reserved"),
    ("192.168.0.0/16", "private"),
    ("198.18.0.0/15", "reserved"),
    ("198.51.100.0/24", "reserved"),
    ("203.0.113.0/24", "reserved"),
    ("224.0.0.0/4", "multicast"),
    ("240.0.0.0/4", "reserved"),
    ("::/128", "unspecified"),
    ("::1/128", "loopback"),
    ("64:ff9b::/96", "reserved"),  # IPv4/IPv6 转换前缀
    ("100::/64", "reserved"),
    ("2001:db8::/32", "reserved"),
    ("fc00::/7", "private"),  # 唯一本地地址（含 fd00:ec2::254）
    ("fe80::/10", "link_local"),
    ("ff00::/8", "multicast"),
)

# 拒绝原因 → 可读中文（前端直接展示，不暴露实现细节）。
REASON_TEXT = {
    "scheme_not_allowed": "只接受 http / https 链接",
    "credentials_not_allowed": "链接不得内嵌用户名或密码",
    "invalid_url": "链接格式无法解析",
    "empty_host": "链接缺少主机名",
    "dns_failure": "主机名无法解析",
    "loopback": "拒绝访问本机环回地址",
    "private": "拒绝访问内网地址",
    "link_local": "拒绝访问链路本地地址",
    "metadata": "拒绝访问云元数据地址",
    "unspecified": "拒绝访问未指定地址",
    "multicast": "拒绝访问组播地址",
    "reserved": "拒绝访问保留地址",
}


class UrlSecurityError(ValueError):
    """URL 未通过安全校验（可读原因 + 机器可读 `reason`）。"""

    def __init__(self, message: str, *, reason: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedUrl:
    """通过校验的 URL：规范化后的原地址 + 实际解析到的地址（可观测）。"""

    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...] = field(default_factory=tuple)


# 解析器签名：主机名 + 端口 → 地址列表（测试注入假解析器，绝不真发 DNS）。
AddressResolver = Callable[[str, int], list[str]]


def _reason(reason: str) -> str:
    """原因码 → 可读文案（缺项时回退原因码本身，绝不返回空串）。"""
    return REASON_TEXT.get(reason, reason)


def _deny(detail: str, *, reason: str, status_code: int = 400) -> UrlSecurityError:
    """构造带可读前缀的安全拒绝异常。"""
    return UrlSecurityError(
        f"{_reason(reason)}：{detail}" if detail else _reason(reason),
        reason=reason,
        status_code=status_code,
    )


def classify_address(address: str) -> str | None:
    """判定单个 IP 是否被禁；返回原因码，公网地址返回 None。

    IPv4 映射的 IPv6 地址（`::ffff:127.0.0.1`）按内层 IPv4 判定，
    否则内网地址可以借该形态绕过网段匹配。
    """
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if str(ip) in METADATA_ADDRESSES:
        return "metadata"

    for network, reason in _NETWORKS:
        if ip in network:
            return reason
    return None


_NETWORKS = tuple(
    (ipaddress.ip_network(cidr), reason) for cidr, reason in _FORBIDDEN_NETWORKS
)


def default_resolver(host: str, port: int) -> list[str]:
    """真实 DNS 解析（默认实现）：返回去重后的地址列表。"""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    return addresses


def validate_url(
    url: str, *, resolver: AddressResolver | None = None, resolve: bool = True
) -> ValidatedUrl:
    """校验 URL 可安全抓取；不通过即抛 `UrlSecurityError`（可读原因）。

    校验两步走（防 DNS rebinding）：
    1. **解析前**：协议、凭据、主机名形态；主机名本身是字面量 IP 时当场判定；
    2. **解析后**：域名经 `resolver` 解析，逐个复核结果地址，任一命中禁止段即拒绝。

    `resolve=False` 只做第 1 步（不发起 DNS）：供路由层做「不联网的快速前置拒绝」，
    第 2 步由抓取器在每一跳请求前完成（见 `HttpUrlFetcher`）。
    """
    raw = (url or "").strip()
    parsed = urlsplit(raw)

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise _deny(parsed.scheme or "（缺少协议）", reason="scheme_not_allowed")

    if parsed.username or parsed.password:
        raise _deny(parsed.netloc, reason="credentials_not_allowed")

    host = (parsed.hostname or "").strip()
    if not host:
        raise _deny(raw, reason="empty_host")

    try:
        port = parsed.port or DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise _deny(raw, reason="invalid_url") from exc

    literal = _as_ip(host)
    if literal is not None:
        reason = classify_address(str(literal))
        if reason is not None:
            raise _deny(f"{raw}（{literal}）", reason=reason)
        return ValidatedUrl(raw, scheme, host, port, (str(literal),))

    if not resolve:
        # 前置拒绝模式：不解析 DNS（路由层不联网），地址复核交给抓取器逐跳完成。
        return ValidatedUrl(raw, scheme, host, port)

    resolve_addresses = resolver or default_resolver
    try:
        addresses = resolve_addresses(host, port)
    except Exception as exc:  # 解析失败一律拒绝，不静默放行（含超时 / 无 DNS）。
        raise _deny(f"{host}（{exc}）", reason="dns_failure") from exc

    if not addresses:
        raise _deny(host, reason="dns_failure")

    for address in addresses:
        try:
            reason = classify_address(address)
        except ValueError as exc:
            raise _deny(f"{host} → {address}", reason="invalid_url") from exc
        if reason is not None:
            raise _deny(f"{host} → {address}", reason=reason)

    return ValidatedUrl(raw, scheme, host, port, tuple(addresses))


def _as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """主机名是字面量 IP 时返回该地址，否则返回 None。

    `urlsplit` 已剥离 IPv6 的方括号；此处再容忍 `%zone` 之类的接口后缀。
    """
    candidate = host.split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None
