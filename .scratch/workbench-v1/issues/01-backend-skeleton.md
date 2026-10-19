# 01 - 后端骨架与数据模型

Status: closed — 已并入 08-v1-unified-spec.md（勿按本单执行；本单为按层切分，已被曳光弹工单取代）

## 目标

按 spec §3/§4 建立 `backend/` FastAPI 应用骨架：包结构、SQLite 建表（含 embeddings 预留）、`/api/health`、根 `.gitignore`（data/、.venv、node_modules、dist）、`启动.bat`（venv + uvicorn 127.0.0.1:8720）。业务路由留桩。

## 验收

- venv 安装依赖成功；`pytest` 建表与 health 测试绿。

## Comments

- （待补）
