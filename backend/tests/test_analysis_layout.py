"""TB-8 资料分析（版式类文件：PDF / PPTX）的 HTTP 接缝测试。

唯一接缝 = 进程内 HTTP（与 TB-7 同一条）；模型走脚本化 fake（零花费、不联网）。
「正文被解析出来」这一事实从注入点观察：脚本化模型收到的提示词里必须出现样本里
每一个页面 / 幻灯片的文本，否则解析等于没把内容交给管线。

覆盖工单 17 的验收点：

- PDF 文本页解析 + 页码 locator 可回溯（分块边界落在页边界上）；
- PPTX 标题 / 正文 / 表格解析 + 幻灯片 locator 可回溯；
- 扫描件（无文本层）与纯图片 PPTX 走明示未识别路径：短路、零模型调用；
- 有正文但页面含读不到的图片 → `unrecognized_parts` 逐项明示（页级 locator）；
- 损坏 PDF 明确报错且不丢已存数据；上传白名单覆盖 .pdf/.pptx。
"""

from __future__ import annotations

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient
from layout_samples import (
    PDF_MIME,
    PDF_TITLE_PAGE_1,
    PDF_TITLE_PAGE_2,
    PPTX_MIME,
    PPTX_TITLE_SLIDE_1,
    PPTX_TITLE_SLIDE_2,
    body_line,
    corrupt_pdf_bytes,
    picture_only_pptx_bytes,
    scanned_pdf_bytes,
    text_pdf_bytes,
    text_pptx_bytes,
)


def _upload(client: TestClient, name: str, data: bytes, content_type: str):
    return client.post(
        "/api/analysis/sources",
        files={"file": (name, data, content_type)},
    )


def _analyze(client: TestClient, source_id: int):
    return client.post(f"/api/analysis/sources/{source_id}/analyze")


def _prompts(scripted_model_client: ScriptedModelClient) -> str:
    """脚本化模型收到的全部 user 提示词（观察「解析结果真的进了管线」）。"""
    return " ".join(
        call["messages"][1]["content"] for call in scripted_model_client.calls
    )


