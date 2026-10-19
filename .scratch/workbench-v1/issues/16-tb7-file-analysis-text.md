# TB-7 · 资料分析：文本类文件 → 总结

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-0（09）、TB-1（10，需真实模型）

## 窄路径（四层触点）

- **schema**：来源登记、文档、文本分块（含位置 locator 字段；嵌入相关字段按 ADR-0002 预留不填）、总结、引用关联。
- **API**：上传校验（扩展名 + 大小上限）→ 解析 TXT / MD / DOCX（正文、标题、基本结构）→ 长文分块 → 逐块分析 → 综合成 ≤500 汉字总结；未识别内容明示；解析失败给出明确提示；总结可复制 / 保存 / 一键送入主题创作。
- **UI**：分析页上传区、进度、总结展示与引用来源、送入创作入口。
- **测试**：脚本化模型下分块与综合次数正确、总结长度上限、未识别提示路径；失败提示不丢已存数据。

## 关键决策落地

- "分块 → 逐块 → 综合"是分析管线，不称 RAG；分析默认不进入拷问流程（需求 17）。

## 演示证据

传一份长 DOCX → 得到 500 字内总结与来源位置 → 一键送入创作，新任务预填该来源。

## 验收

分块与长度测试绿；一次真实长文演示记录。

## Comments

### 2026-10-19 · 后端实现完成（待编排者提交）

**范围**：仅 `backend/**`、`pyproject.toml`、`README.md`、本工单；未触碰 `frontend/**`，未执行任何改变 git 状态的命令（无 add / commit / checkout / stash / reset / push）。

**schema（`backend/app/db/database.py`）**

- `sources`：来源登记，新增 `task_id` 关联。
- `documents`：原文与解析结果；含 `parse_status`、`parse_message`、`heading_source`、`encoding`、`headings`、`images`、`unrecognized_json`、`unrecognized_parts_json`。
- `document_chunks`：文本分块 + `locator_json`（字符区间 / 段落号 / 标题路径）。
- `summaries`：`citations_json` 引用关联，以及 `task_id`、`chunk_count`、`truncated`、`provider_kind`、`provider_used`、`model_used`、`provider_fallback`、`provider_note`。
- `embeddings`：按 ADR-0002 **仅建表预留，不写入**。

**API（`backend/app/api/routes/analysis.py`）**

- `POST /api/analysis/sources`：multipart 上传 → 扩展名白名单（`.txt` / `.md` / `.docx`）+ 50MB 上限 → 落 `data/` 白名单目录 → 解析 → 分块；返回来源、文档状态与分块数。
- `POST /api/analysis/sources/{id}/analyze`：逐块 map + 1 次综合 reduce，落总结与引用。
- `GET /api/analysis/sources`、`GET /api/analysis/sources/{id}`：读取来源、总结、引用位置。
- `POST /api/analysis/sources/{id}/send-to-creation`：创建 `creation` 任务，以 `SEED_ROUND_NO=0` 预填总结为已知信息，**不调用模型**。
- 解析失败：上传仍返回 201 并保留来源与文件，`document.parse_status="failed"` + 可读 `message`；此时分析返回 409，不丢已存数据。
- 未识别内容：命中短路直接返回 200、`summary=null`，契约字段为 `{unrecognized: true, reason, locator, needs_ocr}`，绝不以空字符串冒充成功。
- `POST /api/templates/upload`（`backend/app/api/routes/templates.py`）：multipart 模板上传，仅接受 `.docx`，复用同一套扩展名 + 大小校验，落 `templates/`；同名已存在返回 409，不静默覆盖；损坏文件先写后验、失败删除。

**解析与分块**

- TXT：`utf-8-sig` → `gb18030` → `charset-normalizer` 依次尝试，记录实际 `encoding`。
- MD：`markdown-it-py` token 流提取标题与正文。
- DOCX：优先 `paragraph.style.name`；样式缺失时启发式回退，并用 `heading_source` 标明来源。
- 分块：目标 1200 字符、上限 1800 字符，按段落/标题边界切分，`locator_json` 保留可回溯位置。

**总结与档位**

- 长度收敛：硬切到第 500 个汉字之前，优先回退到 ≥60% 上限处最后一个句读；未以句读结尾补 `…`；记 `truncated=True`。
- 档位（`backend/app/providers/tiered_client.py`）：新增 `TieredModelClient.resolve(kind)` + `ProviderRepository.get_by_kind`，总结走 `turbo` 档；缺失时回退默认档并写 `provider_fallback` / `provider_note` 如实记录。
- 主流程仍使用 `ProviderBackedModelClient`，拷问与方案行为不变（测试夹具只替换 `app.state.tiered_model_client` 可证）。

**命名纪律**：代码与文档均将本管线称为「资料分析 / 分块-逐块-综合」，未使用 RAG 指代；`embeddings` 仅作 ADR-0002 预留。

**测试**

- `backend/tests/test_analysis.py`（11 项）：分块数与综合调用次数、500 汉字上限、未识别短路、解析失败保留数据、模型失败提示、档位回退、一键送入创作零模型调用、引用位置等。
- `backend/tests/test_template_upload.py`（4 项）：仅 `.docx`、大小上限、同名 409、损坏文件清理。
- 唯一外部接缝为进程内 HTTP；模型用 fake 脚本化，测试不联网。

**验证证据**

- `pytest --no-header`：**217 passed**（基线 202，新增 15，只增不减）。
- `ruff check backend`：**All checks passed**。
- 演示 `backend/scripts/demo_analysis_long_docx.py`：320 段长 DOCX → 25 分块；逐块 25 + 综合 1 = 26 次调用；总结 480 汉字（句读收敛，`truncated=True`）；turbo 档 `DeepSeek 总结`、`fallback=False`；25 条引用；一键送入创作新增模型调用 0；图片型 DOCX 返回 `parse_status=unrecognized`、`reason=no_text_layer`、`needs_ocr=true`、新增模型调用 0。

**遗留**

- UI 触点（上传区、进度、总结展示、送入创作入口）属前端范围，本工单后端已就绪，待前端接入。
- 图片型 DOCX 仅识别并明示 `needs_ocr`，OCR 本身不在本工单范围。
- `embeddings` 表按 ADR-0002 预留，未参与本管线。
