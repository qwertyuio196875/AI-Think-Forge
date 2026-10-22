"""HTML deck 逐页截图渲染器（工单 28 / ADR-0004）。

PPT 是**截图版**：用 Playwright + 内置 Chromium（headless），按 ADR-0004 固定
- CSS 视口 1280×720、`deviceScaleFactor=2`，出 2560×1440 PNG；
- 每页是固定尺寸的 `<section class="slide">`，`element.screenshot()` 截元素边界，
  不依赖滚动位置与吸顶元素；不为每页单独生成 HTML 文件。

**测试绝不启动浏览器**：本模块的渲染器通过依赖注入 / 可替换函数接入调用方
（见 `screenshot_slides` 的 `renderer` 参数）。测试注入一个**预置 PNG 字节**的假渲染器，
只验证编排、路径与产物对账，不在任何测试里打开 Chromium。真实 Playwright 渲染器
`PlaywrightScreenshotRenderer` 只在服务侧按需实例化。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.generation.deck import DeckBuild

# ADR-0004：视口 1280×720、2x 缩放 → 2560×1440 PNG（嵌入 pptx 时 13.333×7.5 英寸满幅）。
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720
DEVICE_SCALE_FACTOR = 2

# 单页截图文件名模板（写入输出目录），页序从 1 起。
SLIDE_PNG_TEMPLATE = "slide-{index:03d}.png"


class SlideRenderer(ABC):
    """把一份 deck 的每页截成 PNG，产出 `(index, png_path)` 的有序序列。

    实现必须**逐页截图**且页数与 `DeckBuild.slide_count` 对得上；产出 PNG 都要落在
    `output_dir` 下。测试注入的假实现不启动浏览器。
    """

    @abstractmethod
    def render(self, build: DeckBuild, output_dir: Path) -> tuple[tuple[int, Path], ...]:
        """把 `build` 的每一页截成 PNG，返回 (页序, PNG 路径)。"""
        raise NotImplementedError


class PlaywrightScreenshotRenderer(SlideRenderer):
    """真实截图：Playwright + 内置 Chromium headless（ADR-0004 唯一真实现）。

    `playwright` 延迟导入：测试注入假渲染器时不需要安装 / 加载 Playwright。
    Chromium 未装 / 启动失败 → 抛明确错误，绝不静默降级成「没有 PPT」（ADR 后果 40 行）。
    """

    def __init__(self, timeout_ms: int = 60_000) -> None:
        self.timeout_ms = timeout_ms

    def render(self, build: DeckBuild, output_dir: Path) -> tuple[tuple[int, Path], ...]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 真实现依赖未装时的明确报错
            raise RuntimeError(
                "截图依赖 Playwright 未安装：请先 `pip install playwright` 并 "
                "`python -m playwright install chromium`（见 pyproject.toml）。"
            ) from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        produced: list[tuple[int, Path]] = []
        html_path = str(Path(build.path).resolve())

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    headless=True, args=["--force-color-profile=srgb"]
                )
            except Exception as exc:  # pragma: no cover - Chromium 缺失/坏安装
                raise RuntimeError(
                    "内置 Chromium 启动失败：请运行 `python -m playwright install chromium` "
                    f"（依赖约 150MB 下载）。原因：{exc}"
                ) from exc
            try:
                page = browser.new_page(
                    viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                    device_scale_factor=DEVICE_SCALE_FACTOR,
                )
                page.goto(
                    # 用 as_uri() 而不是手拼 "file:///..."：Windows 的反斜杠绝对路径
                    # 手拼出来不是合法 URI，as_uri() 会正确地转成 file:///E:/... 形式。
                    Path(html_path).resolve().as_uri(),
                    wait_until="load",
                    timeout=self.timeout_ms,
                )
                page.wait_for_selector("section.slide", timeout=self.timeout_ms)
                slide_count = page.locator("section.slide").count()

                for index in range(slide_count):
                    slide = page.locator(f"section.slide:nth-of-type({index + 1})")
                    # 只激活第 index 页并压平过渡：让截图取到该页确定性的静态版式。
                    page.evaluate(
                        """(i) => {
                          const slides = document.querySelectorAll('section.slide');
                          slides.forEach((s, k) => s.classList.toggle('active', k === i));
                          slides.forEach((s) => s.classList.remove('prev'));
                        }""",
                        index,
                    )
                    slide.wait_for(state="visible", timeout=self.timeout_ms)
                    png_path = output_dir / SLIDE_PNG_TEMPLATE.format(index=index + 1)
                    slide.screenshot(path=str(png_path))
                    produced.append((index + 1, png_path))
            finally:
                browser.close()

        if len(produced) != build.slide_count:
            raise RuntimeError(
                f"截图页数不符：deck 声明 {build.slide_count} 页，实际截出 {len(produced)} 页"
            )
        return tuple(produced)


def screenshot_slides(
    *,
    build: DeckBuild,
    output_dir: str | Path,
    renderer: SlideRenderer,
) -> tuple[tuple[int, Path], ...]:
    """用注入的渲染器把 deck 逐页截图到 `output_dir`，返回 (页序, PNG 路径)。

    `renderer` 是依赖注入点：生产传 `PlaywrightScreenshotRenderer()`，测试传假实现
    （绝不启动浏览器）。调用方据返回的页序与 PNG 路径做后续装配 / 对账。
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    return renderer.render(build, output)