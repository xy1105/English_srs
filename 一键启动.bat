@echo off
setlocal

REM 设置项目路径
cd /d %~dp0

echo.
echo 🔍 正在检测虚拟环境...

REM 检查 venv 是否存在
IF NOT EXIST "venv\" (
    echo ⚠️ 未找到虚拟环境，正在创建中...
    python -m venv venv
) ELSE (
    echo ✅ 虚拟环境已存在
)

REM 激活虚拟环境
echo.
echo 🔧 正在激活虚拟环境...
call venv\Scripts\activate.bat

REM 检查是否安装了 Flask（用 flask --version 判断）
flask --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ⚠️ 检测到未安装依赖，正在安装 requirements.txt...
    pip install -r requirements.txt
) ELSE (
    echo ✅ 依赖已安装
)

REM 自动打开浏览器
start http://127.0.0.1:5000

REM 启动 Flask 应用
echo.
echo 🚀 正在启动 Flask 应用...
python run.py

REM 停留控制台窗口
pause
endlocal
