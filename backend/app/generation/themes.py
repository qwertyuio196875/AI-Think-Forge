"""单文件 HTML 演示的主题族（原型定义的三套本地主题）。

**主题 id 与调色板以 `.scratch/workbench-v1/prototype/index.html` 的 `DECKT` 为准**
（前端按这三个 id 选主题）：`slate`（Slate 极简）/ `ember`（Ember 暖调）/ `mono`（Mono 等宽）。

来源与署名（如实区分「OpenDesign 派生」与「本地原创」，不伪造 OpenDesign 主题）：

- **版式骨架与翻页运行时**改编自 OpenDesign 仓库 `design-templates/html-ppt-zhangzara-<theme>/example.html`
  （MIT，`Copyright (c) 2026 Zara Zhang`）：绝对定位幻灯片 + `.active` / `.prev` 状态、
  页码计数、进度条、键盘翻页监听；原样的 Google Fonts 外链与各主题私有 CSS 一律**弃用**；
- **调色板、字体栈、CSS 与页内演讲者模式为本项目本地原创**（不做像素级复刻）。

字体策略（调研 B2）：西文只内联实际用到的 **latin 子集 base64 woff2**；中文用
**系统字体回退**（产物元数据记 `cjk_fallback: true`、`inlined_fonts`）。

三套主题都**不依赖任何网络资源**；若将来有主题必须保留网络资源，必须在
`network_resources` 里明示，由服务层写进产物与生成记录，不得静默（工单硬要求）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.generation.fonts import font_attribution_lines, font_face_css, inlined_font_names

# 中文回退栈：Windows / macOS 自带中文字体足以渲染，且不引入 MB 级 CJK 字体。
CJK_SANS_FALLBACK = (
    '"Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", '
    "system-ui, sans-serif"
)
CJK_SERIF_FALLBACK = '"Songti SC", "SimSun", "Noto Serif CJK SC", serif'


@dataclass(frozen=True)
class DeckTheme:
    """一套演示主题：调色板 + 字体栈 + 内联字体 + 来源署名。"""

    id: str
    name: str
    bg: str
    fg: str
    accent: str
    line: str
    muted: str
    body_fonts: tuple[str, ...]
    heading_fonts: tuple[str, ...]
    derived_from: str
    license: str = "MIT"
    # 需保留的网络资源（本单三套主题全为空；非空时服务层必须写进产物与记录）
    network_resources: tuple[str, ...] = ()

    @property
    def inlined_fonts(self) -> tuple[str, ...]:
        """本主题内联的西文字体清单（产物元数据 `inlined_fonts`，去重）。"""
        return inlined_font_names(self._unique_fonts())

    @property
    def font_attribution(self) -> tuple[str, ...]:
        """本主题内联字体的署名行（版权行 + 许可）。"""
        return font_attribution_lines(self._unique_fonts())

    def font_face_css(self) -> str:
        """本主题的 `@font-face` 规则（base64 内联，无外部 URL）。"""
        return font_face_css(self._unique_fonts())

    def _unique_fonts(self) -> tuple[str, ...]:
        """去重后的字体资产 id（标题与正文可能共用一种字体）。"""
        seen: list[str] = []
        for asset_id in self.body_fonts + self.heading_fonts:
            if asset_id not in seen:
                seen.append(asset_id)
        return tuple(seen)

    def token_css(self) -> str:
        """主题设计令牌（供前端与产物共用同一份事实）。"""
        return (
            ":root{"
            f"--dkt-bg: {self.bg}; --dkt-fg: {self.fg}; --dkt-acc: {self.accent}; "
            f"--dkt-line: {self.line}; --dkt-muted: {self.muted}; "
            f"--dkt-font: {_font_stack(self.body_fonts, CJK_SANS_FALLBACK)}; "
            f"--dkt-head: {_font_stack(self.heading_fonts, self._heading_fallback())};"
            "}"
        )

    def _heading_fallback(self) -> str:
        """标题的中文回退：等宽 / 衬线主题各自贴合自己的字形气质。"""
        if self.heading_fonts and self.heading_fonts[0].startswith("jetbrains-mono"):
            return _font_stack(("inter-400",), CJK_SANS_FALLBACK)
        if self.heading_fonts and self.heading_fonts[0].startswith("source-serif"):
            return CJK_SERIF_FALLBACK
        return CJK_SANS_FALLBACK


def _font_stack(asset_ids: tuple[str, ...], fallback: str) -> str:
    """把字体资产 id 展开成 CSS `font-family` 值（内联字体在前，系统回退在后）。"""
    from app.generation.fonts import FONT_ASSETS

    families: list[str] = []
    for asset_id in asset_ids:
        family = f'"{FONT_ASSETS[asset_id].family}"'
        if family not in families:
            families.append(family)
    return ", ".join([*families, fallback])


# 三套主题：调色板逐值取自原型 `DECKT`（bg / fg / acc / line 同值；muted 为本地补值）。
DECK_THEMES: dict[str, DeckTheme] = {
    "slate": DeckTheme(
        id="slate",
        name="Slate 极简",
        bg="#f6f7f9",
        fg="#1c2027",
        accent="#2f6bdf",
        line="#dfe4ec",
        muted="#5b6472",
        body_fonts=("inter-400", "inter-700"),
        heading_fonts=("inter-700",),
        derived_from=(
            "OpenDesign `design-templates/html-ppt-zhangzara-blue-professional`"
            "（MIT，Copyright (c) 2026 Zara Zhang）版式骨架与翻页运行时改编，"
            "调色板按本项目原型 DECKT 本地重设为 slate"
        ),
    ),
    "ember": DeckTheme(
        id="ember",
        name="Ember 暖调",
        bg="#fbf6ef",
        fg="#2a2018",
        accent="#c4712a",
        line="#e9dcc8",
        muted="#6d5a45",
        body_fonts=("inter-400",),
        heading_fonts=("source-serif-4-600",),
        derived_from=(
            "OpenDesign `design-templates/html-ppt-zhangzara-coral`"
            "（MIT，Copyright (c) 2026 Zara Zhang）版式骨架与翻页运行时改编，"
            "调色板按本项目原型 DECKT 本地重设为 ember"
        ),
    ),
    "mono": DeckTheme(
        id="mono",
        name="Mono 等宽",
        bg="#101319",
        fg="#e8edf5",
        accent="#3f9d70",
        line="#232b36",
        muted="#8f9aad",
        body_fonts=("jetbrains-mono-400",),
        heading_fonts=("jetbrains-mono-700",),
        derived_from=(
            "OpenDesign `design-templates/html-ppt-zhangzara-studio`"
            "（MIT，Copyright (c) 2026 Zara Zhang）版式骨架与翻页运行时改编，"
            "调色板按本项目原型 DECKT 本地重设为 mono"
        ),
    ),
}

# 未指定主题时的默认值（原型主题选择器的首选项）。
DEFAULT_THEME_ID = "slate"


class DeckThemeError(ValueError):
    """主题不存在：明确报错，绝不静默退回默认主题。"""


def deck_theme(theme_id: str | None) -> DeckTheme:
    """按 id 取主题；未知 id 抛 `DeckThemeError`（不静默降级）。"""
    if theme_id is None:
        return DECK_THEMES[DEFAULT_THEME_ID]
    theme = DECK_THEMES.get(theme_id)
    if theme is None:
        known = "、".join(DECK_THEMES)
        raise DeckThemeError(f"未知的演示主题「{theme_id}」；可用主题：{known}")
    return theme


def theme_catalog() -> list[dict]:
    """主题清单（供前端主题选择器读同一份事实，含来源署名与内联字体）。"""
    return [
        {
            "id": theme.id,
            "name": theme.name,
            "palette": {
                "bg": theme.bg,
                "fg": theme.fg,
                "accent": theme.accent,
                "line": theme.line,
                "muted": theme.muted,
            },
            "fonts": list(theme.inlined_fonts),
            "cjk_fallback": True,
            "derived_from": theme.derived_from,
            "license": theme.license,
            "network_resources": list(theme.network_resources),
        }
        for theme in DECK_THEMES.values()
    ]