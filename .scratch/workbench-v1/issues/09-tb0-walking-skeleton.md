# TB-0 · 行走骨架（预重构）

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：无（全项目之根）

## 窄路径（四层触点）

- **schema**：tasks 表最小集（id、kind、status、时间戳），启动建表幂等。
- **API**：健康检查 + 任务创建 / 列表 / 按 id 读取，仅监听本机回环。
- **UI**：三栏工作台壳 + 四入口路由占位；创作页可新建任务并看到列表。
- **测试**：进程内 HTTP 接缝上 create → read-back；重建客户端后任务仍在（续作语义的最小证明）。

## 附带清理与约定

- 吸收现有未提交草稿（空的 backend venv、半成品 frontend 壳），确立目录骨架。
- 定下两个 fake 注入点约定（模型客户端、URL 抓取）供后续所有工单复用。
- 一条启动脚本：拉起后端并托管前端构建产物。

## 演示证据

双击启动脚本 → 浏览器出现工作台 → 新建一条任务 → 关掉重开仍在。

## 验收

pytest 接缝测试绿；启动脚本一份可复现的手工演示记录。

## Comments

- 2026-10-19 子智能体（fixer，TB-0 后端实现者）：在集成分支 `integration/workbench-v1` 完成 TB-0 窄路径的**后端部分**（写域：`backend/**`、根 `pyproject.toml`、根 `启动.bat`、根 `.gitignore`、`README.md`、本工单）。
  - **schema**：`tasks` 表最小集（`id`/`kind`/`title`/`status`/`created_at`/`updated_at`），应用 lifespan 幂等建表；SQLite 落 `data/`（gitignored），库路径可配置（`create_app(db_path=...)` 或环境变量 `THINKFORGE_DB_PATH`），测试用临时库。
  - **对规格 §4 的增补（唯一一处）**：最小集之外仅增加 `title TEXT`（可空，不设默认）。理由——规格 §4 最小集只有 id/kind/status/时间戳，而前端任务列表与 TB-10 历史需要可读标签；id/kind/status 语义未改动。已按工单要求在此记录。
  - **API**（前缀 `/api`，仅监听 `127.0.0.1:8720`）：`GET /api/health`；`POST /api/tasks`（→201）；`GET /api/tasks?kind=&status=`（`{"items":[],"total":n}`）；`GET /api/tasks/{id}`（不存在 →404 带 `detail`）。Task JSON 固定六字段，时间戳为 ISO8601 字符串。
  - **目录骨架**：`backend/app/{api,db,models,providers,grilling,analysis,generation,security}` + `backend/tests`；grilling/analysis/generation/security 按后续工单占位。
  - **两个 fake 注入点接缝**：`providers/model_client.ModelClient` 与 `providers/url_fetcher.UrlFetcher` 两个 Protocol，各配一个显式失败的默认实现；依赖注入点集中于 `api/deps.py`（`Depends` + 模块级 `Annotated` 别名），默认实例挂 `app.state`，测试经 `dependency_overrides` 替换。
  - **测试**：`backend/tests` 共 12 项，进程内 `TestClient`（httpx.ASGITransport），不起端口 / 不联网 / 不开浏览器；覆盖 health 200、create→read-back 字段一致、列表过滤与 total、**重建 app+客户端后任务仍在**（续作语义最小证明）、404、以及两个接缝可被 override。
  - **验证证据（真实输出）**：
    - `backend\.venv\Scripts\python.exe -m pytest -q` → `12 passed`（另有 1 条 Starlette/httpx 弃用告警，见遗留 2）。
    - `backend\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` → `All checks passed!`；`ruff format --check` → `25 files already formatted`。
    - 真实启动冒烟：`uvicorn app.main:app --host 127.0.0.1 --port 8720` → `GET /api/health` 200、`POST /api/tasks` 201、`GET /api/tasks` 200，并在 `data/` 生成 `thinkforge.db`；冒烟后已清理该库。
  - **遗留 / 未决**：
    1. `frontend/dist` 静态托管逻辑已就位，但 `dist` 由并行前端工作产出，本单**未构建、未验证**托管分支。
    2. FastAPI 0.146 / Starlette 1.9 对 `TestClient` 使用 `httpx` 发出 `StarletteDeprecationWarning`（建议改用 `httpx2`）；当前仅告警、不影响测试，后续可跟随上游调整。
    3. 本单**未实现任何业务**：模型客户端与 URL 抓取器均为显式失败占位（分别由 TB-1、TB-9 落地），URL 安全校验纯函数未实现（TB-9）。
    4. `title` 增补需后续工单沿用；若改回严格最小集，须同步前端与历史工单。
  - 说明：本单未执行任何改变 git 状态的命令，提交由编排者统一完成。