"""TB-8 版式类样本的代码构造器（PDF / PPTX）：不提交二进制文件。

- **PDF**：手工拼最小 PDF（PDF-1.4，标准 14 号 Helvetica，不内嵌字体），可按字号
  写行文本、也可只放图片对象，足以构造「有文本层」与「扫描件（无文本层）」两类样本。
  交叉引用表按真实偏移量生成，pypdf 6.x 可正常读回文本与字号。
- **PPTX**：用 python-pptx 现场生成标题 / 正文 / 表格 / 图片页。

样本尺寸刻意做了对齐，让「一页（幻灯片）一分块」成立，页码 / 幻灯片号可清晰回溯：

- PDF 第 1 页块总量落在 (1184, 1200] 字符之间：既不超过分块目标 1200，又使第 2 页的
  第一个块触发 flush（`app.analysis.chunking`），于是分块边界正好落在页边界上；
- PPTX 第 1 张幻灯片同理（标题 21 + 15 段正文 × 78 = 1191）。
"""

from __future__ import annotations

import base64
import io
import zlib

from pptx import Presentation
from pptx.util import Inches

# 1x1 透明 PNG：造图片型样本（与 TB-7 的资料分析测试同源）。
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

PDF_MIME = "application/pdf"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# 正文行宽与条数：18（标题）+ 15 × 78 = 1188，落在 (1184, 1200] 之间。
BODY_LINE_WIDTH = 78
PDF_PAGE_1_BODY_LINES = 15
PPTX_SLIDE_1_BODY_LINES = 15

PDF_TITLE_PAGE_1 = "Quarterly Overview"
PDF_TITLE_PAGE_2 = "Appendix Notes"
PDF_BODY_PREFIX = "Body line"
PDF_PAGE_2_SUFFIX = " appendix note"

PPTX_TITLE_SLIDE_1 = "Roadmap Overview 2026"
PPTX_TITLE_SLIDE_2 = "Metrics Table"
PPTX_TABLE_ROWS = (("Metric", "Value"), ("Adoption", "42 percent"))


def body_line(index: int, *, suffix: str = "") -> str:
    """定宽正文行（按解析侧 strip 后的长度计），便于精确控制分块边界。"""
    prefix = f"{PDF_BODY_PREFIX} {index:02d}: "
    return (prefix + "." * BODY_LINE_WIDTH)[:BODY_LINE_WIDTH] + suffix


def _pdf_text(text: str) -> bytes:
    """PDF 字符串字面量的最小转义（样本只含 ASCII）。"""
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("ascii")


def _content_stream(lines: list[tuple[float, str]], image: bool) -> bytes:
    """内容流：逐行 `Tf` + `Tj`（每行下移 24），可选画一张图片。"""
    parts = [b"BT"]
    y = 720
    for size, text in lines:
        parts.append(b"/F1 " + str(size).encode() + b" Tf 72 " + str(y).encode() + b" Td ("
                     + _pdf_text(text) + b") Tj")
        y -= 24
    parts.append(b"ET")
    if image:
        parts.append(b"q 1 0 0 1 10 100 cm /Im1 Do Q")
    return b"\n".join(parts)


def build_pdf(pages: list[tuple[list[tuple[float, str]], bool]]) -> bytes:
    """按 `[(行列表, 是否放图片)]` 拼一份最小可读 PDF（含正确 xref 偏移）。"""
    objects: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids: list[str] = []

    for lines, has_image in pages:
        xobject = b""
        if has_image:
            raw = zlib.compress(b"\xff\x00\x00")  # 1x1 DeviceRGB
            image_id = len(objects) + 1
            objects.append(
                b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
                + str(len(raw)).encode()
                + b" >>\nstream\n"
                + raw
                + b"\nendstream"
            )
            xobject = b" /XObject << /Im1 " + str(image_id).encode() + b" 0 R >>"
        stream = _content_stream(lines, has_image)
        content_id = len(objects) + 1
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_id = len(objects) + 1
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
            b"<< /Font << /F1 3 0 R >>" + xobject + b" >> /Contents " + str(content_id).encode()
            + b" 0 R >>"
        )
        kids.append(f"{page_id} 0 R")

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids [" + " ".join(kids).encode() + b"] /Count "
        + str(len(pages)).encode() + b" >>"
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_position = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n"
        f"{xref_position}\n%%EOF\n".encode()
    )
    return out.getvalue()


def text_pdf_bytes() -> bytes:
    """两页 PDF：第 1 页标题 + 15 段正文（1188 字符），第 2 页标题 + 一段正文 + 一张图。"""
    page_1 = [(24.0, PDF_TITLE_PAGE_1)] + [
        (10.5, body_line(index)) for index in range(1, PDF_PAGE_1_BODY_LINES + 1)
    ]
    page_2 = [
        (18.0, PDF_TITLE_PAGE_2),
        (10.5, f"{PDF_BODY_PREFIX} appendix: body text on the second page."),
    ]
    return build_pdf([(page_1, False), (page_2, True)])


def scanned_pdf_bytes() -> bytes:
    """两页扫描件样本：只有图片对象，没有任何文本层。"""
    return build_pdf([([], True), ([], True)])


def corrupt_pdf_bytes() -> bytes:
    """损坏的 PDF（有文件头、无有效结构）。"""
    return b"%PDF-1.7 broken payload without structure"


def picture_only_pptx_bytes() -> bytes:
    """只有一张图片的 PPTX：没有任何可分析文本。"""
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_picture(io.BytesIO(PNG_1PX), Inches(1), Inches(1))
    return _pptx_bytes(presentation)


def text_pptx_bytes() -> bytes:
    """两页 PPTX：第 1 页标题 + 15 段正文，第 2 页标题 + 表格 + 一张图。"""
    presentation = Presentation()

    first = presentation.slides.add_slide(presentation.slide_layouts[1])
    first.shapes.title.text = PPTX_TITLE_SLIDE_1
    body = first.placeholders[1].text_frame
    body.paragraphs[0].text = body_line(1)
    for index in range(2, PPTX_SLIDE_1_BODY_LINES + 1):
        body.add_paragraph().text = body_line(index)

    second = presentation.slides.add_slide(presentation.slide_layouts[1])
    second.shapes.title.text = PPTX_TITLE_SLIDE_2
    table = second.shapes.add_table(
        len(PPTX_TABLE_ROWS), 2, Inches(1), Inches(1.5), Inches(6), Inches(1.2)
    ).table
    for row_index, row in enumerate(PPTX_TABLE_ROWS):
        for column_index, cell_text in enumerate(row):
            table.cell(row_index, column_index).text = cell_text
    second.shapes.add_picture(io.BytesIO(PNG_1PX), Inches(1), Inches(4))

    return _pptx_bytes(presentation)


def _pptx_bytes(presentation: Presentation) -> bytes:
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()
