"""TB-9 URL 来源分析的 HTTP 接缝测试。

唯一接缝 = 进程内 HTTP；URL 抓取走 `FakeUrlFetcher` 替身（fake 注入点 2），
模型走脚本化 fake —— **全程不联网**。覆盖：URL 落来源 / 文档 / 分块并与上传共用同一
总结管线、URL 级 locator 与抓取元数据、安全拒绝（环回 / 私网 / 元数据 / 非法协议 /
内嵌凭据）不落库、抓取失败（需登录 / 超时 / 超限 / 重定向到私网）如实提示不绕过、
无正文 → 未识别。
"""

from __future__ import annotations

import pytest
from fakes import FakeUrlFetcher, ScriptedModelClient
from fastapi.testclient import TestClient

from app.providers.url_fetcher import FetchedPage, UrlFetchError

ARTICLE_URL = "https://example.com/post/1"

ARTICLE_HTML = """<html><head><title>示例文章</title></head><body>
<nav>导航 首页 关于我们</nav>
<article>
  <h1>深度阅读：资料分析管线</h1>
  <p>这是网页正文的第一段，描述资料分析的目标与约束，用于验证正文提取与引用。</p>
  <h2>关键结论</h2>
  <p>这是网页正文的第二段内容，包含关键数据 42，用于验证分块与总结路径。</p>
</article>
<footer>版权所有</footer>
</body></html>
"""

# 只有脚本壳的单页应用：trafilatura 抽不出正文（不得伪造成功）。
SPA_SHELL_HTML = (
    '<html><head><title>单页应用</title></head><body><div id="app"></div>'
    "<script>window.__DATA__ = 1;</script></body></html>"
)


def _page(
    html: str,
    *,
    url: str = ARTICLE_URL,
    final_url: str | None = None,
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
    redirects: int = 0,
) -> FetchedPage:
    """构造一次抓取结果（元数据与正文都可控）。"""
    body = html.encode("utf-8")
    return FetchedPage(
        url=url,
        final_url=final_url or url,
        status=status,
        content_type=content_type,
        body=body,
        fetched_at="2026-10-19T00:00:00+00:00",
        redirects=redirects,
    )


def _submit(client: TestClient, url: str):
    return client.post("/api/analysis/sources/url", json={"url": url})


def test_url_source_creates_source_document_and_chunks_with_metadata(
    url_client: TestClient, url_fetcher: FakeUrlFetcher
) -> None:
    """URL → 来源（kind=url）/ 文档 / 分块落库，抓取元数据如实记录。"""
    url_fetcher.set_page(_page(ARTICLE_HTML))

    response = _submit(url_client, ARTICLE_URL)

    assert response.status_code == 201
    body = response.json()
    assert body["source"]["kind"] == "url"
    assert body["source"]["ref"] == ARTICLE_URL
    meta = body["source"]["meta"]
    assert meta["url"] == ARTICLE_URL
    assert meta["final_url"] == ARTICLE_URL
    assert meta["status"] == 200
    assert meta["content_type"] == "text/html; charset=utf-8"
    assert meta["size"] == len(ARTICLE_HTML.encode("utf-8"))
    assert meta["fetched_at"] == "2026-10-19T00:00:00+00:00"
    assert meta["redirects"] == 0

    assert body["document"]["parse_status"] == "parsed"
    assert body["document"]["chunks"] >= 1
    assert body["unrecognized"] is None

    task = url_client.get(f"/api/tasks/{body['source']['task_id']}").json()
    assert task["kind"] == "analysis"
    # 抓取器只被调用一次，且拿到的是原始地址。
    assert url_fetcher.calls == [ARTICLE_URL]


