"""应用设置的请求 / 响应模型。

当前只有 HTML 演示的全局默认主题（US20）：读回时一并给出可用主题清单，
避免前端为「有哪些合法值」再维护一份事实。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeckThemeSettings(BaseModel):
    """HTML 演示的全局默认主题与可用主题清单。"""

    model_config = ConfigDict(extra="forbid")

    theme: str
    available: list[str] = Field(default_factory=list)


class DeckThemeUpdate(BaseModel):
    """设置全局默认主题；主题必须在可用清单内（路由层校验后返回 400）。"""

    model_config = ConfigDict(extra="forbid")

    theme: str