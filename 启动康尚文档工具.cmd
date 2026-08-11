@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

where python >nul 2>&1
if errorlevel 1 goto python_not_found

python -m doc_tool.app
set "APP_EXIT_CODE=%errorlevel%"
if not "%APP_EXIT_CODE%"=="0" goto startup_failed

endlocal
exit /b 0

:python_not_found
echo [ERROR] Python was not found. Install Python 3.13 and add it to PATH.
pause
endlocal
exit /b 1

:startup_failed
echo.
echo [ERROR] Konsung Doc Tool failed to start. Exit code: %APP_EXIT_CODE%
pause
endlocal
exit /b %APP_EXIT_CODE%
