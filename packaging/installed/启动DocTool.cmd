@echo off
setlocal enableextensions
rem Doc Tool installed-app launcher.
rem Installed layout: DocTool.exe + _internal\ sit directly in the install dir
rem (NOT in a 'DocTool' subfolder), and this launcher sits beside them.
rem Since 1.4.4 the build is code-signed, so the app starts IN PLACE and is no
rem longer copied to a fresh %TEMP% folder first - see the portable launcher
rem for the reason (transparent-encryption clients can mangle .pyd/.zip files,
rem breaking the app with 'Failed to start embedded python interpreter!').
rem preflight.ps1 (next to this launcher) verifies the headers of the critical
rem files, auto-repairs base_library.zip from its bundled .bak when the
rem security software has mangled it, and writes its result to
rem %TEMP%\dt_preflight_result.txt.
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.

set "SRC=%~dp0"
rem %~dp0 ends with '\'; in cmd a quoted path ending in '\' escapes the closing
rem quote and mangles the argument, so strip the trailing backslash first.
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"
if not exist "%SRC%\DocTool.exe" (
    echo [ERROR] Cannot find DocTool.exe next to this launcher:
    echo         %SRC%
    pause
    exit /b 1
)

rem --- pre-flight integrity check + base_library.zip self-repair ---
set "DT_SRC=%SRC%"
set "PF_RESULT=%TEMP%\dt_preflight_result.txt"
del "%PF_RESULT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight.ps1"
set "PF_ERR="
if exist "%PF_RESULT%" set /p "PF_ERR="<"%PF_RESULT%"
del "%PF_RESULT%" >nul 2>&1
if defined PF_ERR (
    if "%PF_ERR:~0,7%"=="BROKEN" (
        echo.
        echo [ERROR] Program files look encrypted or corrupted by security software:
        echo         %PF_ERR:~8%
        echo         (invalid file header / file grew by 4 KB - typical of a
        echo         transparent-encryption client such as DocGuard or IP-guard^).
        echo.
        echo Please re-extract this package to a fresh folder, then run this
        echo launcher again. If it still fails, ask IT to whitelist DocTool in
        echo the endpoint encryption/security software, or use another download
        echo channel and re-extract.
        echo.
        pause
        endlocal
        exit /b 1
    )
    echo [NOTE] base_library.zip was corrupted and has been auto-repaired from
    echo        the bundled backup. Starting Doc Tool...
)

start "" "%SRC%\DocTool.exe"
endlocal
exit /b 0
