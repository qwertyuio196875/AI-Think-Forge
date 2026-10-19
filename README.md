# ThinkForge

个人 AI 阅读与内容创作工作台。运行在本机 Windows 上，把「阅读资料 → 辅助思考 → 完善想法 → 确认方案 → 生成成品」连成一条离线可用的本地工作流。

核心不是堆框架，而是**这条流程可靠、可持续使用**：用拷问式对话把模糊想法打磨成经你确认的结构化方案，再生成成品。任务状态全程持久化，模型可切换，密钥不出本机数据库。

> 术语以 [`GLOSSARY.md`](GLOSSARY.md) 为准。本文中「主题创作 / 拷问 / 轮次 / 前沿 / 结构化方案 / 方案确认 / 待确认事项 / 资料分析 / 总结 / 成品 / 模板 / 单文件 HTML / 任务 / 模型配置 / 连接测试」均为定义过的领域词汇。

---

## 核心工作流

### 主题创作（核心）

拷问式对话闭环，规则源自 Matt Pocock 的 grilling 技能（MIT，规则移植适配，见 ADR-0001）：

1. 用一句话、一段描述、一份文档或一份 PPT 发起任务；
2. 系统先解析输入、识别目标 / 背景 / 约束 / 已知信息，不重复询问你已提供的内容；
3. 每轮把当前**前沿**（现在就能问出口、无需猜测未听之答案）的问题一次问完，每题附推荐答案；
4. 下一轮问题根据你的回答动态重算，而非固定问题集；
5. 收敛后产出结构化方案（目标、读者、观点、章节、约束、风险、待确认事项等）；
6. 继续对话修订方案，直到你**显式确认**——未确认的推测只记为待确认事项，绝不直接变成成品。

### 资料分析

面向单份资料（DOCX / PDF / TXT / MD / PPTX 或公开网页 URL）的「解析 → 总结」快捷路径，默认不走拷问：总结 ≤500 汉字、分块 map-reduce 不遗漏、识别不了的内容明示、结论可一键送入主题创作。

---

## 当前状态

领域文档与规格已就位，**后端已落地 TB-0（行走骨架）、TB-1（模型配置与连接测试）、TB-2（拷问第一轮）、TB-3（收敛 → 方案 → 确认闸门）、TB-4（方案修订与待确认事项）与 TB-5（Word 成品与模板机制）并带自动化测试**；其余功能与前端仍在按曳光弹工单推进。除下表标 ✅ 者外，请以规格为准，勿当作已实现能力。

