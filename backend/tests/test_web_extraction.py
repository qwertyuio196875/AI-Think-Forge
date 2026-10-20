"""TB-9 网页正文提取（trafilatura 层）的纯函数测试。

接缝 = `app.analysis.web`：字节 → 解码 → 正文块（带 URL 级 locator）。全是纯函数，
用固定 HTML 字符串驱动，**不联网**。
"""

from __future__ import annotations

from app.analysis.web import (
    decode_html,
    extract_page_title,
    parse_web_document,
    unrecognized_reason,
)

ARTICLE_URL = "https://example.com/post/1"

ARTICLE_HTML = """<html><head><title>测试页标题</title></head><body>
<nav>导航 首页 关于我们 联系方式</nav>
<aside>广告位：立即购买</aside>
<article>
  <h1>主标题</h1>
  <p>这是网页正文的第一段，用于验证正文提取与引用位置。</p>
  <h2>小节标题</h2>
  <p>这是网页正文的第二段内容，包含关键数据 42。</p>
</article>
<footer>版权所有 广告合作</footer>
</body></html>
"""

SPA_SHELL_HTML = (
    '<html><head><title>单页应用</title></head><body><div id="app"></div>'
    "<script>window.__DATA__ = 1;</script></body></html>"
)


def test_extracts_main_text_and_drops_navigation_and_ads() -> None:
    """正文被提取，导航 / 广告 / 页脚不进正文块。"""
    parsed = parse_web_document(ARTICLE_HTML, url=ARTICLE_URL)

    text = "\n".join(block.text for block in parsed.blocks)
    assert "这是网页正文的第一段" in text
    assert "这是网页正文的第二段" in text
    assert "导航" not in text
    assert "广告位" not in text
    assert "版权所有" not in text
    assert parsed.format == "url"


def test_blocks_carry_url_level_locator_and_headings() -> None:
    """每个块的 locator 指回最终 URL（引用位置可回溯）；标题被识别。"""
    parsed = parse_web_document(ARTICLE_HTML, url=ARTICLE_URL)

    headings = [block for block in parsed.blocks if block.heading_level is not None]
    assert headings, "网页标题应被识别为标题块"
    assert parsed.heading_source == "style"

    for block in parsed.blocks:
        assert block.locator["format"] == "url"
        assert block.locator["url"] == ARTICLE_URL
        assert block.locator.get("line") or block.locator.get("block")


def test_script_only_page_yields_no_blocks() -> None:
    """只有脚本壳的单页应用 → 没有可分析正文（不得伪造成功）。"""
    parsed = parse_web_document(SPA_SHELL_HTML, url=ARTICLE_URL)

    assert parsed.blocks == []
    assert unrecognized_reason(SPA_SHELL_HTML) == "no_main_text"


def test_empty_page_is_distinguished_from_no_main_text() -> None:
    """空页面与「有页面但读不出正文」原因不同（可读提示要能区分）。"""
    assert unrecognized_reason("") == "empty_page"
    assert unrecognized_reason("   \n  ") == "empty_page"
    assert unrecognized_reason(SPA_SHELL_HTML) == "no_main_text"


def test_decode_html_prefers_charset_from_content_type() -> None:
    """按 content-type 的 charset 解码（中文站点常见 GB18030）。"""
    body = "<html><body><p>中文正文</p></body></html>".encode("gb18030")

    assert "中文正文" in decode_html(body, "text/html; charset=gb18030")


def test_decode_html_falls_back_to_utf8_when_charset_absent() -> None:
    """未声明 charset → 按 UTF-8 解码，坏字节替换而不是抛错（不因编码丢掉整页）。"""
    body = "<html><body><p>中文正文</p></body></html>".encode()

    assert "中文正文" in decode_html(body, "text/html")


def test_page_title_is_available_for_source_metadata() -> None:
    """页面标题可读出（供来源元数据展示，抓取失败时回退 None）。"""
    titled = (
        "<html><head><title>只有标题的页面</title></head>"
        "<body><article><p>正文内容一段。</p></article></body></html>"
    )

    assert extract_page_title(titled) == "只有标题的页面"
    assert extract_page_title(ARTICLE_HTML)  # 有 h1 时取正文主标题（非空即可）
    assert extract_page_title("") is None
