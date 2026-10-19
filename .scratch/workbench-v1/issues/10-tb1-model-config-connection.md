# TB-1 · 模型配置与连接测试

Status: ready-for-agent
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