| 部分 | 现状 |
| --- | --- |
| 领域文档 | ✅ `GLOSSARY.md`、`docs/adr/0001~0003` |
| 规格与工单 | ✅ 权威规格 `.scratch/workbench-v1/issues/08-v1-unified-spec.md`；曳光弹工单 TB-0 ~ TB-10 |
| 页面原型 | ✅ `.scratch/workbench-v1/prototype/index.html`（静态自包含四视图，含评审标注 `REVIEW.md`） |
| 前端骨架 | ⚠️ 部分：三栏壳与四路由已就位；`src/views/` 视图组件与构建由并行前端工作推进 |
| 后端 | ✅ 行走骨架 TB-0：FastAPI 应用（`backend/app`）、`tasks` 最小表、健康检查与任务创建 / 列表 / 读取、模型客户端与 URL 抓取两个 fake 注入点接缝 |
| 模型配置与连接测试 | ✅ TB-1：`providers` / `settings` 表、DeepSeek 默认播种（3 档角色）、密钥存 Windows 凭据管理器、OpenAI 兼容 httpx 客户端、配置 CRUD 与连接测试（错误分级）、开发期仅本机源的 CORS |
| 拷问第一轮 | ✅ TB-2：`messages` 表（轮次 / 角色 / 内容 / 时间，问答同序落库）、版本化提示词资产（MIT 署名，见 ADR-0001）、LangGraph 最小节点图（分析输入 → 生成前沿 → 落库返回，前沿为空即停）、`/api/grilling/*` 发起 / 作答 / 读取对话 |
| 收敛 → 方案 → 确认闸门 | ✅ TB-3：`plans` 表（内容 / 状态 draft\|confirmed / 确认时间 / 关联轮次）、每轮按上轮回答重算前沿、前沿为空即收敛并生成结构灵活的结构化方案草稿、显式确认动作、生成入口在方案未确认时服务端拒绝（409）、版本化方案提示词资产 |
| 方案修订与待确认事项 | ✅ TB-4：`plan_revisions`（修订前 / 修订后 / 时间 / 差异提示，旧版本不丢）、`open_items`（来源轮次 / 条目 / 状态）、对话式修订（`POST …/plan/revisions`）与差异提示、前沿问题新增 `why`（为什么现在问）/ `alternatives`（备选方向）（资产升 `grilling-v2`）、「暂时跳过」入待确认事项、未处置条目拦截生成（409） |
| Word 成品与模板机制 | ✅ TB-5：`generations`（任务 / 方案 / 格式 / 产物位置 / **本次实际所用模板** / 时间）、`templates`（模板登记：名称 / 格式 / 是否默认）、确认方案后经 `python-docx` 生成 .docx（标题 / 正文 / 列表 / 表格按模板样式映射）、内置最小默认模板按需幂等生成、全局默认模板与任务级**临时覆盖**分离、产物**回读**完整性检查（US 22）、模板缺失 / 损坏 / 非 `.docx` 明确报错不静默空白生成 |
| 运行时目录 | ✅ `data/`（运行时 SQLite 落此处，gitignored）、`启动.bat`、根 `.gitignore`（覆盖 `/data/`、`/templates/`、`.slim/`） |
| 自动化测试 | ✅ `backend/tests`（pytest，进程内 HTTP 接缝，不联网；180 项通过） |

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.12 + FastAPI 单进程，仅监听 `127.0.0.1:8720`，同时托管前端构建产物与 `/api/*` |
| Agent 工作流 | LangGraph 状态机（拷问节点、逐轮持久化、任务可恢复） |
| 模型接入 | 统一 OpenAI 兼容客户端（`httpx` 直连，不引入厂商 SDK）；默认服务商 DeepSeek，档位 plus / turbo / max 为角色标签，可任务级切换 |
| 存储 | SQLite（任务、对话、方案、模板元数据、非敏感配置、生成记录）+ 文件系统（原始资料、模板、成品） |
| 密钥 | Windows 凭据管理器，SQLite 与日志均不落密钥 |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus，布局与工作台同构（左导航 / 中会话流 / 底部输入胶囊） |
| 成品 | Word（python-docx + 用户模板）+ 单文件 HTML 演示（OpenDesign 主题族适配，资源内联、`file://` 直开） |

---

## 目录结构

```
backend/          # FastAPI 应用包 app/（api、db、models、providers、grilling、analysis、generation、security）+ tests/ + scripts/（演示脚本）
frontend/         # Vue3 + TS + Vite + Element Plus；src/{api,layouts,router}（views 待落地）
data/             # 运行时数据（SQLite、上传件、生成产物 data/deliverables/）—— gitignore
templates/        # 用户 Word / PPT 模板 + 内置默认模板 templates/_builtin/ —— gitignore
docs/
  adr/            # 架构决策记录（ADR-0001 ~ 0003）
  agents/         # 智能体工作约定（issue 跟踪、分诊标签、领域文档）
.scratch/
  workbench-v1/
    spec.md       # v1 实施规格
    issues/       # 权威规格 08 与曳光弹工单 TB-0 ~ TB-10
    prototype/    # 静态页面原型 + 评审标注
GLOSSARY.md       # 领域术语表
```

---

## 快速开始

依赖：Node.js（已在 Node 24 / npm 11 下开发）、Python 3.12、Windows。

### 前端

```bash
cd frontend
npm install
npm run dev      # Vite 开发服务器，默认 http://localhost:5173
```

前端不做代理，直连后端 `http://127.0.0.1:8720/api`（见 `src/api/client.ts`）。后端为开发期提供了**仅放行本机开发源的 CORS 中间件**（`http://localhost:5173`、`http://127.0.0.1:5173`；方法 GET/POST/PUT/DELETE，头 Content-Type，不使用通配来源）；生产同源托管 `dist` 不受影响。后端未启动时，请求会被归类为「后端未启动」错误。

注意：开发服务器能起来，但路由懒加载的四个视图组件（`src/views/CreationView.vue` 等）尚未创建，因此进入任一页面都会加载失败；`npm run build` 与 `npm run type-check` 同样需先补齐这些组件。

### 后端

