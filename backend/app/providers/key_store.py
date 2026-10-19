"""密钥存储：Windows 凭据管理器（经 `keyring`）。

密钥绝不落 SQLite / 源码 / Git / 前端 / 日志。凭据以 provider 名为键，
service 名形如 `ThinkForge/provider/<name>`。

退化处理（Windows 实测风险）：`keyring.get_password()` 在凭据不存在或后端
不可用时会返回 `None` / 空串，或抛 `KeyringError`；两种情况都归一为「无密钥」，
不把内部异常抛给 API 层。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import keyring
import keyring.errors

logger = logging.getLogger(__name__)

SERVICE_PREFIX = "ThinkForge/provider"


@runtime_checkable
class KeyStore(Protocol):
    """凭据存储抽象（fake 注入点）。"""

    def set_key(self, provider_name: str, api_key: str) -> None:
        """写入或覆盖某 provider 的密钥。"""
        ...

    def get_key(self, provider_name: str) -> str | None:
        """读取密钥；不存在或后端不可用时返回 None。"""
        ...

    def delete_key(self, provider_name: str) -> None:
        """删除密钥；不存在时静默成功。"""
        ...

    def has_key(self, provider_name: str) -> bool:
        """是否已配置密钥（不回传明文）。"""
        ...


class KeyringKeyStore:
    """默认实现：写入系统凭据管理器。

    `keyring_module` 仅用于注入桩模块做单测，生产代码保持默认。
    """

    def __init__(self, keyring_module: object | None = None) -> None:
        self._keyring = keyring_module if keyring_module is not None else keyring

    @staticmethod
    def _service(provider_name: str) -> str:
        return f"{SERVICE_PREFIX}/{provider_name}"

    def set_key(self, provider_name: str, api_key: str) -> None:
        self._keyring.set_password(self._service(provider_name), provider_name, api_key)

    def get_key(self, provider_name: str) -> str | None:
        try:
            value = self._keyring.get_password(self._service(provider_name), provider_name)
        except keyring.errors.KeyringError:
            logger.warning("读取密钥失败，按未配置处理 provider=%s", provider_name)
            return None
        # Windows 后端可能静默返回空值而非抛错，必须显式归类。
        if not value:
            return None
        return value

    def delete_key(self, provider_name: str) -> None:
        try:
            self._keyring.delete_password(self._service(provider_name), provider_name)
        except keyring.errors.KeyringError:
            # 凭据本就不存在（PasswordDeleteError）时视为已删除，不冒泡。
            return

    def has_key(self, provider_name: str) -> bool:
        return bool(self.get_key(provider_name))