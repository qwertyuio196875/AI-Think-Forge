"""内联字体资产：只打包**实际用到的西文 latin 子集** woff2。

调研结论（`02-parsing-and-opendesign.md` B2，本单最硬的约束）：

- 西文（Inter 400 latin 子集）单字重约 23 KB，base64 后约 31 KB，可直接内联；
- 中文（Noto Sans SC 单字重全部 101 个子集）约 2.3 MB，base64 后约 3.1 MB，是西文的
  10~30 倍；且 Google Fonts 的 CJK 按 `unicode-range` 切 101 片**按需加载**，全量内联
  反而丧失该优化；
- 故：**西文内联 base64 woff2，中文回退系统字体栈**（产物元数据记 `cjk_fallback: true`）。

字体全部为 SIL OFL-1.1（Inter / JetBrains Mono / Source Serif 4），许可全文与版权行见
同目录 `assets/licenses/` 与 `assets/THIRD-PARTY-LICENSES.md`。字体文件随本包分发，
生成产物时读入并 base64 内联，**运行时不需要网络**。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ASSETS_DIR = Path(__file__).with_name("assets")
FONT_DIR = ASSETS_DIR / "fonts"
LICENSE_DIR = ASSETS_DIR / "licenses"

# Google Fonts 对 latin 子集声明的 unicode-range（实测取自其 @font-face）。
LATIN_UNICODE_RANGE = (
    "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, "
    "U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, "
    "U+FEFF, U+FFFD"
)


@dataclass(frozen=True)
class FontAsset:
    """一个内联字体资产：字体文件 + 许可与署名信息。"""

    asset_id: str
    file_name: str
    family: str
    weight: int
    license_id: str
    license_file: str
    copyright_notice: str
    unicode_range: str = LATIN_UNICODE_RANGE
    subset: str = "latin"

    @property
    def path(self) -> Path:
        """字体文件路径（随包分发，非运行时下载）。"""
        return FONT_DIR / self.file_name

    @property
    def display_name(self) -> str:
        """产物元数据里的可读名（含子集，便于排查中文显示异常）。"""
        return f"{self.family} {self.weight} {self.subset}"


FONT_ASSETS: dict[str, FontAsset] = {
    asset.asset_id: asset
    for asset in (
        FontAsset(
            asset_id="inter-400",
            file_name="inter-400-latin.woff2",
            family="Inter",
            weight=400,
            license_id="OFL-1.1",
            license_file="OFL-Inter.txt",
            copyright_notice="Copyright 2020 The Inter Project Authors",
        ),
        FontAsset(
            asset_id="inter-700",
            file_name="inter-700-latin.woff2",
            family="Inter",
            weight=700,
            license_id="OFL-1.1",
            license_file="OFL-Inter.txt",
            copyright_notice="Copyright 2020 The Inter Project Authors",
        ),
        FontAsset(
            asset_id="source-serif-4-600",
            file_name="source-serif-4-600-latin.woff2",
            family="Source Serif 4",
            weight=600,
            license_id="OFL-1.1",
            license_file="OFL-SourceSerif4.txt",
            copyright_notice="Copyright 2014 The Source Serif 4 Project Authors",
        ),
        FontAsset(
            asset_id="jetbrains-mono-400",
            file_name="jetbrains-mono-400-latin.woff2",
            family="JetBrains Mono",
            weight=400,
            license_id="OFL-1.1",
            license_file="OFL-JetBrainsMono.txt",
            copyright_notice="Copyright 2020 The JetBrains Mono Project Authors",
        ),
        FontAsset(
            asset_id="jetbrains-mono-700",
            file_name="jetbrains-mono-700-latin.woff2",
            family="JetBrains Mono",
            weight=700,
            license_id="OFL-1.1",
            license_file="OFL-JetBrainsMono.txt",
            copyright_notice="Copyright 2020 The JetBrains Mono Project Authors",
        ),
    )
}


@cache
def font_data_uri(asset_id: str) -> str:
    """字体文件的 `data:` URI（base64；缓存，避免逐次生成重复读盘）。"""
    asset = FONT_ASSETS[asset_id]
    raw = asset.path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:font/woff2;base64,{encoded}"


def font_face_css(asset_ids: tuple[str, ...]) -> str:
    """把若干字体资产渲染成内联 `@font-face` 规则（无任何外部 URL）。"""
    rules: list[str] = []
    for asset_id in asset_ids:
        asset = FONT_ASSETS[asset_id]
        rules.append(
            "@font-face{"
            f"font-family:'{asset.family}';font-style:normal;font-weight:{asset.weight};"
            "font-display:swap;"
            f"src:url({font_data_uri(asset_id)}) format('woff2');"
            f"unicode-range:{asset.unicode_range};"
            "}"
        )
    return "\n".join(rules)


def inlined_font_names(asset_ids: tuple[str, ...]) -> tuple[str, ...]:
    """产物元数据 `inlined_fonts` 的取值（可读名列表）。"""
    return tuple(FONT_ASSETS[asset_id].display_name for asset_id in asset_ids)


def font_attribution_lines(asset_ids: tuple[str, ...]) -> tuple[str, ...]:
    """产物署名用的「字体名 + 版权行 + 许可」三元组文本。"""
    lines: list[str] = []
    for asset_id in asset_ids:
        asset = FONT_ASSETS[asset_id]
        line = f"{asset.family} ({asset.subset} 子集) — {asset.license_id}, {asset.copyright_notice}"
        if line not in lines:
            lines.append(line)
    return tuple(lines)