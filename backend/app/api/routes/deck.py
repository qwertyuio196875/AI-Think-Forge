"""单文件 HTML 演示的主题族清单（只读）。

前端主题选择器与生成入口读**同一份事实**（`app.generation.themes`），避免把主题
清单复制成两处而漂移。清单里同时给出：调色板（以原型 `DECKT` 为准）、内联的西文字体、
来源署名（哪部分 OpenDesign 派生、哪部分本地原创）与许可、以及**需保留的网络资源**。

术语（GLOSSARY）**模板**：样式文件；HTML 一轨的样式载体是主题，代理由「从不联网搜模板」
的同一纪律保证：主题只来自本包内建主题族，不从网络拉取。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.generation.themes import theme_catalog
from app.models.generation import DeckThemeInfo, DeckThemeListResponse

router = APIRouter(prefix="/deck-themes", tags=["deck-themes"])


@router.get("", response_model=DeckThemeListResponse)
def list_deck_themes() -> DeckThemeListResponse:
    """列出内建的三套演示主题（`slate` / `ember` / `mono`）及其来源署名。"""
    items = [DeckThemeInfo(**item) for item in theme_catalog()]
    return DeckThemeListResponse(items=items, total=len(items), cjk_fallback=True)