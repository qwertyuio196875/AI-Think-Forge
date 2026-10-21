"""填充阶段的引用片段：预览、采纳过滤、参考资料拼装（工单 24 / ADR-0005；接缝 = 进程内 HTTP）。

钉住工单 24 的四条验收：
1. **填充前可见本次引用**：`POST /sections/{seq}/references` 按章标题+要点检索，
   返回默认全选、可逐条取消的引用卡片；
2. **取消的片段不进本次提示词**：单章填充请求体里只带用户保留的卡片，后端只把
   `adopted=True` 的注入正文提示词；
3. **正文写成功才记引用**：`references_json` 只落实际采用的片段，正文失败不落；
4. **成品末尾「参考资料」只列实际用到的来源**：跨章去重、按首次出现排序，与注入
   的 chunk 一一对应。

本单的检索走假向量（`FakeEmbeddingClient`），模型走脚本化替身：离线、零费用。
填充仍走既有「拷问 → 确认 → 开始填充」流程，确保引用是加在完整流程之上而非边角。
"""

from __future__ import annotations

import json

import httpx
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect

IDEA = "帮我准备一份面向新员工的产品培训"

MD_MIME = "text/markdown"

# 一份知识库资料，内容与第一章「产品全景」的主题强重叠（假向量按字符袋算余弦，
# 必须共享足够字符、且让「多来源」能命中，才能稳定断言参考资料的去重与保序）。
KNOWLEDGE_TEXT = (
    "# 产品全景\n\n"
    "要讲清产品，先立三条真实场景做主线：客户旅程、角色分工、价值落地。"
    "产品全景正是从这些真实场景切入，把主线讲清。\n\n"
    "培训效果评估通常采用三个指标：上手时间、独立完成任务比例、三个月留存率。\n"
)

# 同样的主题、不同来源：第二段资料也命中「产品全景 真实场景 主线」，用来验多来源路径。
KNOWLEDGE_SECOND = (
    "# 场景库\n\n"
    "产品全景的一条真实场景，应当从用户主线切入：先走客户旅程，再看角色分工，"
    "产品全景的每条真实场景都要讲清这条主线。\n"
)

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n\n"
    "## 关键约束\n篇幅控制在十页以内。\n"
)

