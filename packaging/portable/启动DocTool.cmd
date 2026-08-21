@echo off
setlocal enableextensions
rem Doc Tool team-distribution launcher.
rem Since 1.4.4 the build is code-signed, so the app starts IN PLACE and is no
rem longer copied to a fresh %TEMP% folder first. Reason: on machines with a
rem transparent-encryption client (e.g. EsafeNet DocGuard / IP-guard) the .pyd
rem or .zip files written by download/extract can get encrypted by the filter
rem driver (files grow by 4 KB and lose their headers), which makes the app
rem fail with 'Failed to start embedded python interpreter!' - worse than the
rem AV block the copy used to dodge.
rem preflight.ps1 (next to this launcher) verifies the headers of the critical
rem files, auto-repairs base_library.zip from its bundled .bak, then (1.4.5)
rem LAUNCHES the app itself and watches the first 8 seconds: a fast nonzero
rem exit is reported here (reason taken from DocTool-startup.log) instead of
rem a silent black-window flash. Results go to %TEMP%\dt_preflight_result.txt
rem and %TEMP%\dt_startfail_reason.txt.
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

rem --- pre-flight integrity check + base_library.zip self-repair + launch ---
set "DT_SRC=%SRC%"
set "PF_RESULT=%TEMP%\dt_preflight_result.txt"
del "%PF_RESULT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight.ps1"
set "PF_ERR="
set "PF_RAN="
if exist "%PF_RESULT%" (
    set /p "PF_ERR="<"%PF_RESULT%"
    set "PF_RAN=1"
)
del "%PF_RESULT%" >nul 2>&1

if defined PF_ERR (
    if "%PF_ERR:~0,7%"=="BROKEN" goto :broken
    if "%PF_ERR:~0,9%"=="STARTFAIL" goto :startfail
    if "%PF_ERR:~0,9%"=="NOTSTARTED" goto :fallback
    echo.
    echo [NOTE] base_library.zip was corrupted and has been auto-repaired
    echo        from the bundled backup. Doc Tool is starting...
    goto :done
)
if not defined PF_RAN goto :fallback
goto :done

:broken
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
exit /b 1

:startfail
echo.
echo [ERROR] Doc Tool started but failed within a few seconds.
echo         Usually the endpoint security software blocked loading of
echo         program components, or files were corrupted after extraction.
echo.
echo         Details from DocTool-startup.log:
if exist "%TEMP%\dt_startfail_reason.txt" type "%TEMP%\dt_startfail_reason.txt"
echo.
echo.
echo         Next steps:
echo          1. Ask IT to whitelist DocTool.exe (and this folder) in the
echo             endpoint security/encryption software, or
echo          2. Run diagnose.cmd next to this file and send back the
echo             generated DocTool-diagnose.txt plus DocTool-startup.log.
echo.
pause
exit /b 1

:fallback
rem preflight did not run or could not launch - start directly, unmonitored.
start "" "%SRC%\DocTool.exe"
goto :done

:done
endlocal
exit /b 0
