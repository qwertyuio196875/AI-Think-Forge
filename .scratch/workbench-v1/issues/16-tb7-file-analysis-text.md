# TB-7 · 资料分析：文本类文件 → 总结

Status: closed — 已实现并合入 integration/workbench-v1
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

- 图片型 DOCX 仅识别并明示 `needs_ocr`，OCR 本身不在本工单范围。
- `embeddings` 表按 ADR-0002 预留，未参与本管线。

### 2026-10-19 · 前端补齐并合入集成分支

**提交**：后端 `3184e4e`；前端 `d37bd6e`；合并 `5db1cdc`（merge commit）。

**UI 触点（`frontend/src/views/AnalysisView.vue`）**

- 上传：拖拽 / 点击选择，前端先校验 TXT / MD / DOCX 与 50MB，XHR 真实上传进度；失败可读提示。
- 解析三态：`parsed` / `failed` / `unrecognized` 用不同色调与文案严格区分；回显文件名、分块数、编码、`heading_source`、图片数与未识别契约（`reason` / `locator` / `needs_ocr`），失败 / 未识别绝不显示成成功。
- 分析：进行中状态（逐块 N 次 + 综合 1 次如实文案，不伪造进度）；成功展示 ≤500 汉字总结、汉字数、`truncated`、引用来源（块号 + 位置 + 摘录）与实际档位（`provider_used` / `model_used` / `provider_fallback` / `provider_note`）。
- 操作：复制总结（clipboard + `execCommand` 回退）；一键送入主题创作后跳转 `/creation?task=`，任务在历史与侧栏可见。
- 扩展位：扩展名白名单单点（TB-8 扩展）、URL 输入保持禁用（TB-9）、来源行按 `source.kind` 渲染。

**验证**

- `npm run test:unit`：19 项通过（`analysisMeta` 纯函数）。
- `npm run build`：通过（element-plus 体积警告为既有问题）。
- 后端 `pytest`：217 项通过；`ruff check`：All checks passed。
- 合并后已在集成分支重跑上述前后端验证，全部通过。

**遗留**

- 真实模型总结卡 / 引用 / 档位回退渲染需持有效 Key 人工走查一次。
- 文件选择器触发的上传 → 分析全链路留人工验收。
- 历史页暂无来源反查端点，分析任务只能进任务详情，不能直达对应来源；已以如实文案降级。

### 2026-10-19 · 评审补齐：来源列表、回看与总结 Word（US16/US26）

**提交**：`f56b66c`（后端）→ `8989305`；前端 `de06390` + `17f85a0` → 合并 `0e941b6`；静态托管深链回退 `f7b15b4`。

**后端**
- `GET /api/analysis/sources?limit=&offset=`：返回来源、最新文档（解析状态、分块数、文件名）与总结标记；按最近更新倒序。
- `HistoryItem.source_id`：历史条目反查该任务最新来源，解决「分析任务只能进任务详情」的缺口。
- `POST /api/analysis/sources/{id}/summary/word`：用已保存总结 + Word 模板生成 `.docx`，新表 `summary_deliverables` 留痕；`GET /api/analysis/summary-deliverables/{id}` 下载，路径限定 `data/deliverables/`，越界 404。
- **不伪造 plan**：总结成品独立于 `generations`，不创建方案、不写生成记录，避免把资料总结冒充「已确认方案的成品」。
- 无总结时返回 409 可读提示；模板缺失/损坏/非 `.docx` 仍按 TB-5 口径明确报错。

**前端**
- 分析页新增「最近资料」列表，点一行经 `?source=` 恢复当时的文档、解析状态、总结与引用；历史页分析任务显示「来源 #N · 可回看解析与总结」与「回看」按钮。
- 总结卡新增「下载 Word」与模板选择（默认「全局默认模板」），显示实际所用模板。
- 解析三态仍严格区分 `parsed` / `failed` / `unrecognized`；恢复失败时明确提示，不把失败显示成成功。

**验证**
- 后端：`test_analysis_sources.py` 3 项、`test_summary_word.py` 7 项、`test_history.py` 来源字段回归；集成分支全量 **360 passed**，`ruff` 全绿。
- 真机联调（`data/demo/review-smoke.db`）：DOCX 上传 → 201 `parsed`、1 分块 → 最近资料 → `?source=1` 深链恢复 → 总结卡 → 「下载 Word」提示实际模板 `_builtin/minimal-default.docx`；`GET /summary` 200；历史「回看」跳转成功。
- 修复 `createWebHistory` 深链刷新 404：`SPAStaticFiles` 对非 `/api/**`、非 `/assets/**`、无扩展名路径回退 `index.html`；`/api/no-such` 与缺失静态文件仍 404。`test_spa_static.py` 覆盖。

**遗留**
- 来源列表当前存在 N+1 查询；单用户本地规模可接受，未优化。
- 真实模型生成的总结语义质量与引用渲染仍需持有效 Key 人工走查一次。
