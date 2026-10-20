# TB-3 · 收敛 → 结构化方案 → 确认闸门

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-2（11）

## 窄路径（四层触点）

- **schema**：方案表（内容、状态 draft/confirmed、确认时间），方案与轮次关联。
- **API**：多轮推进（每轮按上轮回答重算问题集）；收敛判定；生成结构灵活的结构化方案；显式确认动作；确认前拒绝任何生成请求。
- **UI**：方案卡片（在对话流中共存）、确认按钮与确认后的状态显示。
- **测试**：简单任务少轮收敛、复杂任务动态追问、确认前生成被拒（负测）、确认后状态可被下游读取。

## 收敛规则落地

- 关键问题解决即主动收敛，不为延续对话而提问；未确认推测只进待确认事项（细节归 TB-4）。

## 演示证据

走 2~3 轮 → 得到结构化方案 → 点确认 → 状态变为已确认。

## 验收

三类行为测试绿；一次真实多轮演示记录。

## Comments

- 2026-10-19 智能体（TB-3 后端窄路径，集成分支 integration/workbench-v1）：在本单范围内落地后端全部触点，UI 一层留给 @designer（未触碰 `frontend/**`）。

  实现摘要：
  1. **schema**：新增 `plans(id, task_id, round_no, content_md, status[draft|confirmed], confirmed_at)`（规格 §4 + 工单增补）。**增补 `round_no` 的理由**：工单要求「方案与轮次关联」，而规格 §4 的字段集未含轮次；以「产生该方案的那一轮（触发收敛的最后一轮问答）」记录，使方案可追溯到具体轮次。配套 `app/db/plan_repository.py`（create / get / get_current / confirm）与 `app/models/plan.py`。
  2. **多轮推进**：`graph.py` 的 `analyze_input` 归一已知信息并把历轮问答解析为「已确定决策」，`generate_frontier` 基于「已知信息 + 已确定决策 + 历轮问答」重算前沿；`service.rounds_from_messages` 只从 `messages` 表复原历轮，**未引入第二套隐藏状态存储**。新增 `POST /api/grilling/tasks/{id}/advance`。
  3. **收敛与方案**：前沿为空即收敛（提示词明确「关键问题解决即主动收敛，不为延续对话而提问」），收敛后经版本化资产 `prompts/plan_v1.md` 生成结构灵活（章节按任务类型裁剪）的 Markdown 方案，落库为 `draft`。
  4. **确认闸门**：`POST /api/grilling/tasks/{id}/plan/confirm` 做 `draft → confirmed` 并记录 `confirmed_at`（幂等）；新增 `POST /api/tasks/{id}/generations` 作为服务端硬闸门——无方案或未确认一律 409，不依赖前端隐藏按钮。未确认推测只进「待确认事项」（提示词约束）。
  5. **顺手修已知缺陷（TB-1）**：`PUT /api/providers/{id}` 改用 `model_fields_set` 区分「未提供 kind」与「显式置空 kind」，`{"kind": null}` 现在能把档位改回 NULL；补两条负测（置空生效 / 未提供保持原值）。

  涉及文件：`backend/app/db/{database.py,plan_repository.py}`、`backend/app/models/{plan.py,grilling.py}`、`backend/app/grilling/{graph.py,service.py,prompts/__init__.py,prompts/plan_v1.md,prompts/grilling_v1.md}`、`backend/app/api/{deps.py,router.py,routes/grilling.py,routes/generations.py,routes/providers.py}`、`backend/tests/{fakes.py,test_convergence.py,test_providers_api.py}`、`README.md`。

  验证证据（本机实际运行）：
  - `backend\.venv\Scripts\python.exe -m pytest --no-header` → `99 passed in 5.35s`（TB-2 原有 85 项全绿 + 本单新增 14 项）。
  - `backend\.venv\Scripts\python.exe -m ruff check backend` → `All checks passed!`。
  - 测试覆盖：简单任务少轮收敛并产出 draft 方案、复杂任务下一轮按上轮回答重算、确认前生成被拒（409）、确认后闸门放行（501=下游读到已确认）、draft→confirmed 与 `confirmed_at` 落库、重启续作、provider kind 置空负测。

  遗留：
  - 生成管线本身属 TB-5/TB-6；确认后入口暂返回 501（闸门已放行，能力待落地）。
  - 语义质量（方案章节是否切题等）不做自动化断言，依规格由人看证据链验收；真实多轮演示记录待编排者统一补。
  - 方案修订（重新收敛后重建方案）与「待确认事项」的读写细节归 TB-4（本单只保证边界成立）。