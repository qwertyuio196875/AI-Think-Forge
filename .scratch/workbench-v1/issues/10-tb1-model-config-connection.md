# TB-1 · 模型配置与连接测试

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-0（09）

## 窄路径（四层触点）

- **schema**：模型配置非敏感字段（服务商、地址、模型名、是否默认、档位标签）+ 应用设置项；密钥字段不落库。
- **API**：配置增删改、设默认、连接测试；测试结果按错误类别区分（地址不可达 / 鉴权失败 / 模型名无效）。
- **UI**：设置页配置表单与测试按钮，显示清晰成功或失败原因。
- **测试**：注入 fake 模型客户端；三类错误各一负测。

## 关键决策落地

- 密钥存 Windows 凭据管理器，源码 / Git / 前端 / 日志与 SQLite 均不得出现明文。
- 默认服务商为阿里云百炼（OpenAI 兼容），默认档位主流程与总结分档；百炼端点与模型 ID 于本单开工前按事实确认。

## 演示证据

设置页填入百炼配置 → 点连接测试 → 成功提示；改坏密钥 → 失败提示可读；全库搜索无明文密钥。

## 验收

连接测试对百炼真连成功记录；三类错误负测绿。

## 决策变更（2026-10-19，编排者记录）

- **默认服务商由阿里云百炼改为 DeepSeek**（用户决策，见 `spec.md` §9）。百炼降级为「可选的用户自配 provider」，不再作为默认值硬编码。
- 原「对百炼真连成功记录」的验收改为：**对 DeepSeek 真连成功记录**。自动化测试仍走 fake 注入（规格 Testing Decisions：进程内、不联网）。
- 档位 `kind[turbo|plus|max]` 保留为**角色标签**（规格 §4；标签可空），`model_name` 为可编辑字段，默认值取当前有效 ID。**不得把已退市的 `qwen-turbo` 或任何过期 ID 写进默认值。**
- 接口事实以研究笔记为准：`01-bailian-facts.md`（百炼，含错误分类依据）、`03-deepseek-facts.md`（DeepSeek）。
- **DeepSeek 默认值（已核实）**：base_url `https://api.deepseek.com`（容忍客户端自动补 `/v1`）；默认模型 **`deepseek-flash`**（`deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 停用；另一有效模型为 `deepseek-v4-pro`）；默认**关闭思考模式**（`extra_body={"thinking":{"type":"disabled"}}` 或 `reasoning_effort="low"`），否则思维链 token 按输出计费会显著推高成本。
- **错误分类必须用「HTTP 状态码 + `error.type`」**：DeepSeek 的 `error.code` 恒为 `invalid_request_error`，不可用于分支判断；`GET /models` 的 401 返回**纯文本**而非 JSON，解析需防御性处理。
## Comments

- 2026-10-19 后端实现者（TB-1 窄路径，仅 `backend/**` + 根 `pyproject.toml` + `README.md`；未触碰 `frontend/**`）：

  **实现摘要**
  - schema：`providers(id, name UNIQUE, base_url, model_name, is_default, kind CHECK IN ('turbo','plus','max') 可空)`、`settings(key, value)`；**任何密钥列都不存在**（`PRAGMA table_info(providers)` 只有 6 列）。
  - 首次启动播种（幂等，以 `settings.providers_seeded_v1` 标记）：档位当角色标签，模型名取当前有效 ID——
    `DeepSeek 主流程` / `https://api.deepseek.com` / `deepseek-flash` / `kind=plus` / `is_default=1`；
    `DeepSeek 总结` / 同址 / `deepseek-flash` / `kind=turbo`；
    `DeepSeek 旗舰` / 同址 / `deepseek-v4-pro` / `kind=max`。无 `deepseek-chat`/`deepseek-reasoner`/`qwen-turbo`。用户清空 provider 后重启不回填。
  - 密钥：`keyring`（Windows 凭据管理器，实测后端 `WinVaultKeyring`），service 名 `ThinkForge/provider/<name>`。`get_password()` 返回 `None`/空串或抛 `KeyringError` 一律归一为「无密钥」。改名时迁移凭据；删除时清凭据。API 只回 `has_key: bool`。
  - 模型客户端：`app/providers/openai_client.py` 用 `httpx` 直连（无 `openai` SDK），实现 TB-0 `ModelClient` 协议；`POST <base>/chat/completions`，base_url 容忍 `/v1`；请求体固定带 `{"thinking":{"type":"disabled"}}`（DeepSeek 默认开启思考且 effort=high，思维链按输出计费）；默认超时 60s、`max_tokens=1024`。
  - 错误分类纯函数 `app/providers/errors.py::classify_status/classify_exception/parse_error_body`：按「HTTP 状态码 + `error.type`」分支（**不用 `error.code`**）；无状态码→`network_error`、401→`auth_error`、402→`insufficient_balance`、429→`rate_limited`、400/422→`model_error`/`request_error`（message 细分）、5xx→`server_error`；非 JSON 的纯文本 401（`GET /models`）解析防御性回退。
  - API（`/api` 前缀，沿用 `app/api/deps.py` 注入风格）：`GET/POST /api/providers`、`PUT/DELETE /api/providers/{id}`、`POST /api/providers/{id}/default`、`POST /api/providers/{id}/test`。
  - 日志脱敏：`app/security/redaction.py::redact`；客户端失败日志经其脱敏（实测日志含 `***`、不含完整密钥）。
  - 开发期 CORS（2026-10-19 追加）：`app/main.py` 挂 `CORSMiddleware`，仅放行本机开发源 `http://localhost:5173` / `http://127.0.0.1:5173`（常量在 `app/config.py`），方法仅 `GET/POST/PUT/DELETE`、头仅 `Content-Type`，**不使用 `allow_origins=["*"]`**；生产同源托管 dist 不受影响。测试 `backend/tests/test_cors.py`：5173 预检/实际请求带 `access-control-allow-origin`，非白名单源不带，且永不为 `*`。

  **测试与验证证据（真实输出）**
  - `backend\.venv\Scripts\python.exe -m pip install keyring` → `Successfully installed ... keyring-25.7.0`；依赖写入根 `pyproject.toml`（`keyring>=25.4`，并把 `httpx` 移入运行时依赖）。
  - `backend\.venv\Scripts\python.exe -m pytest -q` → **`76 passed, 1 warning in 1.65s`**（唯一接缝 = 进程内 HTTP，不联网、零真实花费；三类失败各一负测：`network_error`/`auth_error`/`model_error`，成功路径一例；另有纯函数真值表单测、SQLite 文件字节级无明文密钥断言、日志脱敏断言、CORS 来源白名单断言）。
  - `backend\.venv\Scripts\python.exe -m ruff check backend` → **`All checks passed!`**。
  - 真连链路 smoke（一次性、不入 pytest）：默认工厂未注入 fake，provider 指向本机不可达端口 → `{"ok": false, "category": "network_error"}`，证明真实 httpx 客户端已接通（`EXIT: 0`）。
  - 真实 keyring 只读核对：`WinVaultKeyring`；`get_key('不存在') -> None`。

  **真实连接测试操作手册**（配好 `DEEPSEEK_API_KEY` 后自证真连；已同步进 README「真实连接测试操作手册」）
  ```powershell
  # 先启动后端（启动.bat 或 uvicorn），然后：
  $env:DEEPSEEK_API_KEY = "<你的 DeepSeek Key>"
  Invoke-RestMethod -Method Put  http://127.0.0.1:8720/api/providers/1 -ContentType application/json -Body (@{ api_key = $env:DEEPSEEK_API_KEY } | ConvertTo-Json) | Out-Null
  Invoke-RestMethod -Method Post http://127.0.0.1:8720/api/providers/1/test | ConvertTo-Json
  ```
  预期 `"ok": true, "category": "ok"`；改坏 Key 重跑预期 `"category": "auth_error"`。未在无凭据时反复重试真实调用。

  **顺带修复（属 TB-1 验证范围）**：前端车道已产出 `frontend/dist`，其静态挂载在 `/` 会遮蔽 TB-0 `test_seams.py` 事后注册的路由。`create_app` 增补向后兼容的 `mount_frontend: bool = True` 参数，测试夹具传 `False`，使测试不再依赖构建产物。未改动 `frontend/**`。

  **遗留 / 风险**
  1. 真连 DeepSeek 的「真连成功记录」需你持凭据按上表手跑一次，本单仅以 fake + 不可达地址 smoke 作为自动化证据（规格：不联网）。
  2. 连接测试探针走一次最小 chat 调用（非 `GET /models`），会消耗极少量 token（`max_tokens=1024`，实际输出极短）；如需零 token 探测可后续改 `/models`。
  3. `ModelClientConfig.timeout_seconds` 默认 60s；长生成（TB-2+）需按 03-deepseek-facts §6 调大 read timeout（官方建议显著 >10 分钟）。
  4. 未实现 `GET /api/providers/{id}` 单条（规格 API 列表未要求）；`settings` 表已建但暂无独立读写 API（供后续工单）。
  5. `ProviderUpdate` 用 `exclude_none`，暂不支持把 `kind` 显式清空为 NULL。
