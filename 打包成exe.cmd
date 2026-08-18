@echo off
setlocal
cd /d "%~dp0"

rem Doc Tool: one-click build to EXE (wraps build_exe.ps1).
rem Usage:  double-click, or run from cmd:  build_exe.ps1 -OneFile
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.

where python >nul 2>&1
if errorlevel 1 goto python_not_found

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1" %*
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo [ERROR] Build failed with exit code %RC%. See messages above.
    echo         Common fix: python -m pip install -r requirements.txt -r requirements-build.txt
    pause
    endlocal
    exit /b %RC%
)

echo.
echo Done. Output is under dist\DocTool (onedir) or dist\DocTool.exe (-OneFile).
pause
endlocal
exit /b 0

:python_not_found
echo [ERROR] Python was not found. Install Python 3.13 and add it to PATH.
pause
endlocal
exit /b 1