BODY_MD = (
    "## 早上开工的第一件事\n\n"
    "新员工到岗的第一个上午，先走一遍产品主流程，再做一次独立的小任务。\n"
)


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _upload(client: TestClient, name: str, text: str) -> dict:
    """上传一份知识库资料（会自动建立检索索引）。"""
    response = client.post(
        "/api/knowledge/sources",
        files={"file": (name, text.encode("utf-8"), MD_MIME)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _task_with_started_fill(client: TestClient, scripted: ScriptedModelClient) -> int:
    """走完拷问 → 收敛 → 确认方案 → 开始填充，返回任务 id。

    这里**不带**知识库资料：知识库一存在，拷问阶段的出题就会触发事实型检索、打乱
    脚本化应答，所以测试总是在填充登记完成之后，再单独上传资料，让引用预览与填充
    过程去检索它。
    """
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
        BODY_MD,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    advanced = client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert advanced.status_code == 200, advanced.text
    confirmed = client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")
    assert confirmed.status_code == 200, confirmed.text
    started = client.post(f"/api/tasks/{task_id}/fill", json={})
    assert started.status_code == 200, started.text
    return task_id


def _references_json(db_path, task_id: int, seq: int) -> str:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT references_json FROM plan_sections WHERE task_id = ? AND seq = ?",
            (task_id, seq),
        ).fetchone()
    return (dict(row)["references_json"] if row else None) or ""


def _deliverable_text(artifact_path) -> str:
    """回读 .docx 成品全部段落文本（参考资料是否拼进成品）。"""
    from docx import Document

    document = Document(str(artifact_path))
    return "\n".join(p.text for p in document.paragraphs)


# --- 验收 ①：填充前可见本次引用（只读预览）----------------------------------------


def test_references_preview_is_read_only_and_defaults_to_adopted(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
    db_path,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    _upload(grilling_client, "行业标准.md", KNOWLEDGE_TEXT)

    # 写之前先预览：检索命中应带引用卡片，且默认全选。
    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/references")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["seq"] == 1
    assert body["cards"], "按章标题+要点检索应当命中知识库"
    first = body["cards"][0]
    assert first["name"] == "行业标准.md"
    assert first["adopted"] is True
    assert first["collapsible"] is True
    assert 0.0 < first["similarity"] <= 1.0
    assert body["retrieval_status"]["status"] == "ok"
    # 预览是只读的：不触发写正文、不落引用。
    assert _references_json(db_path, task_id, 1) == ""
    # 预览端点本身不改库、不调模型（前面 3 次调用是拷问→收敛→方案，不是预览产生的）。
    calls_before = len(scripted_model_client.calls)
    assert grilling_client.post(f"/api/tasks/{task_id}/sections/1/references").status_code == 200
    assert len(scripted_model_client.calls) == calls_before


def test_references_preview_unknown_section_returns_404(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)

    response = grilling_client.post(f"/api/tasks/{task_id}/sections/9/references")

    assert response.status_code == 404


# --- 验收 ②：取消的片段不进本次提示词 ---------------------------------------------


def test_deslected_citation_is_not_injected_into_the_prompt(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
    db_path,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    _upload(grilling_client, "行业标准.md", KNOWLEDGE_TEXT)
    _upload(grilling_client, "场景库.md", KNOWLEDGE_SECOND)

    cards = grilling_client.post(f"/api/tasks/{task_id}/sections/1/references").json()["cards"]
    assert len(cards) >= 2, cards
    # 取消第一条：请求体只带用户保留的（去掉第一条）。
    kept = cards[1:]
    rejected = cards[0]
    response = grilling_client.post(
        f"/api/tasks/{task_id}/sections/1/fill", json={"reference_cards": kept}
    )
    assert response.status_code == 200

    # 提示词的最后一次调用里：被取消的那段原文不能出现，保持的可以。
    sent = "\n".join(
        message["content"] for message in scripted_model_client.calls[-1]["messages"]
    )
    rejected_text = rejected["text"]
    assert rejected_text not in sent, "取消的片段不能进提示词"
    # 保留的片段会以引用块形式出现（哪怕只残留一句也够证明注入路径生效）。
    kept_texts = [c["text"] for c in kept]
    assert any(text[:20] in sent for text in kept_texts)

    # 正文写成功后，`references_json` 只落**保留**的（被取消的不在里面）。
    saved = json.loads(_references_json(db_path, task_id, 1))
    assert saved
    saved_ids = [c["chunk_id"] for c in saved]
    assert rejected["chunk_id"] not in saved_ids
    assert {c["chunk_id"] for c in kept} == set(saved_ids)


def test_fill_without_reference_cards_records_nothing(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
    db_path,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    _upload(grilling_client, "行业标准.md", KNOWLEDGE_TEXT)

    # 不带引用卡片 = 本章不用知识库：也不该有任何参考资料。
    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill", json={})
    assert response.status_code == 200
    assert _references_json(db_path, task_id, 1) == ""


# --- 验收 ③：正文写成功才记引用 ----------------------------------------------------


def test_failed_write_records_no_references(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
    db_path,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    _upload(grilling_client, "行业标准.md", KNOWLEDGE_TEXT)

    cards = grilling_client.post(f"/api/tasks/{task_id}/sections/1/references").json()["cards"]
    scripted_model_client.set_error(httpx.ConnectError("boom"))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/sections/1/fill", json={"reference_cards": cards}
    )
    assert response.status_code == 502
    # 正文没写成，这个章节就不该有任何参考资料。
    assert _references_json(db_path, task_id, 1) == ""


# --- 验收 ④：成品末尾参考资料只列实际用到的来源 ------------------------------------


def test_deliverable_appends_references_of_adopted_sources(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
    db_path,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    _upload(grilling_client, "行业标准.md", KNOWLEDGE_TEXT)
    _upload(grilling_client, "场景库.md", KNOWLEDGE_SECOND)

    cards = grilling_client.post(f"/api/tasks/{task_id}/sections/1/references").json()["cards"]
    assert len(cards) >= 2, cards
    # 只保留第一条：成品参考资料只列实际用到的来源。
    kept = [cards[0]]
    response = grilling_client.post(
        f"/api/tasks/{task_id}/sections/1/fill", json={"reference_cards": kept}
    )
    assert response.status_code == 200

    full = _deliverable_text(response.json()["deliverable"]["file_path"])
    # 参考资料小节出现在成品末尾，且只列实际采用的那个来源。
    assert "参考资料" in full
    assert kept[0]["name"] in full
    # 取消掉（没采用）的那个片段不出现。
    assert cards[1]["name"] not in full


def test_deliverable_without_references_has_no_reference_section(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    embedding_client,
) -> None:
    embedding_client.set_model("fake-embedding", dimensions=256)
    task_id = _task_with_started_fill(grilling_client, scripted_model_client)
    _upload(grilling_client, "行业标准.md", KNOWLEDGE_TEXT)

    # 不带引用卡片 = 本章不用知识库：成品里也不该有「参考资料」一节。
    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill", json={})
    assert response.status_code == 200

    full = _deliverable_text(response.json()["deliverable"]["file_path"])
    assert "参考资料" not in full