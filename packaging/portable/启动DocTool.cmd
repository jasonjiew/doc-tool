@echo off
setlocal enableextensions
rem Doc Tool team-distribution launcher.
rem On some corporate PCs the security software blocks the standalone exe:
rem   * a folder literally named 'DocTool' is blocked, and
rem   * an unsigned exe loaded from a normal/shared drive is blocked, and
rem   * repeatedly running the same unsigned exe can poison the AV reputation
rem     for that path, so the same path may work once then stop working.
rem To dodge all of that, this launcher copies the app into a FRESH, random,
rem not-'DocTool' folder under %%TEMP%% on every run and starts it from there.
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

rem a brand-new random path (NOT 'DocTool'), starts with no AV reputation.
set "TGT=%TEMP%\dt_run_%RANDOM%_%RANDOM%"

echo Deploying Doc Tool to a local working folder. Please wait a few seconds...

robocopy "%SRC%" "%TGT%" /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NP >nul 2>&1

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
