"""集中配置：路径与监听参数。

路径以本文件位置反推仓库根，避免依赖启动时的当前工作目录。
运行时可经环境变量 `THINKFORGE_DB_PATH` 覆盖 SQLite 库位置（测试即用临时库）。
"""

from __future__ import annotations

from pathlib import Path

# config.py 位于 backend/app/，向上三级即仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"
# 模板目录（用户模板 + 内置默认模板）；文件访问白名单之一，见「安全边界」。
TEMPLATES_DIR = REPO_ROOT / "templates"
# 成品产物目录（Word / 单文件 HTML）；文件访问白名单之一。
DELIVERABLES_SUBDIR = "deliverables"

DEFAULT_DB_PATH = DATA_DIR / "thinkforge.db"
DB_PATH_ENV_VAR = "THINKFORGE_DB_PATH"

API_PREFIX = "/api"

# 安全边界（规格 08）：仅监听本机回环
HOST = "127.0.0.1"
PORT = 8720

# 开发期 CORS：前端 Vite 开发服务器不做代理、浏览器跨源直连后端，
# 因此只放行本机开发源。生产为同源托管 dist，此中间件对同源请求无影响，
# 且来源白名单固定、**绝不使用通配来源**。
DEV_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEV_CORS_METHODS = ("GET", "POST", "PUT", "DELETE")
DEV_CORS_HEADERS = ("Content-Type",)

APP_NAME = "ThinkForge 工作台"
APP_VERSION = "0.1.0"
