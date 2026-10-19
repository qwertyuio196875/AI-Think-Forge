"""HTML 全局默认主题（US20）接缝测试。"""

from __future__ import annotations

import json

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = "# 培训大纲\n\n## 目标\n两周内掌握产品全貌。"


def _frontier_json() -> str:
    return json.dumps(
        {
            "frontier": [
                {"title": "Q", "body": "正文", "recommended_answer": "推荐"}
            ]
        },
        ensure_ascii=False,
    )


def _confirmed_task(client: TestClient, scripted: ScriptedModelClient) -> int:
    scripted.set_sequence(
        _frontier_json(),
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


def test_deck_theme_defaults_to_slate(client: TestClient) -> None:
    """未设置时默认 slate，并给出可用主题清单。"""
    response = client.get("/api/settings/deck-theme")

    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "slate"
    assert body["available"] == ["slate", "ember", "mono"]


def test_deck_theme_can_be_saved_and_rejects_unknown(client: TestClient) -> None:
    """合法主题保存后可读回；未知主题 400。"""
    saved = client.put("/api/settings/deck-theme", json={"theme": "ember"})

    assert saved.status_code == 200
    assert saved.json()["theme"] == "ember"
    assert client.get("/api/settings/deck-theme").json()["theme"] == "ember"

    rejected = client.put("/api/settings/deck-theme", json={"theme": "hyper-neon"})
    assert rejected.status_code == 400
    assert "主题" in rejected.json()["detail"]
    assert client.get("/api/settings/deck-theme").json()["theme"] == "ember"


def test_html_generation_uses_global_default_theme(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """生成未显式给 theme 时读取全局默认主题。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    grilling_client.put("/api/settings/deck-theme", json={"theme": "ember"})

    body = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html"}
    ).json()

    assert body["theme_used"] == "ember"
    assert body["template_used"] == "deck-theme:ember"


def test_explicit_theme_overrides_global_default(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """显式 theme 始终优先于全局默认。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    grilling_client.put("/api/settings/deck-theme", json={"theme": "ember"})

    body = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": "mono"}
    ).json()

    assert body["theme_used"] == "mono"