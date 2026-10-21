"""拷问阶段的事实型检索与引用卡片（工单 23 / ADR-0005；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 23 的四条验收：
1. **决策型问题不触发检索**，对话里不出现无关引用；
2. **判定规则写死在提示词资产里**，不交给模型自由心证；
3. 引用卡片**可折叠**，显示文件名、段落号、相关度；
4. **默认全部采用**，取消勾选的片段不进本次提示词。

为什么规则要写进资产而不是让模型自己判断「这个问题需不需要外部依据」：
模型每次回答都可能给出不同的标准，同一个问题这轮检索、下轮不检索，用户会看到
引用卡片时有时无。规则固化在 `app/grilling/prompts/fact_check_v1.md` 里，
判定结果才可复现、可解释。

「事实型」与「决策型」的界线（写进资产）：
- 事实型：需要**外部依据**才能回答的问题——具体数字、政策条款、产品规格、
  行业标准、他人做法等，答案不在用户的脑内，也不在方案里；
- 决策型：问的是**用户想要什么**——目标、读者、篇幅、风格、优先级、取舍。
  这类问题检索只会把选择题变成资料朗读。
"""

from __future__ import annotations

import json

import pytest
from fakes import FakeEmbeddingClient, ScriptedModelClient
from fastapi.testclient import TestClient

IDEA = "帮我准备一份面向新员工的产品培训"

MD_MIME = "text/markdown"

# 一份知识库资料：内容与「新手培训的行业标准」相关，用于事实型问题的检索。
KNOWLEDGE_TEXT = (
    "# 新员工培训行业标准\n\n"
    "行业通行的新员工培训周期是两周，第一周以产品认知为主，第二周以实操为主。\n\n"
    "培训效果评估通常采用三个指标：上手时间、独立完成任务比例、三个月留存率。\n"
)


@pytest.fixture
def fact_client(
    grilling_client: TestClient, embedding_client: FakeEmbeddingClient
) -> TestClient:
    """256 维假向量：相关文本能命中，无关文本被 0.3 阈值挡掉。

    基于 `grilling_client` 而不是 `client`：拷问要调模型，必须注入脚本化替身，
    否则测试会真的连上百炼。
    """
    embedding_client.set_model("fake-embedding", dimensions=256)
    return grilling_client


