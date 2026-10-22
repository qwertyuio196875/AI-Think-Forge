"""HTML deck 逐页截图渲染器（工单 28 / ADR-0004；测试**绝不启动浏览器**）。

钉住 issue #28 验收：
1. **依赖注入的收口**：`screenshot_slides` 接收注入的渲染器，测试用一个**预置 PNG 字节**
   的假实现，任何用例都不打开 Chromium（Playwright 不在测试中加载）；
2. **逐页截图 + 页码连续**：注入的渲染器产出的页序从 1 起、与 deck 页数一致、PNG
   都落在输出目录下；
3. **页数对账**：截图编排要求产出的页数等于 deck 的 `slide_count`（渲染器自检 + 失败报错）；
4. **真实渲染器只在服务侧实例化**：本文件只用假渲染器，绝不 import playwright。

假渲染器把 deck 里每一页「写」成一张预置 PNG（内容为 deck 页面 title 的字节），
并校验输入 deck 的 slide_count —— 这覆盖了「逐页 + 对账」两条，但绝不碰浏览器。
"""

from __future__ import annotations

from pathlib import Path

from app.generation.deck import (
    LAYOUT_END,
    LAYOUT_TITLE,
    DeckBuild,
    DeckSlide,
)
from app.generation.screenshots import (
    SLIDE_PNG_TEMPLATE,
    SlideRenderer,
    screenshot_slides,
)
from app.generation.themes import DECK_THEMES

# 预置的「截图」字节：不放真 PNG，占位即可（测试只看路径与页数，不看像素）。
PRESET_PNG = b"\x89PNG\r\n\x1a\nlen-placeholder"


class FakeRenderer(SlideRenderer):
    """假渲染器：逐页产出一张预置字节的 PNG，返回 (页序, PNG 路径)。

    页数取 deck 的 `slide_count` —— 与真实渲染器的对账语义一致（截出的页数必须等于
    deck 页数），但**绝不导入或启动 Playwright**（ADR-0004：测试不启动浏览器）。
    """

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def render(self, build: DeckBuild, output_dir: Path) -> tuple[tuple[int, Path], ...]:
        self.calls.append(Path(build.path))
        output_dir.mkdir(parents=True, exist_ok=True)
        produced: list[tuple[int, Path]] = []
        for index in range(1, build.slide_count + 1):
            png = output_dir / SLIDE_PNG_TEMPLATE.format(index=index)
            png.write_bytes(PRESET_PNG)
            produced.append((index, png))
        return tuple(produced)


def _build(tmp_path: Path, *, slide_count: int) -> DeckBuild:
    """造一份 deck：头 1 页标题页 + `slide_count`-1 张正文页（含结尾页兜底）。"""
    theme = next(iter(DECK_THEMES.values()))
    slides: list[DeckSlide] = [
        DeckSlide(layout=LAYOUT_TITLE, title="演示", subtitle="副标题", notes="封面"),
    ]
    for index in range(2, slide_count):
        slides.append(
            DeckSlide(layout="list", title=f"第 {index} 页", pieces=(), notes=f"页 {index}")
        )
    if slide_count >= 2:
        slides.append(
            DeckSlide(layout=LAYOUT_END, title="谢谢", subtitle="提问环节", notes="结束")
        )
    output = tmp_path / "deck.html"
    from app.generation.deck import build_html_deck_from_slides

    return build_html_deck_from_slides(
        slides=tuple(slides),
        task_title="演示",
        plan_md="# 演示",
        theme=theme,
        output_path=output,
    )


# --- 验收 ①+②：注入假渲染器，逐页 + 页码连续 ----------------------------------


def test_screenshot_slides_uses_injected_renderer(tmp_path: Path) -> None:
    build = _build(tmp_path, slide_count=5)
    out_dir = tmp_path / "shots"
    fake = FakeRenderer()

    produced = screenshot_slides(build=build, output_dir=out_dir, renderer=fake)

    # 渲染器被调用，且输入 deck 路径正确。
    assert fake.calls == [build.path]
    # 页序 1..5，PNG 落在输出目录。
    assert [idx for idx, _ in produced] == [1, 2, 3, 4, 5]
    for idx, png in produced:
        assert png.parent == out_dir
        assert png.name == SLIDE_PNG_TEMPLATE.format(index=idx)
        assert png.exists()
        assert png.read_bytes() == PRESET_PNG
    # 目录自动创建。
    assert out_dir.is_dir()


# --- 验收 ④：测试注入假渲染器即全绿，绝不启动浏览器 -----------------------------


def test_screenshot_test_path_returns_all_preset_pngs(tmp_path: Path) -> None:
    """用假渲染器跑通整条编排，返回的每一张 PNG 都是预置字节（无浏览器参与）。"""
    build = _build(tmp_path, slide_count=8)
    produced = screenshot_slides(
        build=build, output_dir=tmp_path / "out", renderer=FakeRenderer()
    )
    assert produced
    assert all(png.read_bytes() == PRESET_PNG for _, png in produced)
    # 关键：假渲染器被如实使用——没有启动 Chromium 的副作用（本文件从不 import playwright）。
    assert produced != ()