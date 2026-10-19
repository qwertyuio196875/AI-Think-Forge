# ThinkForge 工作台 v1 实施规格

- 状态：已确认（2026-10-19 拷问会话共识）
- 依据：GLOSSARY.md、ADR-0001（拷问移植）、ADR-0002（RAG 缓做）、ADR-0003（输出双轨）
- 约束：7 天日历天；用户每日审核带宽 ≤2h；预算 200 元阿里云百炼；开发主力为智能体，用户只做验收决策

## 1. 范围

**做**：三栏前端（Vue3+TS+Vite+Element Plus）｜LangGraph 移植版拷问闭环（前沿式每轮多题+推荐答案 → 结构化方案 → 对话式修订 → 方案确认）｜任务历史与中断续作（SQLite，每轮自动落库）｜资料分析（DOCX/PDF/TXT/MD/PPTX 上传 + URL 抓取，分块 map-reduce 总结 ≤500 字，未识别明示，总结一键送入主题创作）｜Word 生成（python-docx，内置最小默认模板，可换用户模板）｜单文件 HTML deck 生成（OpenDesign 主题适配、资源内联、file:// 直开、演讲者模式）｜模型配置（百炼默认、qwen-plus/turbo/max、连接测试最小版、Key 走 Windows 凭据管理器）。

**不做（v1）**：RAG、.pptx 输出、文档型 HTML 页、方案直接编辑、OCR、exe 打包、模板市场。

## 2. 架构决策

- 后端 FastAPI 单进程，仅监听 `127.0.0.1:8720`；托管前端 Vite build 产物 + `/api/*`。
- Agent 工作流用 LangGraph：拷问节点（状态机：分析输入→生成前沿问题→等待回答→重算）；每轮自动持久化，任务可恢复。
- 模型接入统一 OpenAI 兼容客户端（DashScope compatible-mode，端点与模型 ID 以 @librarian 核实结果为准），禁止业务代码绑定厂商 SDK。
- 密钥：Windows 凭据管理器（`keyring` 或 wincred），SQLite 只存非敏感配置；日志脱敏。
- 文件访问限定 `data/`、`templates/` 白名单目录；上传校验扩展名+大小上限（默认 50MB）。
- URL 抓取防护清单：仅 http/https、解析前+解析后双检封禁环回/私网/链路本地/元数据地址、最大重定向 3、超时 15s、下载上限 5MB。

## 3. 目录结构

```
backend/    # FastAPI 应用包 app/（api、db、models、providers、grilling、analysis、generation、security）+ tests/
frontend/   # Vue3+TS+Vite+Element Plus，views：创作/分析/历史/设置
data/       # 运行时数据（SQLite、上传件、生成产物）— gitignore
templates/  # 用户 Word/PPT 模板 + 内置默认模板 — gitignore
docs/adr/  GLOSSARY.md  .scratch/  启动.bat  .gitignore
```

## 4. 数据模型（SQLite）

`tasks(id, kind[creation|analysis], status, created_at, updated_at)`；
`messages(id, task_id, round_no, role, content, created_at)`；
`plans(id, task_id, content_md, status[draft|confirmed], confirmed_at)`；
`sources(id, task_id, kind[file|url], ref, meta_json)`；
`documents(id, source_id, path, parse_status)`、`document_chunks(id, document_id, seq, text, locator_json)`、`embeddings(document_id, model_version)`（ADR-0002 预留，不填充）；
`summaries(id, source_id, text, citations_json)`；
`generations(id, task_id, plan_id, format, file_path, template_used, created_at)`；
`providers(id, name, base_url, model_name, is_default, kind[turbo|plus|max 标签可空])`、`settings(key, value)`。

## 5. 工单与验收（`.scratch/workbench-v1/issues/`）

| # | 工单 | 验收证据 |
|---|---|---|
| 01 | 后端骨架+数据模型 | uvicorn 起、`/api/health` 200、建表测试过 |
| 02 | 前端骨架三栏壳 | `npm run build` 过、四路由渲染 |
| 03 | 模型配置/连接测试/凭据存储 | 对百炼真连成功截图级证据、Key 不落库日志 |
| 04 | 拷问闭环（核心） | LangGraph 每轮前沿提问→回答→方案→确认，单测模拟对话收敛 |
| 05 | 任务历史与续作 | 杀进程重开后任务状态/对话完整 |
| 06 | 资料分析管线 | 五种格式+URL 各一例真实总结、SSRF 负测全拦 |
| 07 | Word + HTML deck 生成 | 确认方案→产出 .docx 与 .html，双击 file:// 可开可翻页 |

## 6. 交付节奏（用户 14h 审核带宽版）

每工单完成 → 测试证据 + 一段演示产物 → 用户 10~20 分钟验收 → 下一单。第 04 单是价值核心，资源不足时先保 01/02/03/04/05，06/07 允许各顺延半天。

## 7. 风险登记

- 百炼端点/模型 ID/定价：@librarian 核实中，03 单动工前必须落定。
- HTML deck 内联体积（约几 MB）与 OpenDesign 主题署名文件（Apache-2.0 + 附属许可）。
- 拷问移植保真度：提示词以本机 grilling SKILL.md 规则为底，偏离处对照 ADR-0001 记录。

## 8. v1.1 队列（顺序即优先级）

RAG 最小版 → PPTX 填用户模板 → 文档型 HTML → 方案直接编辑 → exe 打包 → 模板版本管理完善。
