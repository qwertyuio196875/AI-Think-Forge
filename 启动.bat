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

REM 延迟 3 秒再打开浏览器，给后端启动留出时间；后端在前台运行，Ctrl+C 可停止。
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8720'"

pushd "%~dp0backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8720
popd

endlocal