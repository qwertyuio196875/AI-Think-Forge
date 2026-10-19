"""成品投递端点（`GET /api/deliverables/{generation_id}`）接缝测试。

唯一接缝 = 进程内 HTTP；模型走 fake；**不联网**。

浏览器无法经 `http://127.0.0.1:8720` 读取 `file://` 本地文件，所以「打开成品」与
「应用内预览演示」必须由后端投递产物。本端点只按 **generation id** 取记录，
绝不接受客户端传入的路径：

- 正测：Word / HTML 各一 —— 200、Content-Type 正确、**字节与磁盘文件逐字节一致**；
- 文件名：中文文件名经 `filename*=UTF-8''…` 正确编码（另给 ASCII 回退）；
- HTML 一轨：`inline` 且不加 CSP，保证应用内 `iframe` 能渲染自包含单文件；
- 负测：记录存在但文件被删除 / `file_path` 越出 `data/deliverables/`（绝对路径或 `..`）
  / 未知 id —— 一律 404，且**响应体不泄漏该路径**（不得 500 把内部路径抛给客户端）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.generation_repository import GenerationRepository

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 新员工培训\n\n"
    "两周内掌握产品全貌。\n\n"
    "## 产品定位\n从场景切入。\n\n"
    "## 核心场景\n- 早晨开工\n- 日常答疑\n"
)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
HTML_MEDIA_TYPE = "text/html; charset=utf-8"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _confirmed_task(client: TestClient, scripted: ScriptedModelClient) -> int:
    """走完拷问 → 收敛 → 确认方案，返回已确认方案的任务 id。"""
    scripted.set_sequence(
        _frontier_json(("Q", "正文", "推荐")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["答"]}
    )
    client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    return task_id


def _generation_record(
    db_path: Path,
    *,
    file_path: str,
    format: str = "html",
) -> dict:
    """直接登记一条成品记录（负测构造越界 / 删除等状态用；断言仍只走 HTTP）。"""
    return GenerationRepository(db_path).create(
        task_id=1,
        plan_id=1,
        format=format,
        file_path=file_path,
        template_used="deck-theme:slate",
    )


# --- 正测：Word / HTML 投递 ------------------------------------------------------


def test_word_deliverable_is_downloaded_with_matching_bytes(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """Word 成品：200、正确 Content-Type、字节与磁盘文件一致、可读文件名。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    created = grilling_client.post(f"/api/tasks/{task_id}/generations").json()
    artifact = Path(created["file_path"])

    response = grilling_client.get(f"/api/deliverables/{created['id']}")

    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_MEDIA_TYPE
    assert response.content == artifact.read_bytes()
    assert len(response.content) == artifact.stat().st_size

    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f'filename="{artifact.name}"' in disposition
    assert f"filename*=UTF-8''{artifact.name}" in disposition


def test_html_deliverable_is_downloaded_as_renderable_inline_page(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """HTML 成品：`text/html; charset=utf-8`、`inline`、无 CSP（应用内 iframe 可渲染）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    created = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": "slate"}
    ).json()
    artifact = Path(created["file_path"])

    response = grilling_client.get(f"/api/deliverables/{created['id']}")

    assert response.status_code == 200
    assert response.headers["content-type"] == HTML_MEDIA_TYPE
    assert response.content == artifact.read_bytes()
    assert response.content.decode("utf-8").startswith("<!DOCTYPE html>")

    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert f'filename="{artifact.name}"' in disposition
    # 产物是自包含单文件（样式 / 脚本全内联）：不得用 CSP 阻断它自己的内联资源，
    # 否则应用内预览会变成一张白页。
    assert "content-security-policy" not in response.headers


def test_chinese_filename_is_encoded_in_content_disposition(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    db_path: Path,
    data_dir: Path,
) -> None:
    """中文文件名：`filename*=UTF-8''…` 按 RFC 5987 百分号编码，另给 ASCII 回退。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    created = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html"}
    ).json()

    artifact = Path(created["file_path"])
    renamed = artifact.with_name("新员工培训方案.html")
    artifact.rename(renamed)
    record = _generation_record(db_path, file_path=str(renamed))

    response = grilling_client.get(f"/api/deliverables/{record['id']}")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    # 「新员工培训方案.html」的 UTF-8 百分号编码（独立写死的字面量，不复用实现）。
    assert (
        "filename*=UTF-8''%E6%96%B0%E5%91%98%E5%B7%A5%E5%9F%B9%E8%AE%AD%E6%96%B9%E6%A1%88.html"
        in disposition
    )
    assert 'filename="' in disposition  # ASCII 回退仍在，老客户端不至于拿不到名字


# --- 负测：文件缺失 / 越界路径 / 未知 id ------------------------------------------


def test_missing_artifact_file_returns_404(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """记录存在但产物已从磁盘删除：404，不是 500。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    created = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html"}
    ).json()
    Path(created["file_path"]).unlink()

    response = grilling_client.get(f"/api/deliverables/{created['id']}")

    assert response.status_code == 404
    assert "成品" in response.json()["detail"]


def test_absolute_path_outside_deliverables_root_is_refused_without_leaking(
    grilling_client: TestClient, tmp_path: Path, db_path: Path
) -> None:
    """`file_path` 指向 `data/deliverables/` 之外（绝对路径）：404 且不泄漏路径。"""
    secret = tmp_path / "outside-secret.html"
    secret.write_text("<html>不该被投递</html>", encoding="utf-8")
    record = _generation_record(db_path, file_path=str(secret))

    response = grilling_client.get(f"/api/deliverables/{record['id']}")

    assert response.status_code == 404
    body = response.text
    assert str(secret) not in body
    assert secret.name not in body
    assert "不该被投递" not in body


def test_dotdot_traversal_outside_deliverables_root_is_refused(
    grilling_client: TestClient, tmp_path: Path, db_path: Path, data_dir: Path
) -> None:
    """`file_path` 用 `..` 逃出白名单目录：解析后越界 → 404，不泄漏路径。"""
    secret = tmp_path / "escape-target.html"
    secret.write_text("<html>越界文件</html>", encoding="utf-8")
    traversal = str(data_dir / "deliverables" / ".." / ".." / secret.name)
    record = _generation_record(db_path, file_path=traversal)

    response = grilling_client.get(f"/api/deliverables/{record['id']}")

    assert response.status_code == 404
    assert secret.name not in response.text
    assert "越界文件" not in response.text


def test_file_in_data_dir_but_outside_deliverables_subdir_is_refused(
    grilling_client: TestClient, db_path: Path, data_dir: Path
) -> None:
    """`data/` 下但不在 `deliverables/` 子目录：仍拒绝（白名单是子目录，不是整个 data/）。"""
    other = data_dir / "other-artifact.html"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("<html>非成品目录</html>", encoding="utf-8")
    record = _generation_record(db_path, file_path=str(other))

    response = grilling_client.get(f"/api/deliverables/{record['id']}")

    assert response.status_code == 404
    assert other.name not in response.text


def test_unknown_generation_id_returns_404(grilling_client: TestClient) -> None:
    """不存在的 generation id：404（可读中文），不暴露内部细节。"""
    response = grilling_client.get("/api/deliverables/999999")

    assert response.status_code == 404
    assert "999999" in response.json()["detail"]
