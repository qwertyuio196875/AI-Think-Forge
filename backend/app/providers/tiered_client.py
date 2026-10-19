"""按档位解析模型客户端（分析管线专用；主流程行为不变）。

规格 §Implementation Decisions：档位是**角色标签**（turbo / plus / max），默认
「主流程 plus、总结流程 turbo」。`ProviderBackedModelClient` 只认默认 provider，
若分析管线直接用它，总结就会跑在 plus 档——与规格不符。

本模块只解决「某个档位该用哪个 provider」：

- 优先取该档位的 provider（`ProviderRepository.get_by_kind`）；
- 该档位不存在时**回退当前默认 provider**，并把 `fallback=True`、实际用的
  provider / 档位与可读说明一并返回（**不静默**，写进总结记录与 API 响应）；
- 连默认 provider 都没有时才显式失败。

解析结果由调用方复用（一次分析只解析一次），避免逐块调用时反复查库。
主流程（拷问 / 方案 / 修订）仍走 `ProviderBackedModelClient`，本模块不介入。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.provider_repository import ProviderRepository
from app.providers.key_store import KeyStore
from app.providers.model_client import (
    ModelCallError,
    ModelClient,
    ModelClientConfig,
    ProviderModelClientFactory,
)

# 总结流程的档位（规格：主流程 plus、总结流程 turbo）。
SUMMARY_PROVIDER_KIND = "turbo"

NO_DEFAULT_PROVIDER_MESSAGE = (
    "尚未配置可用的模型服务商，请先在设置页添加模型配置并设为默认"
)


@dataclass(frozen=True)
class ResolvedModelClient:
    """一次档位解析的结果：实际客户端 + 实际所用 provider / 模型 / 是否回退。"""

    client: ModelClient
    requested_kind: str
    provider_name: str
    provider_kind: str | None
    model_name: str
    fallback: bool
    note: str | None = None


class TieredModelClient:
    """按档位解析 provider 并构造真实客户端的接缝（fake 可注入工厂）。"""

    def __init__(
        self,
        provider_repository: ProviderRepository,
        key_store: KeyStore,
        factory: ProviderModelClientFactory,
    ) -> None:
        self.provider_repository = provider_repository
        self.key_store = key_store
        self.factory = factory

    def resolve(self, kind: str) -> ResolvedModelClient:
        """解析档位对应 provider；该档位缺失时回退默认并留下说明。"""
        provider = self.provider_repository.get_by_kind(kind)
        fallback = False
        note: str | None = None

        if provider is None:
            provider = self.provider_repository.get_default()
            fallback = True
            if provider is None:
                raise ModelCallError(NO_DEFAULT_PROVIDER_MESSAGE)
            note = (
                f"未配置 {kind} 档模型配置，已回退默认模型配置「{provider['name']}」"
                f"（档位 {provider['kind'] or '未标注'}）"
            )

        config = ModelClientConfig(
            base_url=provider["base_url"], model_name=provider["model_name"]
        )
        client = self.factory.create(
            config, api_key=self.key_store.get_key(provider["name"])
        )
        return ResolvedModelClient(
            client=client,
            requested_kind=kind,
            provider_name=provider["name"],
            provider_kind=provider["kind"],
            model_name=provider["model_name"],
            fallback=fallback,
            note=note,
        )
