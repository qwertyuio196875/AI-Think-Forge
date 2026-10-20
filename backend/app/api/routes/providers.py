"""模型配置（provider）路由：增删改、设默认、连接测试。

路由只负责校验与响应组织；非敏感字段走 `ProviderRepository`，密钥走 `KeyStore`，
真实调用走 `ProviderModelClientFactory`。响应体一律不含密钥，只给 `has_key`。
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, HTTPException, status

from app.api.deps import KeyStoreDep, ModelClientFactoryDep, ProviderRepositoryDep
from app.models.provider import (
    ConnectionTestResult,
    Provider,
    ProviderCreate,
    ProviderListResponse,
    ProviderUpdate,
)
from app.providers.errors import ConnectionCategory, classify_exception
from app.providers.key_store import KeyStore
from app.providers.model_client import ModelClientConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])

# 连接测试的最小探针消息，输出受客户端 max_tokens 约束，成本可忽略。
CONNECTION_TEST_PROMPT = "ping"


def _to_provider(record: dict, key_store: KeyStore) -> Provider:
    """把数据库行 + 密钥存在性映射为响应模型。"""
    return Provider(
        id=record["id"],
        name=record["name"],
        base_url=record["base_url"],
        model_name=record["model_name"],
        is_default=bool(record["is_default"]),
        kind=record["kind"],
        has_key=key_store.has_key(record["name"]),
    )


def _get_or_404(repository: ProviderRepositoryDep, provider_id: int) -> dict:
    record = repository.get(provider_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"模型配置 {provider_id} 不存在"
        )
    return record


@router.get("", response_model=ProviderListResponse)
def list_providers(
    repository: ProviderRepositoryDep, key_store: KeyStoreDep
) -> ProviderListResponse:
    """列出全部模型配置（不含密钥，含 has_key）。"""
    items = [_to_provider(record, key_store) for record in repository.list()]
    return ProviderListResponse(items=items, total=len(items))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Provider)
def create_provider(
    payload: ProviderCreate,
    repository: ProviderRepositoryDep,
    key_store: KeyStoreDep,
) -> Provider:
    """新建模型配置；密钥写入凭据库，不落 SQLite。"""
    try:
        record = repository.create(
            name=payload.name,
            base_url=payload.base_url,
            model_name=payload.model_name,
            kind=payload.kind.value if payload.kind is not None else None,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"模型配置名已存在：{payload.name}"
        ) from exc

    if payload.api_key:
        key_store.set_key(payload.name, payload.api_key)

    return _to_provider(record, key_store)


@router.put("/{provider_id}", response_model=Provider)
def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    repository: ProviderRepositoryDep,
    key_store: KeyStoreDep,
) -> Provider:
    """编辑非敏感字段；api_key 传了才更新凭据，否则保留原凭据。"""
    existing = _get_or_404(repository, provider_id)
    old_name = existing["name"]
    new_name = payload.name if payload.name is not None else old_name

    # `kind` 可空：用 model_fields_set 区分「未提供」（保持原值）与「显式置空」
    # （`"kind": null` → 写回 NULL）。exclude_none=True 会把显式 null 也剔除，
    # 因此不能只用它。
    fields = payload.model_dump(exclude={"api_key"}, exclude_none=True)
    if "kind" in payload.model_fields_set:
        fields["kind"] = payload.kind.value if payload.kind is not None else None

    try:
        updated = repository.update(provider_id, fields)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"模型配置名已存在：{new_name}"
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"模型配置 {provider_id} 不存在"
        )

    # 凭据以 name 为键：改名时迁移，避免遗留孤儿密钥。
    if payload.api_key:
        key_store.set_key(new_name, payload.api_key)
        if new_name != old_name:
            key_store.delete_key(old_name)
    elif new_name != old_name:
        existing_key = key_store.get_key(old_name)
        if existing_key:
            key_store.set_key(new_name, existing_key)
            key_store.delete_key(old_name)

    return _to_provider(updated, key_store)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider_id: int, repository: ProviderRepositoryDep, key_store: KeyStoreDep
) -> None:
    """删除模型配置，同时清除其凭据。"""
    existing = _get_or_404(repository, provider_id)
    repository.delete(provider_id)
    key_store.delete_key(existing["name"])


@router.post("/{provider_id}/default", response_model=Provider)
def set_default_provider(
    provider_id: int, repository: ProviderRepositoryDep, key_store: KeyStoreDep
) -> Provider:
    """设为唯一默认模型配置。"""
    record = repository.set_default(provider_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"模型配置 {provider_id} 不存在"
        )
    return _to_provider(record, key_store)


@router.post("/{provider_id}/test", response_model=ConnectionTestResult)
def test_provider(
    provider_id: int,
    repository: ProviderRepositoryDep,
    key_store: KeyStoreDep,
    factory: ModelClientFactoryDep,
) -> ConnectionTestResult:
    """连接测试：真实发起一次最小调用，把失败归类为可读结果。

    这里刻意捕获所有异常：分类上报本身就是本接口的职责，`classify_exception`
    再做收敛；未配置密钥时仍探测（交由服务端返回 401 归为 auth_error）。
    """
    record = _get_or_404(repository, provider_id)
    config = ModelClientConfig(base_url=record["base_url"], model_name=record["model_name"])
    client = factory.create(config, api_key=key_store.get_key(record["name"]))

    try:
        client.complete([{"role": "user", "content": CONNECTION_TEST_PROMPT}])
    except Exception as exc:  # noqa: BLE001 — 连接测试需把任意失败转成分类结果
        category, message = classify_exception(exc)
        logger.warning(
            "连接测试失败 provider=%s category=%s", record["name"], category.value
        )
        return ConnectionTestResult(ok=False, category=category, message=message)

    return ConnectionTestResult(
        ok=True, category=ConnectionCategory.ok, message="连接成功"
    )