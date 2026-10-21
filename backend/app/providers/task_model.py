"""按任务解析模型客户端与模型名（拷问与填充共用同一套口径）。

为什么抽到这里：任务级模型覆盖（`tasks.provider_id`）的解析规则只有一条——有覆盖
就按覆盖的 provider 调、没有就按默认 provider 调。写两遍迟早会改漏一处，于是
拷问与填充（两处都要调模型的地方）统一从这里取。

接缝兼容：测试注入的 fake 客户端没有 `for_task` 时原样使用（既有行为不变）。
"""

from __future__ import annotations

from app.db.provider_repository import ProviderRepository
from app.providers.model_client import ModelClient


def model_for_task(
    task: dict, provider_repository: ProviderRepository, model_client: ModelClient
) -> tuple[ModelClient, str | None]:
    """解析任务级模型覆盖，返回（客户端, model_name）。

    - 任务 pin 了 provider：客户端按其配置调用，`model_name` 取该 provider 的；
    - 未 pin：行为与既有实现一致（默认 provider 的 model_name）。
    """
    provider_id = task.get("provider_id")
    client = (
        model_client.for_task(provider_id)
        if hasattr(model_client, "for_task")
        else model_client
    )
    provider = (
        provider_repository.get_by_id(provider_id)
        if provider_id is not None
        else provider_repository.get_default()
    )
    return client, provider["model_name"] if provider is not None else None
