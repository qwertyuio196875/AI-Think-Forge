# 03 - 模型配置、连接测试与凭据存储

Status: ready-for-agent

## 目标

OpenAI 兼容统一客户端（base_url/key/model 三元组）；providers 表 CRUD + 默认设置；连接测试接口（清晰错误分类：网络/鉴权/模型名）；API Key 存 Windows 凭据管理器，SQLite 只存非敏感字段；日志脱敏。默认服务商阿里云百炼（端点/模型 ID 以 @librarian 核实为准；档位默认 qwen-plus，总结默认 turbo，任务级可切 max）。

## 验收

- 对百炼真实连接测试通过；`grep` 全库无明文 Key；pytest 覆盖错误分类。

## Comments

- （待补）