后端为 FastAPI 应用（`backend/app`），仅监听本机回环 `127.0.0.1:8720`，API 前缀 `/api`；`tasks` 表在应用启动时幂等建表，SQLite 文件落在 `data/`（gitignored）。

首次准备（在仓库根）：

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" pydantic httpx keyring langgraph python-docx pytest ruff
```

> 依赖记录在根 `pyproject.toml`（运行时依赖 + `dev` extras），不另设 `requirements.txt`。

运行测试（在仓库根；进程内 HTTP 接缝，不起端口、不联网）：

```powershell
backend\.venv\Scripts\python.exe -m pytest -q
```

启动后端（开发）：

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8720
```

或直接双击仓库根 `启动.bat`：拉起后端，若 `frontend/dist` 存在则由后端静态托管工作台并自动打开浏览器。

当前提供的 API：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 存活探针，返回 `{"status":"ok",...}` |
| POST | `/api/tasks` | 创建任务，body `{"kind":"creation"\|"analysis","title":string?}` → 201 |
| GET | `/api/tasks?kind=&status=` | 任务列表 `{"items":[...],"total":n}` |
| GET | `/api/tasks/{id}` | 单个任务；不存在返回 404 |
| GET | `/api/providers` | 模型配置列表（**不含密钥**，含 `has_key`） |
| POST | `/api/providers` | 新建模型配置，body `{"name","base_url","model_name","kind?","api_key?"}` → 201 |
| PUT | `/api/providers/{id}` | 编辑；`api_key` 可选，**传了才更新凭据**，否则保留 |
| DELETE | `/api/providers/{id}` | 删除配置，同时删除其凭据 → 204 |
| POST | `/api/providers/{id}/default` | 设为唯一默认 |
| POST | `/api/providers/{id}/test` | 连接测试，返回 `{"ok":bool,"category":str,"message":str}`；`category` ∈ `ok \| network_error \| auth_error \| model_error \| insufficient_balance \| rate_limited \| request_error \| server_error` |
| POST | `/api/grilling/tasks` | 从一句话 / 一段描述发起主题创作，body `{"idea":string}` → 201，返回 `{"task":Task,"round":{round_no,frontier:[{title,body,recommended_answer,why,alternatives}],answers}}`（第一轮前沿，1~5 个相互独立问题；每题带推荐答案，以及「为什么现在问」`why` 与「备选方向」`alternatives`，二者缺失容错） |
| POST | `/api/grilling/tasks/{id}/answers` | 提交某轮回答（与前沿问题一一对应），body `{"round_no":int,"answers":[string\|null]}`；`null`（或纯空白）= **暂时跳过**，该题入待确认事项、保持未定 → 写后对话状态 `Dialogue` |
| GET | `/api/grilling/tasks/{id}/dialogue` | 读取某任务的对话 / 轮次（种子输入 + 各轮前沿与回答 + 原始消息流），供前端渲染对话流 |
| POST | `/api/grilling/tasks/{id}/advance` | 按上一轮回答重算下一轮前沿；前沿为空即收敛并生成方案草稿。返回 `{"task_id","converged","next_round"\|null,"plan"\|null}` |
| GET | `/api/grilling/tasks/{id}/plan` | 读取当前结构化方案（`{id,task_id,round_no,content_md,status,confirmed_at}`）；尚无方案返回 404 |
| POST | `/api/grilling/tasks/{id}/plan/confirm` | **方案确认**：`draft → confirmed` 并记录 `confirmed_at`（进入生成阶段的唯一闸门） |
| POST | `/api/grilling/tasks/{id}/plan/revisions` | **对话式修订**：body `{"instruction":string}` → 更新方案正文并返回 `{"plan","revision"}`；`revision.change_summary` 为差异提示（`added/removed/modified` + 章节标题），旧版本留痕。方案回到 `draft`（原确认不再覆盖新内容） |
| GET | `/api/grilling/tasks/{id}/plan/revisions` | 方案的修订历史（逐条含修订前 / 修订后内容与时间）`{"items":[...],"total":n}` |
| GET | `/api/grilling/tasks/{id}/open-items` | **待确认事项**清单 `{"items":[{id,task_id,round_no,text,status,created_at,resolved_at}],"total":n}` |
| POST | `/api/grilling/tasks/{id}/open-items/{item_id}/resolve` | 处置一条待确认事项：body `{"status":"confirmed"\|"dismissed"}`（用户确认动作） |
| POST | `/api/tasks/{id}/generations` | **成品生成入口（硬闸门）**：方案未确认 / 无方案 → 409；**仍有未处置的待确认事项 → 409**；已确认且无未定条目 → 生成 Word 成品 → 201，返回成品记录 + 产物元数据（`template_style_applied` / `missing_styles` / `headings` / `integrity_ok`）。可选 body `{"format":"docx"\|"html","template":string?}`：`template` 为**任务级临时覆盖**（不改变全局默认）；`html` 一轨由 TB-6 落地，现返回 501。模板缺失 / 损坏 / 非 `.docx` → 400（明确报错，不产出成品） |
| GET | `/api/tasks/{id}/generations` | 某任务已生成的成品记录 `{"items":[{id,task_id,plan_id,format,file_path,template_used,created_at}],"total":n}` |
| GET | `/api/templates` | **模板清单**：模板目录里可被选用的模板（含内置 `_builtin/minimal-default.docx`）+ 是否全局默认 / 是否内置 / 是否可用 / 是否已登记 / 是否文件已缺失 |
| POST | `/api/templates` | **模板登记**：body `{"name":string,"is_default":bool?}`，登记已放入 `templates/` 的模板 → 201；只接受 `.docx`，`.dotx` / `.dotm` / `.docm`（含改名成 `.docx` 的模板类型文件）→ 400 并提示「请另存为 .docx」；文件不存在 → 404 |
| PUT | `/api/templates/{name}/default` | 设为该格式的**全局默认模板**（同格式至多一个） |

