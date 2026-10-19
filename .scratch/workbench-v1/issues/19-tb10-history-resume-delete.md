# TB-10 · 历史、续作与删除

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-3（12）；删除的成品关联弱依赖 TB-5（14）/ TB-6（15），可先做任务与对话部分

## 窄路径（四层触点）

- **schema**：任务状态机补全（进行中 / 已完成 / 已删除标记），删除留痕；历史查询用索引字段。
- **API**：历史列表（创作 / 分析分类、状态、时间）→ 打开详情并续作（含停在拷问中途的任务）→ 删除（先返回影响范围：对话、方案、成品文件）→ 失败路径不丢已存对话与方案。
- **UI**：左栏历史列表、续作跳转、删除确认弹层明示影响范围。
- **测试**：重建客户端续作测试（含拷问中途状态）；删除影响范围返回正确；模型失败后对话与方案仍在（负测）。

## 演示证据

拷问进行到一半关掉系统 → 重开 → 回到原轮次继续；删除一条任务先看到影响范围再确认。

## 验收

续作与删除测试绿；一次重启续作演示记录。

## Comments

- 2026-10-19 智能体（TB-10 **后端**实现者，作业方式：`tdd` 红→绿）：后端窄路径落地 + 顺手修掉约定笔记登记的 TB-4 已知缺陷。
  写域仅 `backend/**`；**未触碰 `frontend/**`**（前端侧缺口见「遗留」）。

  **实现摘要**

  - **schema**（`backend/app/db/database.py`）：`tasks` 补 `deleted_at`（删除留痕）+ 历史查询索引
    `idx_tasks_kind_status_id (kind, status, id)`；`init_db` 追加幂等 `_migrate`（按列名探测后 `ALTER TABLE`
    补列），老库无需手工迁移。
  - **状态机**：`in_progress` ↔ `completed` 走 `POST /api/tasks/{id}/status`（迁移刷新 `updated_at`，
    即「何时完成」）；`deleted` **只能**经 `DELETE` 达成（状态迁移入口拒绝 `deleted`，避免绕过影响范围确认）；
    已删除任务是留痕终态，再改状态 → 409。
  - **历史列表**：`GET /api/history?kind=&status=&limit=&offset=` → 当页条目 + `total` + 分页参数 +
    `counts{all,creation,analysis}`（导航 count 徽标）；条目带状态点与元信息行所需字段
    （`status` / `created_at` / `updated_at` / `dialogue_messages` / `rounds`）。
    **默认排除已删除任务**；显式 `status=deleted` 可查留痕。取舍：分页用 limit/offset（本地单用户库，
    offset 足够且前端 pager 直接拿 `total`）；排序按 `id DESC`（最近任务在前）。
  - **打开详情并续作**：`GET /api/history/{id}` 一次拿齐复原所需的一切（种子输入 / 各轮次 / 原始消息 /
    方案 / 待确认事项 + 未处置计数）与**下一步动作** `awaiting`（`answers` / `advance` / `plan_confirm` /
    `generation` / `completed` / `deleted`）与 `pending_round`（前沿已提出但尚未答完的轮次）。
    **停在拷问中途**即 `awaiting=answers` + `pending_round` 指向该轮；推导只依据规格 §4 已持久化数据
    （`app/history.py::derive_resume`），**不新建任何状态**，重启后同一份数据必得同一结论。
  - **删除（规格 US 27）**：`GET /api/tasks/{id}/deletion-impact` 先返回影响范围（对话条数 / 轮次 /
    方案份数 / 修订记录 / 待确认事项 / 成品文件数 + 人类可读 `summary`）；`DELETE /api/tasks/{id}`
    **不带 `confirm=true` → 409**，`detail` 就是影响范围 + 继续方式；带 `confirm=true` → 软删除
    （置 `deleted` 并留 `deleted_at`），对话 / 方案 / 版本记录一条不删，重复删除幂等且不漂移删除时间。
    成品文件数是**弱依赖** TB-5/TB-6：`app/db/generation_repository.py` 探测 `generations` 表是否落地，
    未落地如实返回 0（不伪造）。
  - **失败路径（规格 US 28 / US 26）**：新增 `app/providers/model_client.py::complete_text` 调用封装，
    把调用侧失败（`httpx.HTTPError`/`OSError`、以及未配置占位客户端）收敛为 `ModelCallError`，
    拷问 / 方案 / 修订三个入口据此返回 **502 可读原因**（此前是未处理的 500 堆栈）；数据本来就不在失败前
    被写坏，故用户可安全重试。
  - **顺手修「已知缺陷」（约定笔记 10-conventions.md §已知缺陷 · TB-4）**：`POST /api/grilling/tasks/{id}/plan/confirm`
    新增未处置待确认事项检查 → `has_unresolved` 为真时返回 **409**，detail 给出「还有 N 项未定 + 具体是哪几项
    （最多列 3 项）+ 如何处置（先确认或搁置）」，消灭了「方案已 confirmed 却因 open 条目无法生成（409）」的
    中间态；生成入口的同名判定保留为**纵深防御**（`generations.py` 注释已更新口径）。
    **注意**：`10-conventions.md` 的 TB-4 缺陷条目请编排者划掉/标注已修（该文件不在本单写域）。

  **验证证据（真实输出）**

  - `backend\.venv\Scripts\python.exe -m pytest --no-header` → `155 passed in 12.20s`
    （本单前为 129；新增 `backend/tests/test_history.py` 25 条，改 `backend/tests/test_open_items.py` 1 条并新增 1 条）
  - `backend\.venv\Scripts\python.exe -m ruff check backend` → `All checks passed!`
  - 覆盖点：历史分类/状态/分页/分计数、排除已删除 + 重建客户端后仍可读；详情续作三态
    （拷问中途 / 已答未推进 / 收敛待确认 → 生成）；**负测**：推进时模型调用失败 → 502 且对话与待确认事项
    逐字段不变、无半成品方案，模型恢复后重试方案恰好一份；方案生成失败（模型空返回）→ 502 且对话不变、
    重试唯一；首轮失败 → 502 但任务与种子输入仍在；删除影响范围计数（含修订记录）、未确认 → 409 且任务
    未被删、确认后软删除 + 数据仍可读、幂等、回收视图可查、老库迁移测试（已单独验证：不迁移时软删除
    报 `no such column: deleted_at`，即该测试确为有效红灯）。

  **演示记录（两次独立进程、同一个 SQLite 库 = 真正的「关掉重开」）**

  ```
  === 阶段 1：发起创作，拷问停在第 1 轮（未作答），然后关掉系统 ===
  POST /api/grilling/tasks: 201
  第一轮前沿: ["目标读者", "篇幅"]
  详情.awaiting: "answers"
  详情.pending_round.round_no: 1
  详情.pending_round.answers: []
  详情.dialogue.messages: 2

  === 阶段 2：重开（新进程 + 新应用实例，同一个库）===
  GET /api/history.total: 1
  历史条目: {"id":1,...,"status":"in_progress","dialogue_messages":2,"rounds":1}
  导航徽标分计数: {"all": 1, "creation": 1, "analysis": 0}
  重开后详情.awaiting: "answers"
  重开后详情.pending_round.round_no: 1
  回到原轮次作答: 200
  推进出下一轮: 2
  续作后.last_round_no: 2 / 续作后.awaiting: "answers"
  DELETE 未确认: 409
  DELETE 未确认.detail: "删除「帮我准备一份面向新员工的产品培训」将影响：对话 5 条（2 轮）、
    结构化方案 0 份（修订记录 0 条）、待确认事项 0 条、成品文件 0 个。删除为软删除：数据仍留在
    本地库中可留痕，但任务不再出现在历史列表。 确认无误后重试（加 confirm=true）。"
  DELETE 确认后.task.status: "deleted" / deleted_at: "2026-10-19T11:19:41.830226+00:00"
  确认后历史列表.total: 0；回收视图（留痕）仍可见该任务；对话仍可读（200）
  ```

  等价的可复现版本在测试里：`test_resume_stuck_mid_grilling_after_rebuilding_client`
  （关闭重建客户端后续作）、`test_delete_after_confirmation_soft_deletes_and_keeps_data`。
  演示脚本为一次性临时文件，未入库。

  **遗留（不在本单写域或缺决策，请编排者处置）**

  1. **前端侧缺口（TB-10 的 UI 层，本单未做）**：左栏「最近任务」列表（状态点 + 名称 + 元信息行）、
     导航项 count 徽标、历史页 pager 与导出按钮、删除确认弹层——后端接口已就位
     （`/api/history` 含 counts 与分页、`/api/tasks/{id}/deletion-impact`），待前端工单接上。
  2. **「保留清理」缺口**（约定笔记原型对齐表归 TB-10）：本单未实现——清理范围 / 保留天数属产品决策
     （规格 08 未给），且软删除已保证不丢数据；建议随隐私设置区（TB-7）一并定口径后再做，
     以免削弱 US 27 的「一次误操作不毁掉本地数据」。
  3. **既有缺口（非本单引入，供后续登记）**：
     a. 首轮即收敛（前沿为空）或首轮生成失败的任务无法推进——`advance` 在「无任何已作答轮次」时 422，
        这两态在库里不可区分，故未动（会破坏 TB-3 的既有语义）。
     b. grilling 流程未接入真实 provider 客户端：`app.state.model_client` 恒为 `UnconfiguredModelClient`
        （`get_model_client` 不读 provider 配置与密钥），真实联调前需 TB-1/TB-2 的接线工单补齐；
        本单只保证该情况下返回可读 502 而非堆栈。
     c. 重复对同一轮 `submit_answers` 会再追加回答（无重入保护）；`advance` 成功后再次调用会多产出一份方案行
        （`get_current` 取最新，功能不受影响，但会累积冗余行）。