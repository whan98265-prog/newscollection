@echo off
rem One-click run on Windows: collect -> translate -> save -> push (if configured)
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% finnews.py %*
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" echo [FAILED] exit code %CODE%
pause
exit /b %CODE%
