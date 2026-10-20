"""TB-1 测试替身：内存密钥库与脚本化模型客户端；TB-9 追加 URL 抓取替身。

这些替身只在测试进程内使用：
- `InMemoryKeyStore` 保证测试永不触碰 Windows 凭据管理器；
- `ScriptedModelClient(Factory)` 让连接测试在不联网、零花费的前提下覆盖
  成功与三类失败路径（网络异常 / 鉴权失败 / 模型名无效）；
- `FakeUrlFetcher`（fake 注入点 2）返回预置网页或预置失败，**绝不发起真实请求**。
"""

from __future__ import annotations

from app.providers.model_client import ModelClientConfig
from app.providers.url_fetcher import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    FetchedPage,
)


class InMemoryKeyStore:
    """内存密钥库替身，遵守 KeyStore 协议。"""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    def set_key(self, provider_name: str, api_key: str) -> None:
        self.keys[provider_name] = api_key

    def get_key(self, provider_name: str) -> str | None:
        return self.keys.get(provider_name)

    def delete_key(self, provider_name: str) -> None:
        self.keys.pop(provider_name, None)

    def has_key(self, provider_name: str) -> bool:
        return bool(self.keys.get(provider_name))


class ScriptedModelClient:
    """按脚本应答或抛错的模型客户端替身。

    支持两种脚本方式（TB-3 多轮推进需要「本轮前沿 / 收敛 / 方案」三次不同应答）：
    - `set_result`：之后每次调用返回同一条应答；
    - `set_sequence`：按调用顺序逐条返回，超出后重复最后一条。
    """

    def __init__(self, *, result: str = "ok", error: BaseException | None = None) -> None:
        self._result = result
        self._error = error
        self._sequence: list[str] = []
        self._sequence_index = 0
        self.calls: list[dict] = []

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )
        if self._error is not None:
            raise self._error
        if self._sequence:
            index = min(self._sequence_index, len(self._sequence) - 1)
            self._sequence_index += 1
            return self._sequence[index]
        return self._result

    def set_result(self, result: str) -> None:
        """替换后续调用返回的脚本化应答（测试中途改脚本）。"""
        self._result = result
        self._sequence = []
        self._sequence_index = 0

    def set_sequence(self, *results: str) -> None:
        """按调用顺序逐条应答；调用次数超出后用最后一条。"""
        self._sequence = list(results)
        self._sequence_index = 0
        self._error = None

    def set_error(self, error: BaseException | None) -> None:
        """让后续调用抛出指定异常（测试模型失败路径）。"""
        self._error = error


class ScriptedModelClientFactory:
    """固定返回同一个替身客户端的工厂，并记录收到的配置与密钥。"""

    def __init__(self, client: ScriptedModelClient) -> None:
        self._client = client
        self.last_config: ModelClientConfig | None = None
        self.last_api_key: str | None = None
        self.configs: list[ModelClientConfig] = []
        self.create_count = 0

    def create(self, config: ModelClientConfig, *, api_key: str | None = None) -> ScriptedModelClient:
        self.last_config = config
        self.last_api_key = api_key
        self.configs.append(config)
        self.create_count += 1
        return self._client


class FakeUrlFetcher:
    """URL 抓取替身（fake 注入点 2）：预置页面或预置失败，记录调用过的地址。

    `fetch` 的签名与 `UrlFetcher` 协议一致（同样的默认边界值），使路由代码在
    真假实现之间无需分支；完全离线，绝不发起真实请求。
    """

    def __init__(
        self, *, page: FetchedPage | None = None, error: BaseException | None = None
    ) -> None:
        self._page = page
        self._error = error
        self.calls: list[str] = []

    def fetch(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> FetchedPage:
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        if self._page is None:
            raise AssertionError("FakeUrlFetcher 未预置抓取结果")
        return self._page

    def set_page(self, page: FetchedPage) -> None:
        """预置成功后返回的页面，并清掉此前预置的失败。"""
        self._page = page
        self._error = None

    def set_error(self, error: BaseException | None) -> None:
        """预置抓取失败（超时 / 需登录 / 超限 / 被安全策略拒绝等）。"""
        self._error = error