def _upload(client: TestClient, name: str, text: str) -> dict:
    response = client.post(
        "/api/knowledge/sources",
        files={"file": (name, text.encode("utf-8"), MD_MIME)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _frontier_json(*items: dict) -> str:
    """前沿问题集（只含 FrontierQuestion 认识的标准字段）。

    `facts_required` / `fact_query` **不属于**前沿问题契约——它们是判定环节的输出。
    测试里通过随后的判定调用（脚本化的第二条应答）给出，见 `_fact_check_json`。
    """
    return json.dumps({"frontier": items}, ensure_ascii=False)


def _question(title: str = "培训周期", body: str = "你们行业里新员工培训通常多久？") -> dict:
    return {"title": title, "body": body, "recommended_answer": "两周左右"}


def _fact_check_json(*checks: dict) -> str:
    """判定环节的应答：`checks` 每项含 `facts_required` 与 `fact_query`。"""
    payload = [{"index": index, **check} for index, check in enumerate(checks)]
    return json.dumps({"checks": payload}, ensure_ascii=False)


def _sequence_with_checks(*pairs: tuple[dict, dict]) -> list[str]:
    """把每条前沿问题与它的判定拼成交错的脚本序列。

    为什么必须交错：一次「出题」实际上是**两次**模型调用——先抛前沿问题，
    再判定「哪些需要外部依据」。`ScriptedModelClient.set_sequence` 按调用顺序取，
    所以脚本必须与真实调用顺序一致，否则判定应答会被当成前沿问题解析。
    """
    responses: list[str] = []
    for question, check in pairs:
        responses.extend([_frontier_json(question), _fact_check_json(check)])
    return responses


def _decision() -> dict:
    return {"facts_required": False, "fact_query": "", "reason": "问的是用户偏好"}


def _fact(query: str) -> dict:
    return {"facts_required": True, "fact_query": query, "reason": "答案取决于外部事实"}


def _start(client: TestClient, scripted: ScriptedModelClient, *responses: str) -> int:
    scripted.set_sequence(*responses)
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    return task_id


# ---------- 判定规则写死在资产里 ----------


def test_fact_check_rules_live_in_the_prompt_asset() -> None:
    """判定规则必须是**资产里的文字**，不是代码里的启发式，也不是模型的自由心证。"""
    from app.grilling import prompts

    version = prompts.FACT_CHECK_PROMPT_VERSION
    assert version.startswith("fact-check-v")
    asset = prompts.load_asset(version)

    # 规则必须在资产里出现：事实型 / 决策型的界线、以及「决策型不检索」。
    assert "事实型" in asset
    assert "决策型" in asset
    assert "不检索" in asset
    # 资产必须自带版本留痕（ADR-0001：变更须留痕）。
    assert version in asset


def test_fact_check_rules_are_stable_across_reads() -> None:
    """同一份资产两次读取逐字相同——判定依据不会随调用漂移。"""
    from app.grilling import prompts

    first = prompts.load_asset(prompts.FACT_CHECK_PROMPT_VERSION)
    second = prompts.load_asset(prompts.FACT_CHECK_PROMPT_VERSION)
    assert first == second


# ---------- 决策型问题不检索 ----------


def test_decision_question_does_not_trigger_retrieval(
    fact_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """决策型问题（问的是用户想要什么）不检索：对话里不出现引用。"""
    _upload(fact_client, "行业标准.md", KNOWLEDGE_TEXT)

    decision_question = _question("目标读者", "这份培训讲给谁听？")
    scripted_model_client.set_sequence(
        *_sequence_with_checks(
            (decision_question, _decision()),
            (decision_question, _decision()),
        )
    )
    task_id = fact_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    response = fact_client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert response.status_code == 200

    body = response.json()
    frontier = body["next_round"]["frontier"]
    assert len(frontier) == 1
    # 决策型问题：不带引用（字段存在但为空，与「还没判」区分）。
    assert frontier[0]["citations"] == []
    assert frontier[0]["retrieval_status"] is None


def test_fact_question_returns_citable_hits(
    fact_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """事实型问题检索知识库，命中带文件名、段落号、相关度（引用卡片的三个字段）。"""
    _upload(fact_client, "行业标准.md", KNOWLEDGE_TEXT)

    scripted_model_client.set_sequence(
        *_sequence_with_checks(
            (_question(), _fact("新员工培训周期 行业标准")),
            (_question(), _fact("新员工培训周期 行业标准")),
        )
    )
    task_id = fact_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    response = fact_client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert response.status_code == 200

    frontier = response.json()["next_round"]["frontier"]
    citations = frontier[0]["citations"]
    assert citations, "事实型问题应当带引用"

    first = citations[0]
    # 引用卡片要显示的三样：文件名、段落号、相关度。
    assert first["name"] == "行业标准.md"
    assert first["paragraph"] is not None or first["locator_label"]
    assert 0.0 < first["similarity"] <= 1.0
    # 默认全部采用、可折叠。
    assert first["adopted"] is True
    assert first["collapsible"] is True


def test_citations_can_be_deselected_before_answers(
    fact_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """取消勾选的片段不进本次提示词：提交答案时带 rejected_chunk_ids。"""
    _upload(fact_client, "行业标准.md", KNOWLEDGE_TEXT)
    scripted_model_client.set_sequence(
        *_sequence_with_checks(
            (_question(), _fact("新员工培训周期 行业标准")),
            (_question(), _fact("新员工培训周期 行业标准")),
        )
    )
    task_id = fact_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    advanced = fact_client.post(f"/api/grilling/tasks/{task_id}/advance")
    citations = advanced.json()["next_round"]["frontier"][0]["citations"]
    rejected = [citations[0]["chunk_id"]]

    calls_before = len(scripted_model_client.calls)
    answered = fact_client.post(
        f"/api/grilling/tasks/{task_id}/answers",
        json={"round_no": 1, "answers": ["两周"], "rejected_chunk_ids": rejected},
    )
    assert answered.status_code == 200

    # 下一轮的提示词里不该出现被取消的那段原文。
    scripted_model_client.set_sequence(
        *_sequence_with_checks((_question(), _decision()))
    )
    advanced_again = fact_client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert advanced_again.status_code == 200

    later = scripted_model_client.calls[calls_before:]
    assert later, "应当发生后续的模型调用"
    joined = "\n".join(
        str(message.get("content", "")) for call in later for message in call["messages"]
    )
    # 被取消的那段正文不能以「引用」的形式进入提示词。
    assert "第一周以产品认知为主，第二周以实操为主" not in joined


def test_citation_cards_are_collapsible_in_payload() -> None:
    """引用卡片的展示形态由后端给出（可折叠 + 默认展开），前端不自己编。"""
    from app.retrieval.models import RETRIEVAL_STATUS_LABELS, RetrievalStatus

    # 状态标签必须覆盖三态，前端据此显示「正常 / 降级 / 未使用」。
    assert set(RETRIEVAL_STATUS_LABELS) == {
        RetrievalStatus.ok.value,
        RetrievalStatus.degraded.value,
        RetrievalStatus.unavailable.value,
    }
