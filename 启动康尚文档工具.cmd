@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

where python >nul 2>&1
if errorlevel 1 goto python_not_found

rem If PySide6 is vendored under .vendor\site-packages (some company PCs' DLP
rem blocks "pip install" atomic renames; use scripts\setup_pyside6.py instead),
rem prepend it to PYTHONPATH so the app can find PySide6.
rem When PySide6 is pip-installed normally, this branch is skipped.
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.
if exist ".vendor\site-packages\PySide6" (
    set "PYTHONPATH=%~dp0.vendor\site-packages;%PYTHONPATH%"
)

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
echo.
echo Common fixes:
echo   1. Missing PySide6: run   python -m pip install -r requirements.txt
echo      If pip fails with WinError 17 (DLP blocks install), run:
echo        python scripts\setup_pyside6.py
echo   2. Other missing deps: run   python -m pip install -r requirements.txt
echo   3. Read the Python error output above for the exact cause.
pause
endlocal
exit /b %APP_EXIT_CODE%