### Word 成品与模板机制

- **成品**：方案确认后，`POST /api/tasks/{id}/generations` 把结构化方案的正文确定性渲染成 `.docx`（不调用模型），产物落在 `data/deliverables/{任务 id}/`。
- **样式映射**：`Heading 1~3` / 正文 / 列表 / 表格 六类样式按**模板自己的定义**套用，因此「换模板 → 成品外观随模板变化」。
- **内置最小默认模板**：开箱可用，首次生成时按需幂等生成到 `templates/_builtin/minimal-default.docx`（**不往 Git 里塞二进制**；`templates/` 本身 gitignore）。它显式定义上述六类样式。
- **用户模板**：把 `.docx` 模板放进仓库根 `templates/` 即可被选用（`GET /api/templates` 会列出），机制不变；登记（`POST /api/templates`）只补「是否全局默认」等元数据。
- **默认模板 vs 临时覆盖**：`PUT /api/templates/{name}/default` 设**全局默认模板**；生成请求里的 `template` 是**任务级临时覆盖**——只影响当次生成，**不改变全局默认**，两者在数据与 API 上都分开。
- **每次生成记录实际所用模板**（`generations.template_used`，取 `templates/` 下的相对路径）。
- **明确报错而非静默降级**：模板缺失 / 损坏 / 是 `.dotx`、`.dotm`、`.docm` → 400 并提示「请另存为 .docx」；模板未定义某样式 → 该段回退为「直接设字号 / 加粗」并在产物元数据标 `template_style_applied: false`；产物回读完整性检查（US 22）未通过 → 丢弃产物、不落库、返回 5xx。
- **可复现演示记录**：`backend\scripts\demo_word_deliverable.py`（进程内 HTTP 接缝 + 脚本化模型替身，不联网）会真的生成 .docx 并回读打印章节与样式映射，含换模板、缺模板、非 `.docx`、样式回退四种情形。

### 真实连接测试操作手册（配好 `DEEPSEEK_API_KEY` 后自证真连）

自动化测试一律走 fake 注入、不联网。要在本机确认真连 DeepSeek，按下面一条命令跑（先启动后端，或让 `启动.bat` 拉起）：

```powershell
# 一条命令：把 Key 写入默认 provider 的凭据，再点一次连接测试
$env:DEEPSEEK_API_KEY = "<你的 DeepSeek Key>"
Invoke-RestMethod -Method Put  http://127.0.0.1:8720/api/providers/1 -ContentType application/json -Body (@{ api_key = $env:DEEPSEEK_API_KEY } | ConvertTo-Json) | Out-Null
Invoke-RestMethod -Method Post http://127.0.0.1:8720/api/providers/1/test | ConvertTo-Json
```

