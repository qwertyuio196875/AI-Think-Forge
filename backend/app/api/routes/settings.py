"""应用设置路由：HTML 演示的全局默认主题（US20）。

读写的是 `settings` 表的 `deck_theme_default`：
- 未设置时返回内建默认 `slate`；
- 写入前校验主题存在，未知主题 400（不静默退回默认，避免用户以为已保存）；
- 生成 HTML 时未显式给 theme 才读取该默认值，显式 theme 始终优先。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SettingsRepositoryDep
from app.generation.themes import (
    DECK_THEME_SETTING_KEY,
    DECK_THEMES,
    DEFAULT_THEME_ID,
)
from app.models.settings import DeckThemeSettings, DeckThemeUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _current_theme(repository: SettingsRepositoryDep) -> str:
    """读取当前默认主题；未设置或值已失效时回到内建默认。"""
    value = repository.get(DECK_THEME_SETTING_KEY, DEFAULT_THEME_ID)
    return value if value in DECK_THEMES else DEFAULT_THEME_ID


def _response(theme: str) -> DeckThemeSettings:
    """统一响应：当前主题 + 可用主题清单（按内建顺序）。"""
    return DeckThemeSettings(theme=theme, available=list(DECK_THEMES))


@router.get("/deck-theme", response_model=DeckThemeSettings)
def get_deck_theme(repository: SettingsRepositoryDep) -> DeckThemeSettings:
    """读取 HTML 演示的全局默认主题。"""
    return _response(_current_theme(repository))


@router.put("/deck-theme", response_model=DeckThemeSettings)
def set_deck_theme(
    payload: DeckThemeUpdate, repository: SettingsRepositoryDep
) -> DeckThemeSettings:
    """保存全局默认主题；未知主题 400（不写入任何值）。"""
    theme = payload.theme.strip()
    if theme not in DECK_THEMES:
        known = "、".join(DECK_THEMES)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知的演示主题「{payload.theme}」；可用主题：{known}",
        )

    repository.set(DECK_THEME_SETTING_KEY, theme)
    return _response(theme)