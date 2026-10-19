"""TB-7 资料分析（文本类文件）的 HTTP 接缝测试。

唯一接缝 = 进程内 HTTP；模型走脚本化 fake（零花费、不联网）。覆盖工单 16 的
验收点：分块与综合次数、500 汉字上限、未识别短路、失败不丢已存数据、上传校验、
一键送入主题创作、总结走 turbo 档与缺失回退。
"""

from __future__ import annotations

import base64
import io

import pytest
from docx import Document
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.analysis.service import count_hanzi
from app.providers.model_client import ModelCallError
from app.security import uploads as uploads_module

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 1x1 透明 PNG：用来造「只有图片、没有文本层」的 DOCX（未识别路径）。
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _docx_bytes(document: Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _long_docx(paragraphs: int = 120) -> bytes:
    """几百段的长 DOCX：每段约 100 字，足以切出多个分块。"""
    document = Document()
    document.add_heading("长文标题", level=1)
    for index in range(paragraphs):
        if index and index % 20 == 0:
            document.add_heading(f"第 {index // 20 + 1} 节", level=2)
        document.add_paragraph(
            f"第 {index + 1} 段：这是一段用于验证分块与综合的正文内容，"
            "描述产品定位、用户场景与执行约束，确保单次输入长度不会漏掉重要信息。"
        )
    return _docx_bytes(document)


def _short_docx(text: str = "这是一份短资料，用于验证单块分析。") -> bytes:
    document = Document()
    document.add_heading("短资料", level=1)
    document.add_paragraph(text)
    return _docx_bytes(document)


def _image_only_docx() -> bytes:
    document = Document()
    document.add_picture(io.BytesIO(_PNG_1PX))
    return _docx_bytes(document)


def _upload(
    client: TestClient, name: str, data: bytes, content_type: str = DOCX_MIME
):
    return client.post(
        "/api/analysis/sources",
        files={"file": (name, data, content_type)},
    )


def _analyze(client: TestClient, source_id: int):
    return client.post(f"/api/analysis/sources/{source_id}/analyze")


def test_upload_parses_docx_and_reports_structure(analysis_client: TestClient) -> None:
    """上传长 DOCX → 来源 / 文档 / 分块落库，结构信息如实返回。"""
    response = _upload(analysis_client, "长文.docx", _long_docx())

    assert response.status_code == 201
    body = response.json()
    assert body["source"]["kind"] == "file"
    assert body["source"]["meta"]["original_name"] == "长文.docx"
    assert body["document"]["parse_status"] == "parsed"
    assert body["document"]["heading_source"] == "style"
    assert body["document"]["headings"] >= 2
    assert body["document"]["chunks"] >= 2
    assert body["unrecognized"] is None

    task = analysis_client.get(f"/api/tasks/{body['source']['task_id']}").json()
    assert task["kind"] == "analysis"


def test_long_document_calls_model_once_per_chunk_plus_one_reduce(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """N 块 → 恰好 N 次逐块 + 1 次综合；引用覆盖全部分块；总结走 turbo 档。"""
    uploaded = _upload(analysis_client, "长文.docx", _long_docx()).json()
    source_id = uploaded["source"]["id"]
    chunk_count = uploaded["document"]["chunks"]
    assert chunk_count >= 2

    scripted_model_client.set_sequence(
        *[f"第 {index} 块的主题与要点" for index in range(1, chunk_count + 1)],
        "总结。" * 50,
    )

    result = _analyze(analysis_client, source_id)

    assert result.status_code == 200
    body = result.json()
    summary = body["summary"]
    assert summary is not None
    assert summary["chunk_count"] == chunk_count
    assert len(scripted_model_client.calls) == chunk_count + 1
    # 前 N 次是逐块分析（提示词里带块序号），最后一次是综合。
    assert "第 1 / " in scripted_model_client.calls[0]["messages"][1]["content"]
    assert "逐块分析如下" in scripted_model_client.calls[-1]["messages"][1]["content"]
    assert [citation["chunk_seq"] for citation in summary["citations"]] == list(
        range(1, chunk_count + 1)
    )
    assert summary["provider_kind"] == "turbo"
    assert summary["provider_used"] == "DeepSeek 总结"
    assert summary["provider_fallback"] is False
    assert summary["hanzi_count"] <= 500

    # 保存：重新读取同一份总结；任务已完成。
    saved = analysis_client.get(f"/api/analysis/sources/{source_id}/summary")
    assert saved.status_code == 200
    assert saved.json()["text"] == summary["text"]
    task = analysis_client.get(f"/api/tasks/{uploaded['source']['task_id']}").json()
    assert task["status"] == "completed"


def test_summary_is_capped_at_500_hanzi(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """模型给出超长总结 → 收敛到 ≤500 汉字并记 `truncated`。"""
    uploaded = _upload(analysis_client, "短资料.docx", _short_docx()).json()
    scripted_model_client.set_sequence("块分析", "太" * 600)

    summary = _analyze(analysis_client, uploaded["source"]["id"]).json()["summary"]

    assert summary["truncated"] is True
    assert count_hanzi(summary["text"]) <= 500
    assert summary["hanzi_count"] == count_hanzi(summary["text"])


def test_unrecognized_document_short_circuits_without_model_calls(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """只有图片、没有文本层 → 明示未识别，不调用模型，不返回空总结冒充成功。"""
    uploaded = _upload(analysis_client, "扫描件.docx", _image_only_docx())

    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["document"]["parse_status"] == "unrecognized"
    assert body["document"]["chunks"] == 0
    assert body["unrecognized"]["unrecognized"] is True
    assert body["unrecognized"]["reason"] == "no_text_layer"
    assert body["unrecognized"]["needs_ocr"] is True
    assert body["unrecognized"]["locator"]["format"] == "docx"

    scripted_model_client.set_result("不该被调用")
    result = _analyze(analysis_client, body["source"]["id"])

    assert result.status_code == 200
    result_body = result.json()
    assert result_body["summary"] is None
    assert result_body["unrecognized"]["reason"] == "no_text_layer"
    assert scripted_model_client.calls == []
    assert (
        analysis_client.get(
            f"/api/analysis/sources/{body['source']['id']}/summary"
        ).status_code
        == 404
    )


def test_parse_failure_is_explicit_and_keeps_stored_data(
    analysis_client: TestClient,
) -> None:
    """损坏的 .docx → 明确提示；来源 / 文档 / 文件仍在库里，可重试或换文件。"""
    response = _upload(analysis_client, "损坏.docx", b"not a zip package")

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["parse_status"] == "failed"
    assert "损坏" in body["message"]

    source_id = body["source"]["id"]
    source = analysis_client.get(f"/api/analysis/sources/{source_id}").json()
    assert source["document"]["parse_status"] == "failed"
    assert source["source"]["meta"]["original_name"] == "损坏.docx"

    blocked = _analyze(analysis_client, source_id)
    assert blocked.status_code == 409
    assert "解析失败" in blocked.json()["detail"]


def test_model_failure_keeps_uploaded_source_document_and_chunks(
    analysis_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    data_dir,
) -> None:
    """模型失败 → 可读 502；已入库的来源 / 文档 / 分块与上传文件都还在。"""
    uploaded = _upload(analysis_client, "长文.docx", _long_docx()).json()
    source_id = uploaded["source"]["id"]
    chunk_count = uploaded["document"]["chunks"]

    scripted_model_client.set_error(ModelCallError("模拟：网络中断"))

    failed = _analyze(analysis_client, source_id)

    assert failed.status_code == 502
    assert "模型调用失败" in failed.json()["detail"]

    source = analysis_client.get(f"/api/analysis/sources/{source_id}").json()
    assert source["document"]["parse_status"] == "parsed"
    assert source["document"]["chunks"] == chunk_count
    assert (data_dir / source["source"]["ref"]).is_file()
    assert (
        analysis_client.get(f"/api/analysis/sources/{source_id}/summary").status_code
        == 404
    )


def test_upload_rejects_unsupported_extension(analysis_client: TestClient) -> None:
    """非 TXT / MD / DOCX / PDF / PPTX → 明确拒绝（不落库、不静默当作文本）。"""
    response = _upload(
        analysis_client, "表格.xlsx", b"PK\x03\x04fake", "application/vnd.ms-excel"
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "只接受" in detail
    assert "TXT" in detail and "MD" in detail and "DOCX" in detail
    assert "PDF" in detail and "PPTX" in detail


def test_upload_rejects_oversized_file(
    analysis_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超过上传上限 → 413 明确拒绝（上限与资料分析入口共用同一常量）。"""
    monkeypatch.setattr(uploads_module, "MAX_UPLOAD_BYTES", 1024)

    response = _upload(
        analysis_client, "过长.txt", b"a" * 2048, "text/plain"
    )

    assert response.status_code == 413
    assert "上传上限" in response.json()["detail"]


def test_txt_encoding_and_markdown_fence_are_parsed_correctly(
    analysis_client: TestClient,
) -> None:
    """TXT 回传 GB18030；MD 代码围栏里的 `#` 不被当成标题（token 流而非正则）。"""
    text = "第一段内容。\n\n第二段内容。\n"
    txt = _upload(
        analysis_client,
        "gbk.txt",
        text.encode("gb18030"),
        "text/plain",
    ).json()
    assert txt["document"]["parse_status"] == "parsed"
    assert txt["document"]["encoding"] == "gb18030"
    assert txt["document"]["chunks"] >= 1

    markdown = "# 真标题\n\n正文段落。\n\n```python\n# 伪标题\nprint(1)\n```\n"
    md = _upload(
        analysis_client,
        "说明.md",
        markdown.encode("utf-8"),
        "text/markdown",
    ).json()
    assert md["document"]["parse_status"] == "parsed"
    assert md["document"]["headings"] == 1
    assert md["document"]["encoding"] == "utf-8-sig"


def test_send_to_creation_creates_task_with_summary_as_known_input(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """一键送入主题创作：新任务被创建、已知信息含该来源的总结，且不再调用模型。"""
    uploaded = _upload(analysis_client, "短资料.docx", _short_docx()).json()
    source_id = uploaded["source"]["id"]
    scripted_model_client.set_sequence("块分析", "这是关于产品定位的总结。")
    summary = _analyze(analysis_client, source_id).json()["summary"]
    calls_before = len(scripted_model_client.calls)

    sent = analysis_client.post(f"/api/analysis/sources/{source_id}/send-to-creation")

    assert sent.status_code == 201
    body = sent.json()
    assert body["task"]["kind"] == "creation"
    assert body["summary_id"] == summary["id"]
    assert "短资料" in body["known_input"]
    assert summary["text"] in body["known_input"]
    assert len(scripted_model_client.calls) == calls_before  # 预填不调用模型

    dialogue = analysis_client.get(
        f"/api/grilling/tasks/{body['task']['id']}/dialogue"
    ).json()
    assert dialogue["seed_input"] == body["known_input"]
    assert dialogue["rounds"] == []


def test_summary_falls_back_to_default_provider_and_records_it(
    analysis_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """turbo 档不存在 → 回退默认 provider，并在结果里如实记录用了哪一个。"""
    providers = analysis_client.get("/api/providers").json()["items"]
    turbo = next(item for item in providers if item["kind"] == "turbo")
    moved = analysis_client.put(f"/api/providers/{turbo['id']}", json={"kind": "max"})
    assert moved.status_code == 200

    uploaded = _upload(analysis_client, "短资料.docx", _short_docx()).json()
    scripted_model_client.set_sequence("块分析", "总结正文。")
    summary = _analyze(analysis_client, uploaded["source"]["id"]).json()["summary"]

    assert summary["provider_fallback"] is True
    assert summary["provider_kind"] == "plus"
    assert summary["provider_used"] == "DeepSeek 主流程"
    assert "turbo" in (summary["provider_note"] or "")
