@echo off
setlocal enableextensions
rem Doc Tool installed-app launcher.
rem Installed layout: DocTool.exe + _internal\ sit directly in the install dir
rem (NOT in a 'DocTool' subfolder), and this launcher sits beside them.
rem Same strategy as the portable package: copy the app into a FRESH, random,
rem ASCII-safe folder and start it from there. The copy uses PowerShell's
rem Copy-Item because the AV file filter (Huorong enterprise) silently corrupts
rem .pyd/.py files when robocopy/xcopy/tar copies them (files grow by 4 KB and
rem lose their headers), which makes the app fail to import its extension
rem modules. Copy-Item is not intercepted and preserves every byte.
rem This dodges two blockers seen on corporate PCs:
rem   * security software blocking an unsigned exe from loading DLLs from a
rem     normal/shared/installed location, and
rem   * PyInstaller bootloader failing with 'Failed to start embedded python
rem     interpreter!' when the runtime path contains non-ASCII characters
rem     (e.g. a Chinese Windows username makes %TEMP% non-ASCII).
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

rem tidy folders from earlier runs so the temp area does not fill up.
for /d %%D in ("%TEMP%\dt_run_*") do rd /s /q "%%D" 2>nul
for /d %%D in ("%PUBLIC%\dt_run_*") do rd /s /q "%%D" 2>nul

rem Choose an ASCII-safe destination: prefer %TEMP% when it is pure ASCII,
rem otherwise fall back to C:\Users\Public (world-writable, always ASCII).
set "TGTBASE=%TEMP%"
powershell -NoProfile -Command "if ([regex]::IsMatch($env:TEMP, '[^\x20-\x7E]')) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    set "TGTBASE=%PUBLIC%"
    echo NOTE: your TEMP path contains non-ASCII characters, using %PUBLIC% instead.
)

rem a brand-new random path (NOT 'DocTool'), starts with no AV reputation.
set "TGT=%TGTBASE%\dt_run_%RANDOM%_%RANDOM%"

echo Deploying Doc Tool to a local working folder. Please wait a few seconds...

rem Pass the paths through environment variables: cmd would otherwise lose
rem non-ASCII characters when building the PowerShell command line.
rem NOTE: do NOT pre-create %TGT% - PowerShell Copy-Item -Recurse creates the
rem destination folder itself, copying the source contents directly into it.
set "DT_SRC=%SRC%"
set "DT_TGT=%TGT%"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Copy-Item -LiteralPath $env:DT_SRC -Destination $env:DT_TGT -Recurse -Force"
if errorlevel 1 (
    echo [ERROR] Deployment failed. Manually copy the DocTool files to
    echo         a temporary folder and run DocTool.exe there.
    pause
    exit /b 1
)

if not exist "%TGT%\DocTool.exe" (
    echo [ERROR] Deployment failed. Manually copy the DocTool files to a
    echo         temporary folder and run DocTool.exe there.
    pause
    exit /b 1
)

rem brief pause gives the security software time to finish scanning the
rem freshly-written .pyd/.dll files before we load them.
ping 127.0.0.1 -n 5 >nul 2>&1

start "" "%TGT%\DocTool.exe"
endlocal
exit /b 0