预期输出 `"ok": true, "category": "ok", "message": "连接成功"`。把 Key 改坏（删末尾一位）重跑，预期 `category` 为 `auth_error`。
密钥写入 Windows 凭据管理器（service 名 `ThinkForge/provider/DeepSeek 主流程`，可用 `cmdkey /list` 核对），SQLite 与日志中不会出现明文。
前端设置页的连接测试按钮（TB-1 前端车道）会调用同一接口，届时无需手敲命令。

---

## 架构决策（ADR）

| 编号 | 决策 |
| --- | --- |
| [0001](docs/adr/0001-grilling-uses-ported-rules.md) | 拷问工作流**规则移植**，不调用原始技能、不驱动外部 Agent CLI（应用自包含、状态可控） |
| [0002](docs/adr/0002-defer-rag-to-v1-1.md) | 首版**不做 RAG**，schema 预留，v1.1 第一优先补齐（空知识库上实现 RAG 零收益） |
| [0003](docs/adr/0003-output-formats-dual-track.md) | 输出**双轨**：v1 = Word + 单文件 HTML；PPTX 推迟到 v1.1，且与 OpenDesign HTML deck 分轨 |

---

## 路线图（曳光弹工单）

v1 以曳光弹方式推进，编号即依赖顺序；每条工单的验收证据见 `.scratch/workbench-v1/issues/`。

| 单 | 内容 |
| --- | --- |
| TB-0 | 行走骨架：tasks 最小表 + 健康检查 + 任务创建/列表/读取 + 三栏壳 + 启动脚本 |
| TB-1 | 模型配置与连接测试 |
| TB-2 | 拷问第一轮 |
| TB-3 | 收敛 → 结构化方案 → 确认闸门 |
| TB-4 | 方案对话式修订与待确认事项 |
| TB-5 | Word 成品（模板机制） |
| TB-6 | 单文件 HTML 演示成品 |
| TB-7 | 资料分析：文本类文件（TXT / MD / DOCX）→ 总结 |
| TB-8 | 资料分析：版式类文件（PDF / PPTX） |
| TB-9 | URL 分析 + SSRF 防护 |
| TB-10 | 历史、续作与删除 |

v1.1 队列（顺序即优先级）：RAG 最小版 → PPTX 填用户模板 → 文档型 HTML → 方案直接编辑 → exe 打包 → 模板版本管理。

---

## 测试与验收

- **唯一自动化测试接缝 = 本地工作台 HTTP API 边界**：进程内客户端驱动，不起真实端口、不开浏览器、不联网。
- 断言三类可观察结果：API 状态、持久化数据（「重启续作」靠重建客户端再读验证）、数据目录中的成品文件。
- 外部世界只有两个 fake 注入点：模型客户端（脚本化应答，零真实花费）与 URL 抓取（假响应 + 纯函数式 URL 安全校验负测）。
- 不对模型输出的语义质量做自动化断言，语义质量由人看证据链验收；前端走手工验收。

---

## 安全边界

- 仅监听本机回环 `127.0.0.1`，同网段他人无法使用。
- 文件访问限定工作目录白名单（`data/`、`templates/`），上传校验扩展名与大小上限（默认 50MB）。
- URL 抓取：仅 http/https；解析前后双检封禁环回 / 私网 / 链路本地 / 元数据地址；最大重定向 3、超时 15s、下载上限 5MB；需登录或受访问控制的站点如实提示且不绕过。
- 密钥存 Windows 凭据管理器，不入 SQLite、不入日志、不进前端。
- 调用云端模型前明确告知：提示词与资料片段可能发送给所配置的服务商——「本地运行」不等于「数据不出机」。

---

## 开发约定

- 分支主线为 `main`；issue 与规格以 `.scratch/<feature-slug>/` 下的 markdown 跟踪，约定见 [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)。
- 动手改代码前，先读 [`GLOSSARY.md`](GLOSSARY.md) 与涉及区域的 ADR；命名领域概念时严格使用术语表词汇。
- 与既有 ADR 冲突时明确摆出，不静默覆盖。

---

## 许可与署名

- 拷问机制基于 Matt Pocock 的 `grilling` 技能规则移植（MIT），保留署名；本项目**不声称**直接调用原始技能。
- HTML 演示主题取自 [nexu-io/open-design](https://github.com/nexu-io/open-design)（Apache-2.0，附属资源各自许可），使用时保留相应署名。
