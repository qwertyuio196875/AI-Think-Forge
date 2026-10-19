# TB-9 · URL 分析 + SSRF 防护

Status: closed — 已实现（后端侧；待编排者验收 / 提交）
规格：08-v1-unified-spec.md
阻塞边：TB-7（16，复用同一总结管线）

## 窄路径（四层触点）

- **schema**：来源类型扩展为 URL（保留抓取时间、最终地址、内容摘要元数据）。
- **API**：URL 输入 → 安全校验（仅 http/https；拒绝环回 / 私网 / 链路本地 / 云元数据地址；重定向上限；超时与下载大小上限）→ 抓取 → 正文提取并过滤导航 / 广告 → 进入同一分块总结管线；需登录 / 受访问控制 / 抓取失败如实提示且不绕过。
- **UI**：分析页 URL 输入与安全拒绝原因展示。
- **测试**：安全校验器以纯函数负测（各类禁止地址与非法协议必须拦）；假 fetch 注入下正文提取与总结路径正确；失败提示路径。

## 演示证据

抓取一个公开网页并得到总结；输入本机地址与云元数据地址被明确拒绝并说明原因。

## 验收

安全负测全绿；一次公开网页真机演示记录。

## Comments

### 2026-10-19 · 后端实现完成（独立 worktree `agent/tb9-url`）

**范围**：`backend/**` 与根 `pyproject.toml` 及本工单；**未触碰** `frontend/**`、`README.md`（由编排者统一更新）。无 schema 变更（`sources.kind` 早已含 `url`、`documents` 字段齐全，URL 类复用同表）。

**安全校验器（`backend/app/security/url_guard.py`，纯函数）**

- `validate_url(url, *, resolver=None, resolve=True)` + `classify_address(address)`：除 DNS 解析外全部纯函数，可独立负测。
- 仅 `http` / `https`；拒绝 URL 内嵌用户名 / 密码。
- 封禁：环回（127/8、::1）、私网（10/8、172.16/12、192.168/16、100.64/10、fc00::/7）、链路本地（169.254/16、fe80::/10）、**云元数据**（169.254.169.254、fd00:ec2::254，原因码精确到 `metadata`）、未指定（0.0.0.0、::）、组播（224/4、ff00::/8）、保留（240/4、2001:db8::/32 等）；IPv4 映射的 IPv6 按内层 IPv4 判定（`::ffff:10.0.0.1` 也拦）。
- **解析前 + 解析后双检**：字面量地址当场判；域名解析后逐个复核结果地址，任一命中即整体拒绝（防 DNS rebinding）。解析失败 → `dns_failure`，不静默放行。
- 路由层用 `resolve=False` 做**不联网的前置拒绝**（拒绝时不落库、不抓取）；DNS 复核由抓取器逐跳完成，因此 HTTP 边界测试无需真实 DNS。

**抓取器（`backend/app/providers/url_fetcher.py`，扩展既有注入接缝）**

- 协议改为返回 `FetchedPage{url, final_url, status, content_type, body, fetched_at, redirects, size}`（元数据如实入库）；失败一律 `UrlFetchError{reason}`：`blocked_address` / `redirect_limit` / `timeout` / `login_required`(401/403/407) / `http_error` / `body_too_large` / `network_error`。
- `HttpUrlFetcher`：`follow_redirects=False` 手动跟跳，**每一跳先 `validate_url` 再请求**，最多 3 跳；超时 15s；流式读取上限 5MB；普通浏览器 UA。注入接缝 `resolver` 与 `client_factory`（测试用 `httpx.MockTransport`）。URL 内嵌凭据 / 私网跳转一律拒绝，**不做任何绕过尝试**（不带 Cookie 试探、不改 UA 伪装）。
- `app.state.url_fetcher` 生产默认改为 `HttpUrlFetcher`（此前为 `UnconfiguredUrlFetcher` 占位）；`test_seams.py` 的期望同步更新。

**正文提取（`backend/app/analysis/web.py`）**