def test_pdf_text_pages_are_parsed_with_page_locators(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """PDF 正文 + 字号启发式标题被解析；引用 locator 带页码（从 1 开始）可回溯。"""
    uploaded = _upload(analysis_client, "季度报告.pdf", text_pdf_bytes(), PDF_MIME)

    assert uploaded.status_code == 201
    body = uploaded.json()
    document = body["document"]
    assert document["parse_status"] == "parsed"
    assert document["parser"] == "pypdf"
    assert document["heading_source"] == "heuristic"
    assert document["headings"] == 2
    assert document["images"] == 1
    assert document["chunks"] == 2
    assert body["unrecognized"] is None

    # 有正文但有读不到的图片：逐项明示，不伪装成完整分析。
    assert len(body["unrecognized_parts"]) == 1
    part = body["unrecognized_parts"][0]
    assert part["reason"] == "images_not_read"
    assert part["needs_ocr"] is True
    assert part["locator"] == {"format": "pdf", "page": 2, "images": 1}

    scripted_model_client.set_sequence("第 1 块要点", "第 2 块要点", "总结正文。")
    result = _analyze(analysis_client, body["source"]["id"])

    assert result.status_code == 200
    summary = result.json()["summary"]
    assert summary["chunk_count"] == 2
    # 分块边界正好落在页边界上：第 1 块只在第 1 页，第 2 块只在第 2 页。
    assert [
        (citation["locator"]["start"]["page"], citation["locator"]["end"]["page"])
        for citation in summary["citations"]
    ] == [(1, 1), (2, 2)]
    assert all(
        citation["locator"]["format"] == "pdf" for citation in summary["citations"]
    )

    prompts = _prompts(scripted_model_client)
    assert PDF_TITLE_PAGE_1 in prompts and body_line(1) in prompts
    assert PDF_TITLE_PAGE_2 in prompts and "second page" in prompts


def test_pptx_slides_title_body_and_table_are_parsed_with_slide_locators(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """PPTX 每页标题 / 正文 / 表格逐行转文本；引用 locator 带幻灯片序号可回溯。"""
    uploaded = _upload(analysis_client, "方案.pptx", text_pptx_bytes(), PPTX_MIME)

    assert uploaded.status_code == 201
    body = uploaded.json()
    document = body["document"]
    assert document["parse_status"] == "parsed"
    assert document["parser"] == "python-pptx"
    assert document["heading_source"] == "style"
    assert document["headings"] == 2
    assert document["images"] == 1
    assert document["chunks"] == 2
    assert body["unrecognized"] is None

    assert len(body["unrecognized_parts"]) == 1
    part = body["unrecognized_parts"][0]
    assert part["reason"] == "images_not_read"
    assert part["locator"]["format"] == "pptx"
    assert part["locator"]["slide"] == 2

    scripted_model_client.set_sequence("第 1 块要点", "第 2 块要点", "总结正文。")
    result = _analyze(analysis_client, body["source"]["id"])

    assert result.status_code == 200
    summary = result.json()["summary"]
    assert summary["chunk_count"] == 2
    assert [
        (citation["locator"]["start"]["slide"], citation["locator"]["end"]["slide"])
        for citation in summary["citations"]
    ] == [(1, 1), (2, 2)]
    assert all(
        citation["locator"]["format"] == "pptx" for citation in summary["citations"]
    )

    prompts = _prompts(scripted_model_client)
    assert PPTX_TITLE_SLIDE_1 in prompts and body_line(1) in prompts
    assert PPTX_TITLE_SLIDE_2 in prompts
    # 表格逐行转文本（与 DOCX 同一口径）。
    assert "Metric | Value" in prompts
    assert "Adoption | 42 percent" in prompts


def test_scanned_pdf_short_circuits_without_model_calls(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient, data_dir
) -> None:
    """扫描件（无文本层）→ 明示未识别、需要 OCR；不调用模型、不落空总结。"""
    uploaded = _upload(analysis_client, "扫描件.pdf", scanned_pdf_bytes(), PDF_MIME)

    assert uploaded.status_code == 201
    body = uploaded.json()
    document = body["document"]
    assert document["parse_status"] == "unrecognized"
    assert document["parser"] == "pypdf"
    assert document["chunks"] == 0
    assert body["unrecognized"]["unrecognized"] is True
    assert body["unrecognized"]["reason"] == "no_text_layer"
    assert body["unrecognized"]["needs_ocr"] is True
    assert body["unrecognized"]["locator"]["format"] == "pdf"
    assert "OCR" in body["message"]

    source_id = body["source"]["id"]
    scripted_model_client.set_result("不该被调用")
    result = _analyze(analysis_client, source_id)

    assert result.status_code == 200
    result_body = result.json()
    assert result_body["summary"] is None
    assert result_body["unrecognized"]["reason"] == "no_text_layer"
    assert result_body["unrecognized"]["needs_ocr"] is True
    assert scripted_model_client.calls == []

    source = analysis_client.get(f"/api/analysis/sources/{source_id}").json()
    assert source["document"]["parse_status"] == "unrecognized"
    assert source["document"]["parser"] == "pypdf"
    assert source["source"]["meta"]["original_name"] == "扫描件.pdf"
    assert (data_dir / source["source"]["ref"]).is_file()  # 文件仍在，可重试 / 换文件
    assert (
        analysis_client.get(f"/api/analysis/sources/{source_id}/summary").status_code
        == 404
    )


def test_picture_only_pptx_short_circuits_without_model_calls(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """只有图片的 PPTX → 同样走明示未识别路径（不把空内容当成功）。"""
    uploaded = _upload(analysis_client, "图片页.pptx", picture_only_pptx_bytes(), PPTX_MIME)

    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["document"]["parse_status"] == "unrecognized"
    assert body["document"]["parser"] == "python-pptx"
    assert body["document"]["chunks"] == 0
    assert body["unrecognized"]["reason"] == "no_text_layer"
    assert body["unrecognized"]["needs_ocr"] is True
    assert body["unrecognized"]["locator"]["format"] == "pptx"

    scripted_model_client.set_result("不该被调用")
    result = _analyze(analysis_client, body["source"]["id"])

    assert result.status_code == 200
    assert result.json()["summary"] is None
    assert scripted_model_client.calls == []


def test_corrupt_pdf_reports_failure_and_keeps_stored_data(
    analysis_client: TestClient,
) -> None:
    """损坏的 PDF → 明确提示；来源 / 文档 / 文件仍可查，分析被 409 拦下。"""
    response = _upload(analysis_client, "损坏.pdf", corrupt_pdf_bytes(), PDF_MIME)

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["parse_status"] == "failed"
    assert "损坏" in body["message"]

    source = analysis_client.get(
        f"/api/analysis/sources/{body['source']['id']}"
    ).json()
    assert source["document"]["parse_status"] == "failed"
    assert source["source"]["meta"]["original_name"] == "损坏.pdf"

    blocked = _analyze(analysis_client, body["source"]["id"])
    assert blocked.status_code == 409
    assert "解析失败" in blocked.json()["detail"]
