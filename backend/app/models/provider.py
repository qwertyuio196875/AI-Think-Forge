"""模型配置（provider）与连接测试的请求 / 响应模型。

响应体刻意不含密钥：只给 `has_key: bool`。档位 `kind` 是角色标签（可空）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.providers.errors import ConnectionCategory


class ProviderKind(str, Enum):
    """档位 = 角色标签（规格 §4）；`model_name` 另行可编辑。"""

    turbo = "turbo"
    plus = "plus"
    max = "max"


class ProviderCreate(BaseModel):
    """新建模型配置请求体。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    kind: ProviderKind | None = None
    api_key: str | None = None


class ProviderUpdate(BaseModel):
    """编辑模型配置请求体；未传的字段保持原值，api_key 传了才更新凭据。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    base_url: str | None = Field(default=None, min_length=1)
    model_name: str | None = Field(default=None, min_length=1)
    kind: ProviderKind | None = None
    api_key: str | None = None


class Provider(BaseModel):
    """模型配置响应体（不含密钥）。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    base_url: str
    model_name: str
    is_default: bool
    kind: ProviderKind | None
    has_key: bool


class ProviderListResponse(BaseModel):
    """模型配置列表响应：条目 + 总数。"""

    items: list[Provider]
    total: int


class ConnectionTestResult(BaseModel):
    """连接测试结果：成功与否 + 分类 + 可读消息。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    category: ConnectionCategory
    message: str