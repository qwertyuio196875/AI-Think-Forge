"""TB-8 可复现演示：PDF / PPTX → 分块 → 逐块分析 → 综合 → 页 / 幻灯片级引用。

在仓库根运行（会真的写文件，落在 `data/demo/`，该目录已被 .gitignore 忽略）：

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_analysis_layout.py

演示全程走**进程内 HTTP 接缝**（`TestClient`，真实 multipart 上传 + 真实 SQLite /
文件落盘；不起端口、不联网），模型用内联脚本化替身（**零花费**）。所以它既是演示
也是证据链：解析器标识、标题数、页 / 幻灯片 locator、未识别契约与模型调用次数都会打印。

样本构造复用测试用的同一份代码（`backend/tests/layout_samples.py`），避免演示样本与
测试样本漂移——本单不提交任何二进制样本文件。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
TESTS_DIR = BACKEND_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fastapi.testclient import TestClient
from layout_samples import (
    PDF_MIME,
    PPTX_MIME,
    corrupt_pdf_bytes,
    scanned_pdf_bytes,
    text_pdf_bytes,
    text_pptx_bytes,
)

from app import config
from app.db.provider_repository import ProviderRepository
from app.main import create_app
from app.providers.model_client import ModelClientConfig
from app.providers.tiered_client import TieredModelClient


class _NoKeyStore:
    """演示不触碰 Windows 凭据管理器。"""

    def get_key(self, provider_name: str) -> str | None:
        return None

    def set_key(self, provider_name: str, api_key: str) -> None:
        return None

    def delete_key(self, provider_name: str) -> None:
        return None

    def has_key(self, provider_name: str) -> bool:
        return False


class _ScriptedFactory:
    """固定返回同一个脚本化客户端，并记录解析到的 provider 配置。"""

    def __init__(self, client: _ScriptedClient) -> None:
        self.client = client
        self.configs: list[ModelClientConfig] = []

    def create(self, config: ModelClientConfig, *, api_key: str | None = None):
        self.configs.append(config)
        return self.client


class _ScriptedClient:
    """按提示词类型应答：逐块返回块分析、综合返回总结。"""

    def __init__(self) -> None:
        self.chunk_calls = 0
        self.reduce_calls = 0

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        user_content = messages[-1]["content"]
        if "逐块分析如下" in user_content:
            self.reduce_calls += 1
            return (
                "主题：季度进展与后续动作\n"
                "核心观点：先跑通阅读到创作的链路，再用小步交付降低风险\n"
                "关键内容：正文覆盖目标、范围与验收口径\n"
                "结论：本份资料可作为主题创作的输入"
            )
        self.chunk_calls += 1
        return (
            f"主题：第 {self.chunk_calls} 块的主题\n"
            "核心观点：围绕既有版面结构展开\n"
            "关键内容：标题 / 正文 / 表格已被逐块读出\n"
            "结论：本块结论明确"
        )

    @property
    def total(self) -> int:
        return self.chunk_calls + self.reduce_calls


def _upload(client: TestClient, name: str, payload: bytes, content_type: str) -> dict:
    return client.post(
        "/api/analysis/sources",
        files={"file": (name, payload, content_type)},
    ).json()


def _show_document(uploaded: dict) -> None:
    document = uploaded["document"]
    print(
        f"parse_status={document['parse_status']}｜parser={document['parser']}"
        f"｜heading_source={document['heading_source']}｜标题数={document['headings']}"
        f"｜图片数={document['images']}｜分块数={document['chunks']}"
    )
    print(f"落盘位置：data/{uploaded['source']['ref']}")
    if uploaded["unrecognized"]:
        print(f"未识别（一级）：{uploaded['unrecognized']}")
    for part in uploaded["unrecognized_parts"]:
        print(f"未识别（逐项）：{part}")


def _show_summary(client: TestClient, uploaded: dict, scripted: _ScriptedClient) -> dict:
    source_id = uploaded["source"]["id"]
    before = scripted.total
    result = client.post(f"/api/analysis/sources/{source_id}/analyze").json()
    summary = result["summary"]
    print(
        f"逐块调用={summary['chunk_count']}｜本次新增模型调用={scripted.total - before}"
        f"｜总结汉字数={summary['hanzi_count']}｜truncated={summary['truncated']}"
        f"｜provider={summary['provider_used']}（{summary['provider_kind']}）"
    )
    print(f"总结前 60 字：{summary['text'][:60]}…")
    for citation in summary["citations"]:
        print(
            f"  分块 {citation['chunk_seq']}｜位置 {citation['locator']}"
            f"｜摘录 {citation['excerpt'][:28]}…"
        )
    return summary


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # 演示输出只保留接缝证据：pypdf 对损坏文件的告警在这里是噪声（失败已由 API 明示）。
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    demo_dir = config.DATA_DIR / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    db_path = demo_dir / "tb8-demo.db"
    db_path.unlink(missing_ok=True)

    app = create_app(db_path=db_path, mount_frontend=False)
    scripted = _ScriptedClient()
    app.state.tiered_model_client = TieredModelClient(
        ProviderRepository(db_path), _NoKeyStore(), _ScriptedFactory(scripted)
    )

    with TestClient(app) as client:
        print("=== 1. PDF：正文 / 标题 / 页码引用 ===")
        pdf_upload = _upload(client, "季度报告.pdf", text_pdf_bytes(), PDF_MIME)
        _show_document(pdf_upload)
        _show_summary(client, pdf_upload, scripted)

        print("\n=== 2. PPTX：每页标题 / 正文 / 表格 + 幻灯片级引用 ===")
        pptx_upload = _upload(client, "方案.pptx", text_pptx_bytes(), PPTX_MIME)
        _show_document(pptx_upload)
        _show_summary(client, pptx_upload, scripted)

        print("\n=== 3. 扫描件 PDF：明示未识别、不调用模型 ===")
        scanned_upload = _upload(client, "扫描件.pdf", scanned_pdf_bytes(), PDF_MIME)
        _show_document(scanned_upload)
        before = scripted.total
        scanned_analysis = client.post(
            f"/api/analysis/sources/{scanned_upload['source']['id']}/analyze"
        ).json()
        print(
            f"summary={scanned_analysis['summary']}"
            f"｜unrecognized={scanned_analysis['unrecognized']}"
            f"｜新增模型调用={scripted.total - before}"
        )
        print(f"提示：{scanned_analysis['message']}")

        print("\n=== 4. 损坏 PDF：明确报错，不丢已存数据 ===")
        broken_upload = _upload(client, "损坏.pdf", corrupt_pdf_bytes(), PDF_MIME)
        print(
            f"parse_status={broken_upload['document']['parse_status']}"
            f"｜message={broken_upload['message']}"
        )
        blocked = client.post(
            f"/api/analysis/sources/{broken_upload['source']['id']}/analyze"
        )
        print(f"分析被拦：HTTP {blocked.status_code}｜{blocked.json()['detail']}")

        print("\n=== 5. 演示数据位置 ===")
        print(f"演示库：{db_path}")
        print(f"上传件目录：{config.DATA_DIR / 'uploads'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
