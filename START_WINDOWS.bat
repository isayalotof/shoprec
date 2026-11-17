@echo off
cd /d "%~dp0"
echo ShopRec local server
echo After startup, open http://127.0.0.1:8787 in your browser.
echo Admin page: http://127.0.0.1:8787/admin
echo On first run, the admin token is saved in data\admin-token.
echo.
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
  py -3 server.py
) else (
  python --version >nul 2>&1
  if errorlevel 1 (
    echo Python 3.10 or newer is required. Install Python or use Docker Compose.
  ) else (
    python server.py
  )
)
pause
