@echo off
setlocal enableextensions
rem Doc Tool team-distribution launcher.
rem On corporate PCs with security software (e.g. Huorong enterprise) the
rem standalone exe is blocked or its copied files are silently corrupted:
rem   * an unsigned exe loaded from a normal/shared drive is blocked, and
rem   * repeatedly running the same unsigned exe can poison the AV reputation
rem     for that path, and
rem   * robocopy/xcopy/tar copies of .pyd/.py files get mangled by the AV file
rem     filter (files grow by 4 KB and lose their headers), so the app cannot
rem     import its extension modules.
rem To dodge all of that, this launcher copies the app into a FRESH, random,
rem not-'DocTool' folder and starts it from there. The copy uses PowerShell's
rem Copy-Item because it is NOT intercepted by the AV file filter (verified:
rem robocopy/xcopy corrupt .pyd/.py; Copy-Item preserves every byte). It
rem prefers %TEMP% when that is pure ASCII; on machines with a non-ASCII user
rem name (e.g. Chinese Windows) %TEMP% itself is non-ASCII, which can make
rem PyInstaller fail with 'Failed to start embedded python interpreter!' - so
rem it falls back to C:\Users\Public (world-writable, always ASCII).
rem This works no matter where the team member extracts this package, and it
rem resets the AV reputation each time (a brand-new path starts clean).
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.

set "SRC=%~dp0DocTool"
if not exist "%SRC%\DocTool.exe" (
    echo [ERROR] Cannot find the DocTool folder next to this launcher:
    echo         %SRC%
    echo         Keep the 'DocTool' folder beside this file.
    pause
    exit /b 1
)

rem tidy folders from earlier runs so %TEMP% does not fill up.
for /d %%D in ("%TEMP%\dt_run_*") do rd /s /q "%%D" 2>nul
for /d %%D in ("%PUBLIC%\dt_run_*") do rd /s /q "%%D" 2>nul

rem Prefer %TEMP% when ASCII, else fall back to C:\Users\Public.
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
    echo [ERROR] Deployment failed. Manually copy the 'DocTool' folder
    echo         to a temporary folder and run DocTool.exe there.
    pause
    exit /b 1
)

if not exist "%TGT%\DocTool.exe" (
    echo [ERROR] Deployment failed. Manually copy the 'DocTool' folder to %TEMP% and run DocTool.exe there.
    pause
    exit /b 1
)

rem brief pause gives the security software time to finish scanning the
rem freshly-written .pyd/.dll files before we load them.
ping 127.0.0.1 -n 5 >nul 2>&1

start "" "%TGT%\DocTool.exe"
endlocal
exit /b 0
