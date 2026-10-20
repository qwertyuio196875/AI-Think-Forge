"""TB-6 可复现演示记录：生成真实的单文件 HTML 演示并自证「离线可直开」。

在仓库根运行（会真的写文件，产物落在 `data/deliverables/`）：

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_html_deck.py

演示全程走**进程内 HTTP 接缝**（`TestClient`，不起端口、不联网），模型用内联脚本化
替身（零花费）——与自动化测试同一条路径，因此它既是演示也是证据链。打印：

- 产物体积与内联字体体积（base64 内联 vs 原始 woff2，调研 B2 的体积口径）；
- **外部网络引用扫描结果**（要求 0 条）；
- 主题、内联字体清单、`cjk_fallback`、页数、演讲者模式形态；
- 演示能力的静态证据（键盘监听 / 页码 / 演讲者覆盖层 / 脚本内联 = 断网 `file://` 可翻页）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app import config
from app.api.deps import get_model_client
from app.generation.deck import find_external_references, split_deck_document
from app.generation.fonts import FONT_ASSETS
from app.main import create_app

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# AI 编程工具使用指南\n\n"
    "从装环境到能自己改一个小工具。\n\n"
    "## 卡住人的从来不是模型\n"
    "- 环境：命令能跑通，报错对得上表\n"
    "- 提示词：一次只让工具做一件小事\n\n"
    "## 先跑通一次\n"
    "看到第一条结果之前，不要改任何设置。\n\n"
    "## 什么时候别用它\n"
    "- 需要精确复现的计算\n"
    "- 公司代码与内部数据\n\n"
    "| 项 | 值 |\n| --- | --- |\n| 篇幅 | 10 页 |\n"
)

# 调研 B2 记录的 OpenDesign 单文件导出限额（借来自检，本项目远低于该量级）。
ENTRY_LIMIT_BYTES = 2 * 1024 * 1024
ARTIFACT_LIMIT_BYTES = 100 * 1024 * 1024


class _ScriptedModelClient:
    """按顺序应答的模型客户端替身（演示不联网、零花费）。"""

    def __init__(self, *results: str) -> None:
        self._results = list(results)
        self._index = 0

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        index = min(self._index, len(self._results) - 1)
        self._index += 1
        return self._results[index]


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    return json.dumps(
        {
            "frontier": [
                {"title": title, "body": body, "recommended_answer": answer}
                for title, body, answer in triples
            ]
        },
        ensure_ascii=False,
    )


def _empty_frontier() -> str:
    return json.dumps({"frontier": []}, ensure_ascii=False)


def _report_artifact(label: str, path: str, body: dict) -> None:
    """打印产物体积、外部引用扫描、主题与内联字体清单（演示的核心证据）。"""
    artifact = Path(path)
    text = artifact.read_text(encoding="utf-8")
    document = split_deck_document(text)
    references = find_external_references(text)
    base64_bytes = sum(
        len(re.search(r"base64,([A-Za-z0-9+/=]+)", chunk).group(1))
        for chunk in re.findall(r"url\(data:font/woff2;base64,[^)]+\)", text)
    )
    raw_bytes = sum(
        asset.path.stat().st_size
        for asset in FONT_ASSETS.values()
        if asset.display_name in body["inlined_fonts"]
    )

    print(f"\n[{label}] {artifact}")
    print(f"  体积：{artifact.stat().st_size:,} 字节（{artifact.stat().st_size / 1024:.1f} KB）")
    print(f"  主题：{body['theme_used']}（记录里 template_used={body['template_used']}）")
    print(f"  页数：{body['slides']}；布局序列：{document['layouts']}")
    print(f"  内联西文字体（latin 子集）：{body['inlined_fonts']}")
    print(
        "  字体体积：原始 woff2 合计 "
        f"{raw_bytes:,} 字节 → base64 内联合计 {base64_bytes:,} 字节"
        f"（膨胀 {base64_bytes / raw_bytes:.2f}x；调研 B2 口径约 +33%）"
    )
    print(f"  中文回退系统字体：cjk_fallback={body['cjk_fallback']}")
    print(f"  外部网络引用扫描：{len(references)} 条 {references}")
    print(f"  声明保留的网络资源：{body['network_resources_declared']}")
    print(f"  演讲者模式：{body['presenter_mode']}")
    print(
        "  离线可用证据：脚本内联="
        f"{'<script>' in text and ' src=' not in text}"
        f"｜键盘监听={document['has_keydown_listener']}"
        f"｜按键={sorted(document['keys'])}"
        f"｜页码={document['has_page_counter']}"
        f"｜演讲者覆盖层={document['has_presenter_overlay']}"
    )
    print(
        f"  限额自检：入口 {ENTRY_LIMIT_BYTES:,} / 产物 {ARTIFACT_LIMIT_BYTES:,} 字节 → "
        f"{'通过' if artifact.stat().st_size < ENTRY_LIMIT_BYTES else '超限'}"
    )


def main() -> int:
    app = create_app(mount_frontend=False)
    model_client = _ScriptedModelClient(
        _frontier_json(("目标读者", "写给谁？", "新员工")), _empty_frontier(), PLAN_MD
    )
    app.dependency_overrides[get_model_client] = lambda: model_client

    with TestClient(app) as client:
        started = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()
        task_id = started["task"]["id"]
        client.post(
            f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
        )
        client.post(f"/api/grilling/tasks/{task_id}/advance")
        plan = client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").json()
        print(f"任务 {task_id}｜方案 {plan['id']}｜状态 {plan['status']}｜确认时间 {plan['confirmed_at']}")

        print("\n=== 1. 主题族清单（与前端主题选择器同一份事实）===")
        catalog = client.get("/api/deck-themes").json()
        for item in catalog["items"]:
            print(f"  {item['id']}｜{item['name']}｜palette={item['palette']}")
            print(f"    字体：{item['fonts']}｜许可：{item['license']}")
            print(f"    来源：{item['derived_from']}")
            print(f"    网络资源：{item['network_resources'] or '无'}")

        print("\n=== 2. 三套主题各生成一份单文件 HTML 演示 ===")
        for theme_id in ("slate", "ember", "mono"):
            response = client.post(
                f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": theme_id}
            )
            body = response.json()
            _report_artifact(f"主题 {theme_id}", body["file_path"], body)

        print("\n=== 3. 负测：未知主题 → 400，绝不静默退回默认主题 ===")
        unknown = client.post(
            f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": "hyper-neon"}
        )
        print("未知主题 →", unknown.status_code, unknown.json()["detail"])

        print("\n=== 4. 闸门：未确认方案不允许生成（与 TB-5 逐字一致）===")
        fresh = client.post(
            "/api/tasks", json={"kind": "creation", "title": "尚无方案的任务"}
        ).json()["id"]
        gated = client.post(f"/api/tasks/{fresh}/generations", json={"format": "html"})
        print("无方案 →", gated.status_code, gated.json()["detail"])

        records = client.get(f"/api/tasks/{task_id}/generations").json()
        print(f"\n成品记录（同一张 generations 表，format=html）：{records['total']} 份")
        for record in records["items"]:
            print(
                f"  #{record['id']} format={record['format']} "
                f"template_used={record['template_used']} file_path={record['file_path']}"
            )
        print(f"产物目录：{Path(config.DATA_DIR) / config.DELIVERABLES_SUBDIR / str(task_id)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())