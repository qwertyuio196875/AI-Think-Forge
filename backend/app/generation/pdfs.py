"""把 HTML deck 打印成 PDF 成品（工单 31 / ADR-0004：PDF 由 deck 打印导出，可选）。

PDF 与 pptx **同源同版式**：都吃同一份「页面规划 → HTML deck」，只是导出方式不同——
pptx 逐页截图后装配成图片页，PDF 直接由浏览器把同一份 deck 打印成矢量/文本页。
因此本模块只认 `DeckBuild`，不自己再造版式。

三条硬纪律（与 #28 截图、#29 pptx 装配同一条纪律）：
1. **渲染器可替换**：真实实现是 Playwright 的 `page.pdf()`，测试注入假实现，
   **任何用例都不启动浏览器**；
2. **失败不落半成品**：先写 `.part` 临时文件，校验通过才原子改名；打印失败 /
   页数不符一律抛明确异常，磁盘上不留 `.pdf`；
3. **回读校验**：用 pypdf 重新打开产物，页数必须等于 deck 的幻灯片数
   （每页幻灯片 = PDF 一页）。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.generation.deck import DeckBuild
from app.generation.screenshots import VIEWPORT_HEIGHT, VIEWPORT_WIDTH


class PdfDefinitionError(Exception):
    """PDF 成品打印/校验失败：不交付半成品。"""


class PdfRenderer(ABC):
    """把一份 deck 打印成 PDF 的接缝（真实实现走 Playwright，测试注入假实现）。"""

    @abstractmethod
    def render(self, build: DeckBuild, output_path: Path) -> Path:
        """把 `build` 指向的 deck 打印成 `output_path` 的 PDF，返回落盘路径。"""


class PlaywrightPdfRenderer(PdfRenderer):
    """真实渲染器：Playwright + 内置 Chromium headless，把 deck 打印成 PDF。

    **延迟导入 playwright**：只在真正调用时才加载浏览器驱动，测试环境下模块导入本身
    不触碰浏览器（与 #28 截图渲染器同一取舍）。

    打印前必须把 deck 从「舞台式演示」改成「顺序流式文档」：deck 里 `.slide` 是
    `position:absolute; inset:0` 的叠放舞台（一次只显示一页，靠 JS 切 `.active`），
    直接打印只会得到当前那一页。这里注入打印专用样式，让所有幻灯片按文档流依次排布、
    每张恰好一页（`break-after:page`），从而与截图的逐页结果一一对应。
    """

    #: 打印时注入的样式：解除绝对定位与叠放，改为每张幻灯片一页。
    #: 覆盖点来自 deck 的实际 CSS：`.deck` 是定位容器、`.slide` 为
    #: `position:absolute; inset:0; opacity:0; pointer-events:none`（靠 JS 切 `.active`）。
    #: 打印必须让**所有**幻灯片同时可见、按文档流依次排布、每张占一页。
    PRINT_CSS = """
    @page { size: 13.333in 7.5in; margin: 0; }
    html, body {
        margin: 0 !important; padding: 0 !important;
        background: #fff !important; overflow: visible !important;
        height: auto !important;
    }
    .deck {
        position: static !important; inset: auto !important;
        width: auto !important; height: auto !important;
        overflow: visible !important; transform: none !important;
        display: block !important;
    }
    .slide-counter, .progress-bar, .nav-controls, .keyboard-hint,
    .speaker-notes, .deck-meta { display: none !important; }
    section.slide {
        position: relative !important; inset: auto !important;
        display: flex !important;
        opacity: 1 !important; visibility: visible !important;
        pointer-events: auto !important;
        transform: none !important;
        width: 13.333in !important; height: 7.5in !important;
        box-sizing: border-box !important;
        overflow: hidden !important;
        break-after: page !important; page-break-after: always !important;
        break-inside: avoid !important; page-break-inside: avoid !important;
    }
    section.slide:last-of-type {
        break-after: auto !important; page-break-after: auto !important;
    }
    """

    def render(self, build: DeckBuild, output_path: Path) -> Path:
        from playwright.sync_api import sync_playwright

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 先打到临时文件再原子改名：打印中途失败不会留下能被当成成品的 .pdf。
        staging = output_path.with_name(output_path.name + ".part")
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(
                        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
                    )
                    page.goto(Path(build.path).resolve().as_uri(), wait_until="load")
                    # 让所有幻灯片同时可见并按页断开（见类文档）。
                    page.add_style_tag(content=self.PRINT_CSS)
                    page.emulate_media(media="print")
                    page.pdf(
                        path=str(staging),
                        width="13.333in",
                        height="7.5in",
                        print_background=True,
                        margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                    )
                finally:
                    browser.close()
            os.replace(staging, output_path)
        except Exception:
            staging.unlink(missing_ok=True)
            raise
        return output_path


@dataclass(frozen=True)
class PdfVerdict:
    """PDF 成品的回读校验结果。"""

    path: Path
    page_count: int
    integrity_ok: bool = True


def render_pdf(*, build: DeckBuild, output_path: Path, renderer: PdfRenderer) -> Path:
    """用注入的渲染器把 deck 打印成 PDF；失败不留半成品。

    渲染器负责写 `output_path`（真实实现内部先写临时文件再原子改名）；这里只兜底：
    渲染器没产出文件、或中途抛错时，把可能残留的产物删掉，不留能被当成成品的 `.pdf`。
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        renderer.render(build, output)
        if not output.exists():
            raise PdfDefinitionError("PDF 渲染器没有产出文件")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def verify_pdf_deliverable(output_path: str | Path, *, expected_pages: int) -> PdfVerdict:
    """**回读产物**做完整性检查：能被 pypdf 打开、页数等于 deck 幻灯片数。

    任一条不通过抛 `PdfDefinitionError`（服务层据此丢弃产物、不落库、不交付）。
    """
    path = Path(output_path)
    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfDefinitionError(f"成品 PDF 无法被 pypdf 打开：{exc}") from exc

    if page_count != expected_pages:
        raise PdfDefinitionError(
            f"成品 PDF 页数不符：期望 {expected_pages}，实际 {page_count}"
        )
    return PdfVerdict(path=path, page_count=page_count)
