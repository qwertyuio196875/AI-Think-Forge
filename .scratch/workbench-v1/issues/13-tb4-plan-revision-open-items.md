# TB-4 · 方案对话式修订与待确认事项

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-3（12）

## 窄路径（四层触点）

- **schema**：方案版本记录（前后内容、修订时间）、待确认事项清单（来源轮次、状态）。
- **API**：对已生成方案继续对话 → 方案更新；返回差异提示；待确认事项维护（未经确认的推测只入此清单）。
- **UI**：方案卡片标注变更摘要；待确认事项单独区块可见。
- **测试**：修订后内容确实变化且旧版本留痕；负测——待确认事项在确认动作前不得作为已定需求进入下游。

## 演示证据

对方案说"目标读者改成初级工程师" → 方案更新并显示变更摘要；待确认事项区块列出未定项。

## 验收

修订与负测绿；一次真实对话修订记录。

## Comments

- 2026-10-19 智能体（TB-4 后端窄路径，集成分支 integration/workbench-v1）：在本单范围内落地后端全部触点（含 B 节原型对齐增补 5、6），UI 一层留给 @designer（**未触碰 `frontend/**`**）。

  实现摘要：
  1. **schema**：新增 `plan_revisions(id, plan_id, task_id, instruction, previous_content_md, content_md, change_summary, created_at)`——每次对话式修订留一条版本记录（修订前 / 修订后 / 修订时间 / 差异提示），**旧版本不可丢**；当前正文仍以 `plans.content_md` 为准。新增 `open_items(id, task_id, round_no, text, status[open|confirmed|dismissed], created_at, resolved_at)`——待确认事项清单（来源轮次 / 条目 / 状态）。
  2. **对话式修订 API**：`POST /api/grilling/tasks/{id}/plan/revisions`（body `{instruction}`）→ 取当前方案 → 用新资产 `revision-v1` 渲染「当前方案 + 用户指令 + 已定 + 未定」→ 模型返回新正文 → **计算差异提示**（`app/grilling/revision.py`：按 Markdown 章节给出 `added/removed/modified` + 章节标题）→ 就地更新正文并把方案置回 `draft`（原确认不再覆盖新内容）→ 追加版本记录。`GET …/plan/revisions` 回查全部旧版本。差异粒度取**章节**：对用户而言「哪一节被改了」比字符级 diff 可读。
  3. **待确认事项维护**：`GET …/open-items`、`POST …/open-items/{item_id}/resolve`（`confirmed` / `dismissed`，记 `resolved_at`）。`app/db/open_item_repository.py` 提供 `open_texts`（喂提示词「未定」区块）与 `has_unresolved`（喂生成闸门）。
  4. **「暂时跳过」语义（增补 6）**：`AnswerSubmitRequest.answers` 改为 `list[str | None]`，`null`（或纯空白）即跳过；跳过的问题进入待确认事项（来源轮次 = 该轮），在 `messages` 表以 `（暂时跳过）` 占位落库（**保持「问题 ↔ 回答」按位对齐**，`rounds_from_messages` 依赖此配对），并在 `derive_determined` 中被排除——**不算已定决策**。
  5. **前沿问题新字段（增补 5）**：`FrontierQuestion` 增 `why`（为什么现在问）与 `alternatives`（备选方向）；解析层容错（空串归一为 `None`、空条目剔除），结构要求由提示词契约承担。
  6. **下游边界（负测）**：①提示词把「未定」单列成区块，跳过项只出现在「未定」，不出现在「已确定决策」（`render_frontier_messages` / `render_plan_messages` / `render_revision_messages`）；②生成闸门 `POST /api/tasks/{id}/generations` 新增判定——存在 `open` 条目即 409，用户处置后放行。

  提示词资产版本变更与偏离记录（ADR-0001 纪律，**显式记录、非静默走样**）：
  - `grilling-v1 → grilling-v2`（新增 `prompts/grilling_v2.md`，v1 资产保留可读）：输出契约新增 `why` / `alternatives`。依据规格 US 5 与原型的 `.q-why` / `.alt` 两栏。**偏离原规则**：原规则只要求「每题附推荐答案」，未要求给备选方向、也未要求说明问题为何在此时提出；本版把两者升为结构要求（解析层仍容错）。
  - `plan-v1 → plan-v2`（新增 `prompts/plan_v2.md`，v1 保留）：新增「未定（待确认事项）」输入区处理规则与「跳过即未定」规则。
  - 新增 `prompts/revision_v1.md`：为「方案定稿前的对话式修订」补规则（原规则只给停止条件、未规定修订），并限定修订只改文本、不改确认状态含义。
  - 三份资产的头部「版本变更记录 / 移植偏离」小节都写明了本次变更理由。

  涉及文件：`backend/app/db/{database.py,plan_repository.py,plan_revision_repository.py,open_item_repository.py,message_repository.py}`、`backend/app/models/{plan.py,grilling.py,open_items.py}`、`backend/app/grilling/{service.py,graph.py,frontier.py,open_items.py,revision.py,prompts/__init__.py,prompts/grilling_v2.md,prompts/plan_v2.md,prompts/revision_v1.md}`、`backend/app/api/{deps.py,routes/grilling.py,routes/generations.py}`、`backend/tests/{test_frontier_fields.py,test_open_items.py,test_plan_revision.py,test_grilling.py}`、`README.md`、本工单文件。

  验证证据（本机实际运行）：
  - `backend\.venv\Scripts\python.exe -m pytest --no-header` → `129 passed in 10.76s`（TB-3 原有 99 项全绿 + 本单新增 30 项）。
  - `backend\.venv\Scripts\python.exe -m ruff check backend` → `All checks passed!`。
  - 新增测试覆盖：修订后内容确实变化 + 差异提示（改 / 删 / 增各一类，未改章节不误报）+ 旧版本留痕可查（含连续两次修订首尾相接、重启后续作可查）；待确认事项读写 + 来源轮次 + 跳过入清单（`null` 与纯空白两种跳过写法）+ 处置状态迁移（`confirmed`/`dismissed`/非法状态 422/不存在 404）；**负测**——跳过项不进「已确定决策」区块（方案提示词与下一轮前沿提示词各一条）、方案已确认但存在 `open` 条目时生成被拒 409、处置后放行；frontier 新字段解析落库/返回与缺字段容错、`grilling-v2` 版本与偏离声明、v1 资产保留。

  显式决策（需编排者知悉，非偏离规格）：
  - **修订指令不写成 `messages` 的轮次消息**：术语「轮次」在 GLOSSARY 中指「拷问交互的单位（系统提一组问题、用户作答）」，一段修订指令不是轮次；把它塞进 `messages` 会产生「空前沿的轮次」，既污染对话流也会被下游误读。修订的「继续对话」记录改由 `plan_revisions.instruction` 承载（可经 `GET …/plan/revisions` 回查），前端可据此渲染「对方案说：X → 变更摘要」。
  - **生成闸门对未处置待确认事项的拦截**：术语「方案确认是进入生成阶段的**唯一**闸门」指「只有用户显式确认才放行、不做自动推进」；这里的 409 是把规格 US 9「未经我明确确认的推测绝不直接变成成品」落在服务端——`open` 条目即「尚未被确认的推测」，故闸门在其处置前保持关闭（处置为 `confirmed` 或 `dismissed` 均可解除）。两条判定互不取代。
  - **修订已确认的方案会把它置回 `draft`**：内容一变，原确认不再覆盖新内容（否则「未获批准的内容永不被写出」不成立）。原型上的「确认后锁定态」是前端展示选择，后端保持可修订以免用户被死锁。

  遗留：
  - 前端一层（方案卡变更摘要、待确认事项区块、跳过按钮、`.q-why` / `.alt`）归 @designer（本单未触碰 `frontend/**`）；接口契约见 README「当前提供的 API」表。
  - 「一次真实对话修订记录」需真实模型联调，按契约（约定层分工）由编排者统一补；自动化测试一律走 fake 注入。
  - 语义质量（修订是否切题、`why` / `alternatives` 是否说得对）不做自动化断言（规格 Testing Decisions），由人看证据链验收。
  - 生成管线本身仍属 TB-5/TB-6：闸门放行后暂返回 501（能力待落地）。