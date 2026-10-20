"""知识库资料入库与清单（工单 19）接缝测试。

接缝只到进程内 HTTP：上传 / 清单 / 删除三组端点，外加数据库可见状态
（分块确实落在 `document_chunks`、删除确实连带清掉）。不触碰内部函数。
"""

from __future__ import annotations

import io

from docx import Document
from fastapi.testclient import TestClient

from app.db.database import connect

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _count_rows(db_path, table: str) -> int:
    """直接查库确认级联删除真的落到磁盘（清单以外的第二处证据）。"""
    with connect(db_path) as connection:
        return connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def _docx(paragraphs: list[str]) -> bytes:
    """造一份带标题的 DOCX（标题让分块按标题边界切，贴近真实资料）。"""
    document = Document()
    document.add_heading("知识库资料", level=1)
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload(client: TestClient, name: str, payload: bytes) -> dict:
    response = client.post("/api/knowledge/sources", files={"file": (name, payload, DOCX_MIME)})
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_stores_source_with_chunks_and_index_status(
    client: TestClient,
) -> None:
    """上传即入库：返回已解析、分块数大于 0、索引状态为「已入库」。"""
    payload = _upload(
        client,
        "产品说明.docx",
        _docx(["第一段内容，用于验证上传入库链路。", "第二段内容，继续验证分块与状态。"]),
    )

    item = payload["item"]
    assert item["name"] == "产品说明.docx"
    assert item["kind"] == "file"
    assert item["parse_status"] == "parsed"
    assert item["chunk_count"] > 0
    assert item["index_status"] == "stored"
    assert item["index_message"] is None
    assert item["source_id"] > 0
    assert item["document_id"] > 0

    listed = client.get("/api/knowledge/sources").json()
    assert listed["total"] == 1
    assert listed["items"][0]["source_id"] == item["source_id"]
    assert listed["items"][0]["chunk_count"] == item["chunk_count"]


def test_parse_failure_keeps_item_visible_with_failed_status(
    client: TestClient,
) -> None:
    """解析失败不丢资料：仍返回 201、仍在清单里、状态「索引失败」且原因可读。"""
    broken = b"this is not a real docx"
    payload = _upload(client, "坏文件.docx", broken)

    item = payload["item"]
    assert item["index_status"] == "failed"
    assert item["index_status_label"] == "索引失败"
    assert item["index_message"]
    assert item["chunk_count"] == 0
    assert item["name"] == "坏文件.docx"
    assert payload["message"] == item["index_message"]

    listed = client.get("/api/knowledge/sources").json()["items"]
    assert [entry["source_id"] for entry in listed] == [item["source_id"]]
    assert listed[0]["index_status"] == "failed"
    assert listed[0]["index_message"]


def test_delete_removes_source_and_its_chunks(client: TestClient, db_path) -> None:
    """删除后清单与分块一并消失（不留下孤儿分块）。"""
    item = _upload(client, "待删除.docx", _docx(["删除后不应再有任何分块残留。"]))["item"]
    assert item["chunk_count"] > 0

    response = client.delete(f"/api/knowledge/sources/{item['source_id']}")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "source_id": item["source_id"],
        "deleted_chunk_count": item["chunk_count"],
    }

    assert client.get("/api/knowledge/sources").json()["total"] == 0
    assert client.delete(f"/api/knowledge/sources/{item['source_id']}").status_code == 404
    assert _count_rows(db_path, "document_chunks") == 0
    assert _count_rows(db_path, "documents") == 0
    assert _count_rows(db_path, "sources") == 0


def test_chunks_follow_analysis_pipeline_parameters(client: TestClient, db_path) -> None:
    """分块参数复用分析管线同一套（目标 1200 / 上限 1800），不另造分块器。

    证据看库里的分块：每块不超过 1800 字符，长资料确实被切成多块。
    """
    long_paragraph = "这是一段用于验证分块参数的中文内容。" * 40
    item = _upload(client, "长资料.docx", _docx([long_paragraph, long_paragraph]))["item"]
    assert item["chunk_count"] > 1

    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT text FROM document_chunks WHERE document_id = ?",
            (item["document_id"],),
        ).fetchall()
    assert [row["text"] for row in rows]
    assert all(len(row["text"]) <= 1800 for row in rows)


def test_list_is_newest_first_and_paginates(client: TestClient) -> None:
    """清单按最新在前、分页参数如实回显；越界参数由框架拒绝（422）。"""
    first = _upload(client, "第一份.docx", _docx(["第一份资料。"]))["item"]
    second = _upload(client, "第二份.docx", _docx(["第二份资料。"]))["item"]

    newest = client.get("/api/knowledge/sources", params={"limit": 1}).json()
    assert newest["total"] == 2
    assert newest["limit"] == 1
    assert newest["offset"] == 0
    assert [entry["source_id"] for entry in newest["items"]] == [second["source_id"]]

    older = client.get("/api/knowledge/sources", params={"limit": 1, "offset": 1}).json()
    assert [entry["source_id"] for entry in older["items"]] == [first["source_id"]]

    assert client.get("/api/knowledge/sources", params={"limit": 0}).status_code == 422
    assert client.get("/api/knowledge/sources", params={"offset": -1}).status_code == 422


def test_reindex_rebuilds_chunks_and_reports_status(client: TestClient, db_path) -> None:
    """重建索引：重新解析并重切块，逐条回报状态；文件丢失则如实失败。"""
    item = _upload(client, "可重建.docx", _docx(["重建索引前的正文内容。"]))["item"]

    response = client.post("/api/knowledge/reindex", json={"source_id": item["source_id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["source_id"] == item["source_id"]
    assert body["items"][0]["index_status"] == "stored"
    assert body["items"][0]["index_status_label"] == "已入库"

    listed = client.get("/api/knowledge/sources").json()["items"][0]
    assert listed["chunk_count"] == item["chunk_count"]

    assert client.post("/api/knowledge/reindex", json={"source_id": 9999}).status_code == 404


def test_reindex_marks_failure_when_original_file_missing(client: TestClient, data_dir) -> None:
    """原始文件被移走时重建索引失败，但资料仍在清单里、状态明确可见。"""
    item = _upload(client, "文件会消失.docx", _docx(["文件稍后会被移走。"]))["item"]
    for path in (data_dir / "uploads").glob("*"):
        path.unlink()

    body = client.post("/api/knowledge/reindex", json={"source_id": item["source_id"]}).json()
    assert body["items"][0]["index_status"] == "failed"
    assert body["items"][0]["message"]

    listed = client.get("/api/knowledge/sources").json()["items"][0]
    assert listed["index_status"] == "failed"
    assert listed["index_message"]
    assert listed["name"] == "文件会消失.docx"


def test_analysis_sources_are_not_listed_in_knowledge(
    analysis_client: TestClient, client: TestClient
) -> None:
    """资料分析来源不属于知识库：两边清单互不串味，也不可被知识库删除。"""
    analysis_item = analysis_client.post(
        "/api/analysis/sources",
        files={"file": ("分析资料.docx", _docx(["资料分析的正文。"]), DOCX_MIME)},
    )
    assert analysis_item.status_code == 201, analysis_item.text
    analysis_source_id = analysis_item.json()["source"]["id"]

    assert client.get("/api/knowledge/sources").json()["total"] == 0
    assert client.delete(f"/api/knowledge/sources/{analysis_source_id}").status_code == 404
