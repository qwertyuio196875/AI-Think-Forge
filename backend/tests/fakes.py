"""TB-1 测试替身：内存密钥库与脚本化模型客户端。

这两个替身只在测试进程内使用：
- `InMemoryKeyStore` 保证测试永不触碰 Windows 凭据管理器；
- `ScriptedModelClient(Factory)` 让连接测试在不联网、零花费的前提下覆盖
  成功与三类失败路径（网络异常 / 鉴权失败 / 模型名无效）。
"""

from __future__ import annotations

from app.providers.model_client import ModelClientConfig


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

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        self.calls.append({"messages": messages, "model": model})
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


class ScriptedModelClientFactory:
    """固定返回同一个替身客户端的工厂，并记录收到的配置与密钥。"""

    def __init__(self, client: ScriptedModelClient) -> None:
        self._client = client
        self.last_config: ModelClientConfig | None = None
        self.last_api_key: str | None = None
        self.create_count = 0

    def create(self, config: ModelClientConfig, *, api_key: str | None = None) -> ScriptedModelClient:
        self.last_config = config
        self.last_api_key = api_key
        self.create_count += 1
        return self._client