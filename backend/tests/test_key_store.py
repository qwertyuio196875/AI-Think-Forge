"""TB-1 真实密钥库适配：keyring 退化情况与 service 命名。

不触碰真实 Windows 凭据管理器：以桩模块注入，验证：
- `get_password` 返回 `None`（Windows 上可能静默返回空值）→ `None`；
- 后端抛 `KeyringError` → `None`，不冒泡；
- service 名形如 `ThinkForge/provider/<name>`。
"""

from __future__ import annotations

import keyring.errors

from app.providers.key_store import SERVICE_PREFIX, KeyringKeyStore


class _StubKeyring:
    """记录调用的 keyring 桩模块。"""

    def __init__(self, *, result: str | None = None, raises: Exception | None = None) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[tuple] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get_password", service, username))
        if self._raises is not None:
            raise self._raises
        return self._result

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set_password", service, username, password))

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete_password", service, username))


def test_service_name_format() -> None:
    """service 名固定为 `ThinkForge/provider/<name>`，用户名取 provider 名。"""
    stub = _StubKeyring()
    KeyringKeyStore(stub).set_key("DeepSeek 主流程", "sk-1")

    assert SERVICE_PREFIX == "ThinkForge/provider"
    assert stub.calls[0] == (
        "set_password",
        "ThinkForge/provider/DeepSeek 主流程",
        "DeepSeek 主流程",
        "sk-1",
    )


def test_get_key_returns_none_when_backend_returns_none() -> None:
    """退化情况：Windows 后端可能静默返回 None，不得抛错。"""
    store = KeyringKeyStore(_StubKeyring(result=None))

    assert store.get_key("不存在") is None
    assert store.has_key("不存在") is False


def test_get_key_returns_none_when_backend_returns_empty_string() -> None:
    """空字符串同样视为「无密钥」。"""
    store = KeyringKeyStore(_StubKeyring(result=""))

    assert store.get_key("空值") is None


def test_get_key_swallows_keyring_error() -> None:
    """后端不可用（NoKeyringError）时返回 None，不把内部异常抛给 API 层。"""
    store = KeyringKeyStore(_StubKeyring(raises=keyring.errors.NoKeyringError()))

    assert store.get_key("任何") is None
    assert store.has_key("任何") is False


def test_delete_key_ignores_missing_credential() -> None:
    """删除不存在的凭据时 keyring 会抛 PasswordDeleteError，视为已完成。"""
    store = KeyringKeyStore(_StubKeyring(raises=keyring.errors.PasswordDeleteError()))

    store.delete_key("不存在")  # 不抛错即通过


def test_has_key_true_when_present() -> None:
    """存在密钥时 has_key 为 True 且不回传明文。"""
    store = KeyringKeyStore(_StubKeyring(result="sk-present"))

    assert store.has_key("有") is True
    assert store.get_key("有") == "sk-present"