def test_url_source_uses_same_summary_pipeline_with_url_locator(
    url_client: TestClient,
    url_fetcher: FakeUrlFetcher,
    scripted_model_client: ScriptedModelClient,
) -> None:
    """URL 来源复用既有 analyze / summary 管线：逐块 + 综合，引用定位到 URL。"""
    url_fetcher.set_page(_page(ARTICLE_HTML))
    uploaded = _submit(url_client, ARTICLE_URL).json()
    source_id = uploaded["source"]["id"]
    chunk_count = uploaded["document"]["chunks"]
    scripted_model_client.set_sequence(
        *[f"第 {index} 块要点" for index in range(1, chunk_count + 1)],
        "这是网页资料的总结。",
    )

    result = url_client.post(f"/api/analysis/sources/{source_id}/analyze")

    assert result.status_code == 200
    summary = result.json()["summary"]
    assert summary["chunk_count"] == chunk_count
    assert len(scripted_model_client.calls) == chunk_count + 1
    assert summary["provider_kind"] == "turbo"
    assert [citation["chunk_seq"] for citation in summary["citations"]] == list(
        range(1, chunk_count + 1)
    )
    for citation in summary["citations"]:
        locator = citation["locator"]
        assert locator["format"] == "url"
        assert locator["start"]["url"] == ARTICLE_URL
        assert locator["end"]["url"] == ARTICLE_URL

    saved = url_client.get(f"/api/analysis/sources/{source_id}/summary")
    assert saved.status_code == 200
    assert saved.json()["text"] == summary["text"]


def test_redirected_page_records_final_url_and_locates_chunks_there(
    url_client: TestClient,
    url_fetcher: FakeUrlFetcher,
    scripted_model_client: ScriptedModelClient,
) -> None:
    """发生重定向 → 来源保留原始地址，文档 / 引用位置指向最终地址。"""
    final_url = "https://example.com/moved/article"
    url_fetcher.set_page(_page(ARTICLE_HTML, final_url=final_url, redirects=1))

    body = _submit(url_client, ARTICLE_URL).json()

    assert body["source"]["ref"] == ARTICLE_URL
    assert body["source"]["meta"]["final_url"] == final_url
    assert body["source"]["meta"]["redirects"] == 1
    assert body["document"]["path"] == final_url

    source_id = body["source"]["id"]
    scripted_model_client.set_sequence("块分析", "总结正文。")
    summary = url_client.post(f"/api/analysis/sources/{source_id}/analyze").json()[
        "summary"
    ]
    for citation in summary["citations"]:
        assert citation["locator"]["start"]["url"] == final_url


@pytest.mark.parametrize(
    ("url", "readable"),
    [
        ("http://127.0.0.1/", "环回"),
        ("http://10.0.0.1/admin", "内网"),
        ("http://172.16.0.9/", "内网"),
        ("http://192.168.1.1/", "内网"),
        ("http://169.254.169.254/latest/meta-data/", "元数据"),
        ("http://[fd00:ec2::254]/", "元数据"),
        ("http://[fe80::1]/", "链路本地"),
        ("http://[::1]/", "环回"),
        ("http://0.0.0.0/", "未指定"),
        ("http://224.0.0.1/", "组播"),
        ("http://240.0.0.1/", "保留"),
        ("ftp://example.com/post", "http"),
        ("file:///C:/Windows/win.ini", "http"),
        ("http://user:secret@example.com/post", "用户名"),
    ],
)
def test_url_source_rejects_forbidden_targets_without_storing_anything(
    url_client: TestClient,
    url_fetcher: FakeUrlFetcher,
    url: str,
    readable: str,
) -> None:
    """禁止目标 / 非法协议 / 内嵌凭据 → 400 可读拒绝，且**不落库、不抓取**。"""
    response = _submit(url_client, url)

    assert response.status_code == 400
    assert readable in response.json()["detail"]
    assert url_fetcher.calls == []
    # 没有来源 / 任务被建：拒绝是「整单不受理」，不是「建了再失败」。
    assert url_client.get("/api/analysis/sources/1").status_code == 404


