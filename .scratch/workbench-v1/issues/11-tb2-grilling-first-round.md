# TB-2 · 拷问第一轮

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-0（09）；真实凭据依赖 TB-1（10），测试不依赖

## 窄路径（四层触点）

- **预重构（单内前置）**：把移植的 grilling 规则固化为版本化提示词资产，保留 MIT 署名（ADR-0001）。
- **schema**：对话消息表（任务、轮次、角色、内容、时间），回答与问题同序落库。
- **API**：从一句话 / 一段描述发起创作；产出第一轮"前沿"问题集（1~N 个相互独立问题，每题附推荐答案）；提交回答。
- **UI**：创作页对话流 + 当前问题卡片（题目、推荐答案、作答入口）。
- **测试**：脚本化模型应答下断言——不重复询问输入中已明确的信息、每题带推荐答案、往返内容正确落库。

## 演示证据

一句话发起 → 看到第一轮问题与各题推荐答案 → 作答 → 对话流出现我的回答。

## 验收

接缝测试绿；一次真实模型的单轮演示记录。

## Comments

- 2026-10-19 后端实现者（TB-2 后端窄路径；写域仅 `backend/**` + 根 `pyproject.toml` + `README.md`，未触碰 `frontend/**`）：

  **实现摘要**
  - 预重构 · 版本化提示词资产：`backend/app/grilling/prompts/grilling_v1.md`（版本常量 `GRILLING_PROMPT_VERSION = "grilling-v1"`，代码经 `app.grilling.prompts` 引用，规则不散落）。资产保留 **MIT 署名**（「基于 Matt Pocock 的 grilling 技能规则适配版」），并落地设计树 / 前沿 / 轮次推进 / 每题附推荐答案 / 事实由系统查·决策归用户 / 前沿为空即停；资产内嵌输出契约 JSON。
  - schema：`messages(id, task_id, round_no, role, content, created_at)`（规格 §4），`role CHECK IN ('system','assistant','user')`，索引 `(task_id, round_no, id)`。种子输入记 `round_no=0`，前沿轮次从 1 起；同轮内 assistant（问题集）先于该轮 user（回答），顺序由自增 id 保证。**问题集结构化存进 assistant 消息 content**：`{"frontier":[{"title","body","recommended_answer"},...]}`；user 消息 content 为纯文本回答。**轮次与消息的持久化只走这张表**，未引入第二套隐藏状态存储。
  - API（沿用 `/api` 前缀与 `app/api/deps.py` 注入风格，新增 `MessageRepositoryDep`）：`POST /api/grilling/tasks`（一句话发起 → 建 `creation` 任务 + 第一轮前沿）、`POST /api/grilling/tasks/{id}/answers`（写回答 → 返回写后对话状态）、`GET /api/grilling/tasks/{id}/dialogue`（复原对话流）。选用**新增 grilling 入口**而非扩展 `POST /api/tasks`：`/api/tasks` 保持纯任务 CRUD（TB-0 接缝），拷问专属流程自带语义（前沿 / 轮次 / 作答）更适合独立路由；代价是任务创建逻辑在两处，但复用同一 `TaskRepository`。
  - LangGraph：`backend/app/grilling/graph.py` 落地**最小节点图** `分析输入 → 生成前沿问题 →（条件）落库并返回 /（前沿为空）收敛停止`；一次 `invoke` 推进一轮。依赖（`ModelClient`、`MessageRepository`、`model_name`）以闭包注入，路由按请求构图。扩展点：`analyze_input` 留给 TB-3 做目标/背景/约束识别并纳入历轮消息，`generate_frontier` 留给 TB-3/TB-4 基于已定决策重算前沿。**LangGraph 与当前切片适配，未偏离、未跳过**。
  - 不重复询问已知信息：`render_frontier_messages()` 把用户原始输入以「已知信息（用户已提供，视为已确定，绝不再问）」写进提示词 —— 该渲染被测试直接断言（fake 记录的 messages 含原始 idea 与「已知信息」字样）。
  - 每题必带推荐答案：`FrontierQuestion.recommended_answer` 为必填（`min_length=1`），解析层 `parse_frontier` 校验；缺字段抛 `FrontierParseError` → API 返回 502。**结构强制，非模型自觉**。
  - 模型名走默认 provider（`ProviderRepository.get_default()`，播种值 `deepseek-flash`），经 TB-0/TB-1 的 `ModelClient` 接缝调用；测试全部走 `ScriptedModelClient` fake（零真实花费、不联网）。

  **提示词资产版本与显式偏离**（ADR-0001 纪律）
  - 版本：`grilling-v1`（`backend/app/grilling/prompts/grilling_v1.md`）。
  - 偏离 1：**每轮问题数上限 5**（`MAX_FRONTIER_QUESTIONS`，原规则未设上限，只要求一轮问完整条前沿）——超限按上限截断。
  - 偏离 2：**输出语言为简体中文**（原规则为英文）。
  - 偏离 3：**输出为结构化 JSON**（便于前端渲染题目 / 推荐答案 / 作答入口卡片），替代原规则的 `❓/➡️` 纯文本轮次格式。
  - 上述偏离均写进资产头部「移植偏离」段，可被测试断言（含「偏离」「简体中文」「Matt Pocock」「MIT」字样）。

  **验证证据（真实输出）**
  - `backend\.venv\Scripts\python.exe -m pip install langgraph` → `Successfully installed ... langgraph-1.2.16 ...`；依赖写入根 `pyproject.toml`（`langgraph>=1.2`）。
  - `backend\.venv\Scripts\python.exe -m pytest --no-header` → **`85 passed in 3.06s`**（TB-2 新增 9 项：前沿数量在 1~5 且各带推荐答案、超限截断、提示词含已知输入、缺推荐答案被拒 502、回答按 round_no+顺序往返并重建 app 后复原、回答数不匹配 422、缺任务 404、前沿为空不再提问、提示词资产版本/署名/偏离）。
  - `backend\.venv\Scripts\python.exe -m ruff check backend` → **`All checks passed!`**。

  **遗留 / 下一步**
  - 本单只落第一轮的前沿生成与作答落库；**作答后重算下一轮（TB-3）未实现** —— 图与提示词已留好扩展点。
  - 真实模型单轮演示记录待编排者/用户在有 DeepSeek Key 的环境补跑（自动化测试按规格一律走 fake）。
  - 任务级模型切换（TB-3+）：当前固定用默认 provider 的模型名，接口已按「取默认」实现，切换只需换 `model_name` 来源。
  - 未实现任务删除时的消息清理（TB-10 范畴）；`messages.task_id` 已声明 `REFERENCES tasks(id)`，启用外键 `PRAGMA` 后可级联，现未开启。