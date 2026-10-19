"""按 provider 配置解析的模型客户端（`app.state.model_client` 的生产默认实现）。

接线缺陷修复：此前 `app.state.model_client` 恒为 `UnconfiguredModelClient`，
拷问／方案／修订主链路从未真正调用模型——即便用户已在设置页配好 Key。

本实现每次 `complete` 时解析**当前默认 provider**，用它的 `base_url` 与
`model_name` 构造配置、用它的 `name` 从 `KeyStore` 取密钥，再经
`ProviderModelClientFactory` 造出真实客户端并委托调用。这样「默认 provider +
凭据管理器 + OpenAI 兼容适配层」三者才真正串起来。

密钥语义：密钥缺失时**照常发请求**（`api_key=None`），由服务端返回 401，交既有
分类逻辑归为 `auth_error`，不提前伪造失败。
"""

from __future__ import annotations

from app.db.provider_repository import ProviderRepository
from app.providers.key_store import KeyStore
from app.providers.model_client import (
    ModelCallError,
    ModelClientConfig,
    ProviderModelClientFactory,
)

# 无默认 provider 时的可读提示（引导用户去设置页配置）。
NO_DEFAULT_PROVIDER_MESSAGE = (
    "尚未配置可用的模型服务商，请先在设置页添加模型配置并设为默认"
)


class ProviderBackedModelClient:
    """按默认 provider 配置解析并委托给真实客户端的 `ModelClient` 实现。

    构造参数为接缝协作者（provider 仓库 / 密钥库 / 客户端工厂），便于测试注入
    内存替身；生产由 `app.main` 以 `app.state` 上的实例装配。
    """

    def __init__(
        self,
        provider_repository: ProviderRepository,
        key_store: KeyStore,
        factory: ProviderModelClientFactory,
    ) -> None:
        self.provider_repository = provider_repository
        self.key_store = key_store
        self.factory = factory

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        """解析默认 provider 配置与密钥，构造真实客户端并委托调用。

        `model` 显式传入时以调用方为准，否则用 provider 的 `model_name`。
        """
        provider = self.provider_repository.get_default()
        if provider is None:
            raise ModelCallError(NO_DEFAULT_PROVIDER_MESSAGE)

        config = ModelClientConfig(
            base_url=provider["base_url"],
            model_name=model or provider["model_name"],
        )
        client = self.factory.create(config, api_key=self.key_store.get_key(provider["name"]))
        return client.complete(messages, model=model)