- trafilatura `output_format="markdown", favor_precision=True, include_comments=False` → 导航 / 广告 / 页脚不进正文；再复用 `parsing.parse_markdown_blocks`（token 流）建块，**每个块的 locator 带最终 URL**。
- `decode_html`：按 content-type 的 charset 解码，缺省回退 UTF-8（坏字节替换，不因编码丢整页）。
- 无正文 → `unrecognized`：`empty_page`（响应体为空）/ `no_main_text`（脚本壳 / 抽不出正文），`needs_ocr=false`，message 可读；**绝不空内容冒充成功**。

**API（`backend/app/api/routes/analysis.py`）**

- `POST /api/analysis/sources/url`，body `{"url": string}` → 返回与上传一致的 `AnalysisSourceResponse`（201）；随后复用既有 `analyze` / `summary` / `send-to-creation`，无需新端点。
- 安全拒绝 → 400 + 可读原因（如「拒绝访问云元数据地址：http://169.254.169.254/…」），**不建任务、不落来源、不抓取**。
- 抓取失败 / 需登录 / 超时 / 超限 / 重定向到私网 → 201 + `document.parse_status="failed"` + 可读 `message`（与上传失败口径一致：来源 / 文档落库、可重试、不丢数据）；此时 analyze 返回 409。
- 来源 `ref` = 原始地址（按 `database.py` 既有约定）；`meta` 记 `url / final_url / original_name(页面标题) / fetched_at / status / content_type / size / redirects`；文档 `path` = 最终地址。

**依赖**：根 `pyproject.toml` 登记 `trafilatura>=2.0`（唯一新增运行时依赖，已装 2.3.1）。

**测试（全程不联网）**

- `backend/tests/test_url_guard.py`（64 项）：非法协议 / 内嵌凭据 / 14 类字面量禁止地址 / 域名解析到私网 / 多地址任一命中 / DNS 失败 / 公网放行 / 前置模式不发起 DNS。
- `backend/tests/test_url_fetcher.py`（17 项）：MockTransport 下重定向到私网被逐跳拦下（且未发出第二次请求）、重定向超限、需登录 / 权限、超时、超限、网络异常、元数据记录、协议一致性。
- `backend/tests/test_web_extraction.py`（7 项）：正文提取丢弃导航 / 广告、URL 级 locator 与标题、脚本壳页面无块、空页与无正文原因区分、charset 解码、标题读取。
- `backend/tests/test_analysis_url.py`（26 项）：HTTP 边界上落库与元数据、与上传共用同一总结管线（引用 locator 指向 URL）、重定向后 final_url、14 类禁止目标 400 且不落库、5 类抓取失败提示、无正文未识别短路、一键送入创作、空 URL 422。

**验证证据**（在 `.slim/worktrees/tb9-url/backend` 用主 venv 实跑）

- `pytest`：**331 passed**（基线 217，新增 114，只增不减；`test_seams` 1 项按「抓取器已接真实实现」更新期望）。
- `ruff check .`：**All checks passed**。
- 已把 `integration/workbench-v1`（尖端 3184e4e）合并进 `agent/tb9-url`：**Already up to date**（本单即基于该尖端，无冲突）。

**遗留 / 待办**

- **公开网页真机演示**（工单「演示证据」）需要真实联网抓取，本单按要求全程离线验证，故未执行；请编排者 / 用户在验收阶段跑一次真实页面（如公开技术文章）并记录，同时用 `http://127.0.0.1/`、`http://169.254.169.254/…` 演示拒绝。
- **残留 TOCTOU**：校验用的 DNS 结果与 httpx 实际连接时的解析之间存在时间窗（DNS rebinding 的理论残余风险）；已用「逐跳复核 + 解析后复核」把窗口压到最小，彻底消除需按 IP 直连并自设 Host。现行折中记于此，未做 IP 钉连。
- 前端未接（URL 输入与拒绝原因展示属 UI 触点）；README 由编排者统一更新。
