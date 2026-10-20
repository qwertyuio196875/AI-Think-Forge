@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   ThinkForge 工作台  http://127.0.0.1:8720
echo   关闭本窗口或按 Ctrl+C 即停止服务
echo ============================================
echo.

if not exist "backend\.venv\Scripts\python.exe" (
    echo [错误] 未找到后端虚拟环境 backend\.venv
    echo 请先在仓库根执行：
    echo   python -m venv backend\.venv
    echo   backend\.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" pydantic httpx pytest ruff
    pause
    exit /b 1
)

REM 前端构建产物：缺失则先构建（首次运行）。构建失败不阻断后端启动，只给出可读警告。
if not exist "frontend\dist\index.html" (
    echo [信息] 未找到前端构建产物 frontend\dist，正在构建...
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [警告] 未找到 npm（Node.js）。后端仍会启动，但 http://127.0.0.1:8720 只提供 /api，工作台界面不可用。
        echo        请安装 Node.js 后在 frontend 目录执行：npm install ^&^& npm run build
    ) else (
        pushd "%~dp0frontend"
        if not exist "node_modules" (
            echo [信息] 安装前端依赖（首次较慢）...
            call npm install
        )
        call npm run build
        popd
        if not exist "frontend\dist\index.html" (
            echo [警告] 前端构建未产出 frontend\dist\index.html。后端仍会启动，但工作台界面不可用。
        )
    )
)

REM 延迟 3 秒再打开浏览器，给后端启动留出时间；后端在前台运行，Ctrl+C 可停止。
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8720'"

pushd "%~dp0backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8720
popd

endlocal