@pytest.mark.parametrize(
    ("error", "readable"),
    [
        (UrlFetchError("需登录", reason="login_required"), "需登录"),
        (UrlFetchError("抓取超时", reason="timeout"), "超时"),
        (UrlFetchError("超过上限", reason="body_too_large"), "上限"),
        (UrlFetchError("拒绝访问内网地址", reason="blocked_address"), "内网"),
        (UrlFetchError("重定向次数超过上限", reason="redirect_limit"), "重定向"),
    ],
)
def test_fetch_failure_is_recorded_truthfully_and_blocks_analysis(
    url_client: TestClient,
    url_fetcher: FakeUrlFetcher,
    scripted_model_client: ScriptedModelClient,
    error: UrlFetchError,
    readable: str,
) -> None:
    """抓取失败 / 需登录 / 超时 / 超限 → 如实落库并提示；分析被 409 挡住，不调用模型。"""
    url_fetcher.set_error(error)

    response = _submit(url_client, ARTICLE_URL)

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["parse_status"] == "failed"
    assert readable in body["message"]
    assert readable in body["document"]["parse_message"]
    assert body["source"]["kind"] == "url"

    source_id = body["source"]["id"]
    blocked = url_client.post(f"/api/analysis/sources/{source_id}/analyze")
    assert blocked.status_code == 409
    assert "解析失败" in blocked.json()["detail"]
    assert scripted_model_client.calls == []
    assert (
        url_client.get(f"/api/analysis/sources/{source_id}/summary").status_code == 404
    )


def test_page_without_main_text_is_unrecognized_and_short_circuits(
    url_client: TestClient,
    url_fetcher: FakeUrlFetcher,
    scripted_model_client: ScriptedModelClient,
) -> None:
    """读不出正文（脚本壳页面）→ 明示未识别，不伪造成功、不调用模型。"""
    url_fetcher.set_page(_page(SPA_SHELL_HTML))

    response = _submit(url_client, ARTICLE_URL)

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["parse_status"] == "unrecognized"
    assert body["document"]["chunks"] == 0
    assert body["unrecognized"]["unrecognized"] is True
    assert body["unrecognized"]["reason"] == "no_main_text"
    assert body["unrecognized"]["locator"]["url"] == ARTICLE_URL
    assert body["message"]

    result = url_client.post(f"/api/analysis/sources/{body['source']['id']}/analyze")
    assert result.status_code == 200
    assert result.json()["summary"] is None
    assert result.json()["unrecognized"]["reason"] == "no_main_text"
    assert scripted_model_client.calls == []


def test_empty_page_is_unrecognized_with_empty_page_reason(
    url_client: TestClient, url_fetcher: FakeUrlFetcher
) -> None:
    """空响应体 → 原因 `empty_page`（与「有页面无正文」区分）。"""
    url_fetcher.set_page(_page(""))

    body = _submit(url_client, ARTICLE_URL).json()

    assert body["document"]["parse_status"] == "unrecognized"
    assert body["unrecognized"]["reason"] == "empty_page"


def test_url_source_can_be_sent_to_creation_after_analysis(
    url_client: TestClient,
    url_fetcher: FakeUrlFetcher,
    scripted_model_client: ScriptedModelClient,
) -> None:
    """URL 来源的总结同样可一键送入主题创作（既有端点直接复用）。"""
    url_fetcher.set_page(_page(ARTICLE_HTML))
    uploaded = _submit(url_client, ARTICLE_URL).json()
    source_id = uploaded["source"]["id"]
    scripted_model_client.set_sequence("块分析", "网页资料总结正文。")
    url_client.post(f"/api/analysis/sources/{source_id}/analyze")

    sent = url_client.post(f"/api/analysis/sources/{source_id}/send-to-creation")

    assert sent.status_code == 201
    assert "网页资料总结正文。" in sent.json()["known_input"]


def test_blank_url_is_rejected(url_client: TestClient) -> None:
    """空 URL → 422（请求体校验），不进入抓取。"""
    response = url_client.post("/api/analysis/sources/url", json={"url": "   "})

    assert response.status_code == 422
