@echo off
echo ========================================
echo Shared Equipment Rescue - Quick Start
echo ========================================
echo.

echo [1] Starting MCP API Server...
start "" cmd /k "cd /d %~dp0 && python simple_test_server.py"

timeout /t 3 /nobreak >nul

echo.
echo [2] Opening Demo Page...
start DEMO.html

echo.
echo ========================================
echo ✓ DONE! Demo page should be open now
echo ========================================
echo.
echo Your server is running at: http://localhost:8000
echo Open the demo page in your browser to see it in action!
echo.
pause
