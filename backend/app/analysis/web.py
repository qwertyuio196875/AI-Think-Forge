"""网页正文提取（trafilatura）：过滤导航 / 广告 / 侧栏，只留主正文。

抓取层只负责「拿到字节与元数据」（`app.providers.url_fetcher`），本模块负责把 HTML
变成可分析的正文块：

- `decode_html`：按 `content-type` 的 charset 解码，缺省回退 UTF-8 且坏字节替换
  （编码问题不应让整页资料消失）；
- `parse_web_document`：`favor_precision=True` 让 trafilatura 走精确抽取路径，
  导航 / 广告 / 页脚不进正文；输出 Markdown 以复用既有的 token 流建块逻辑
  （标题可识别），每个块的 locator 带**最终 URL**，引用可回溯；
- 无正文时**绝不伪造成功**：由调用方按 `unrecognized_reason` 落 `unrecognized`
  （`empty_page` = 页面为空；`no_main_text` = 有页面但抽不出正文，如脚本壳页面）。

本模块不发起网络请求，输入是纯字符串，可独立测试（全程离线）。
"""

from __future__ import annotations

import trafilatura

from app.analysis.parsing import ParsedDocument, parse_markdown_blocks

# 「有页面但抽不出正文」与「页面本身为空」两种原因，前端提示口径不同。
NO_MAIN_TEXT_REASON = "no_main_text"
EMPTY_PAGE_REASON = "empty_page"


def decode_html(body: bytes, content_type: str | None = None) -> str:
    """把网页字节解码为文本：优先 content-type 声明的 charset，否则 UTF-8。

    未知 / 非法 charset 一律回退 UTF-8 并替换坏字节：宁可个别字符变问号，
    也不因编码问题丢掉整页资料。
    """
    charset = _charset_from(content_type)
    for encoding in (charset, "utf-8"):
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def parse_web_document(html: str, *, url: str) -> ParsedDocument:
    """HTML → 正文块（含标题），locator 记录来源 URL；抽不出正文时返回空块。"""
    if not (html or "").strip():
        return ParsedDocument(
            format="url", blocks=[], heading_source="none", parser="trafilatura"
        )

    markdown = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_links=False,
        favor_precision=True,
    )
    if not markdown or not markdown.strip():
        return ParsedDocument(
            format="url", blocks=[], heading_source="none", parser="trafilatura"
        )

    blocks, headings = parse_markdown_blocks(
        markdown, format_name="url", locator_extra={"url": url}
    )
    return ParsedDocument(
        format="url",
        blocks=blocks,
        heading_source="style" if headings else "none",
        encoding="utf-8",
        parser="trafilatura",
    )


def unrecognized_reason(html: str) -> str:
    """没有正文块时的原因：页面为空 → `empty_page`，否则 → `no_main_text`。"""
    return EMPTY_PAGE_REASON if not (html or "").strip() else NO_MAIN_TEXT_REASON


def extract_page_title(html: str) -> str | None:
    """页面标题（供来源元数据展示）；读不到返回 None，不编造。"""
    if not (html or "").strip():
        return None
    metadata = trafilatura.extract_metadata(html)
    title = getattr(metadata, "title", None) if metadata else None
    return title.strip() if title and title.strip() else None


def _charset_from(content_type: str | None) -> str | None:
    """从 `text/html; charset=gb18030` 取出 charset（没有则 None）。"""
    if not content_type:
        return None
    for part in content_type.split(";")[1:]:
        key, _, value = part.partition("=")
        if key.strip().lower() == "charset":
            return value.strip().strip('"').strip("'") or None
    return None
