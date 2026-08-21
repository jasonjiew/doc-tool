@echo off
setlocal enableextensions
rem Doc Tool portable diagnostic. Put this file in the folder that contains
rem the 'DocTool' subfolder (the same folder as the launcher .cmd), run it,
rem then send back the generated DocTool-diagnose.txt.
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.

set "HERE=%~dp0"
set "APP=%HERE%DocTool"
set "LOG=%HERE%DocTool-diagnose.txt"
set "TMPH=%TEMP%\dt_diag_hash.txt"

rem --- expected baselines for DocTool 1.4.1 portable ---
set "EXP_BL_SIZE=1402481"
set "EXP_BL_HASH=6e71e842c225ef92fb0ae201f5a8f3962d2f0d1291841db14339335d6cf766f8"
set "EXP_PY_SIZE=6129496"
set "EXP_PY_HASH=6964e590037c41d631fd1215f05af154f7fa68105993c6f573a20689b473f1ac"
set "EXP_GUI_SIZE=6629775"
set "EXP_CLI_SIZE=6250554"
set "EXP_APP_FILES=394"
set "EXP_INT_FILES=392"

echo Collecting diagnostics, this takes about 30 seconds...
echo.

> "%LOG%" echo ================ Doc Tool portable diagnostic ================
>>"%LOG%" echo when       : %DATE% %TIME%
>>"%LOG%" echo this file  : %HERE%
>>"%LOG%" echo app folder : %APP%
>>"%LOG%" echo.

>>"%LOG%" echo --- 1. environment ---
>>"%LOG%" ver
>>"%LOG%" echo arch       : %PROCESSOR_ARCHITECTURE%
>>"%LOG%" echo user       : %USERNAME%
>>"%LOG%" echo TEMP       : %TEMP%
>>"%LOG%" echo cwd drive  : %~d0
>>"%LOG%" echo.

if not exist "%APP%\DocTool.exe" (
    >>"%LOG%" echo FATAL: '%APP%\DocTool.exe' not found.
    >>"%LOG%" echo Keep the 'DocTool' folder next to this script.
    goto :show
)

>>"%LOG%" echo --- 2. file counts ---
call :count "%APP%" %EXP_APP_FILES% "DocTool"
call :count "%APP%\_internal" %EXP_INT_FILES% "_internal"
>>"%LOG%" echo.

>>"%LOG%" echo --- 3. key file integrity ---
call :chk "%APP%\_internal\base_library.zip" %EXP_BL_SIZE% %EXP_BL_HASH%
call :chk "%APP%\_internal\python313.dll" %EXP_PY_SIZE% %EXP_PY_HASH%
call :chk "%APP%\DocTool.exe" %EXP_GUI_SIZE% -
call :chk "%APP%\doc-tool-cli.exe" %EXP_CLI_SIZE% -
>>"%LOG%" echo.

:stage4
>>"%LOG%" echo --- 4. run the console build IN PLACE (real python error, if any) ---
>>"%LOG%" echo command: "%APP%\doc-tool-cli.exe" --version
pushd "%APP%"
>>"%LOG%" 2>&1 "%APP%\doc-tool-cli.exe" --version
set "RC=%ERRORLEVEL%"
popd
>>"%LOG%" echo exit code: %RC%
>>"%LOG%" echo.

>>"%LOG%" echo --- 5. same thing from a fresh %%TEMP%% copy (what the launcher does) ---
set "TGT=%TEMP%\dt_diag_%RANDOM%_%RANDOM%"
>>"%LOG%" echo target: %TGT%
robocopy "%APP%" "%TGT%" /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NP >nul 2>&1
>>"%LOG%" echo robocopy exit: %ERRORLEVEL%   (0-7 = ok, 8+ = copy failed)
if not exist "%TGT%\doc-tool-cli.exe" (
    >>"%LOG%" echo copy FAILED - doc-tool-cli.exe did not arrive in TEMP
    goto :cleanup5
)
call :count "%TGT%" %EXP_APP_FILES% "TEMP copy"
call :chk "%TGT%\_internal\base_library.zip" %EXP_BL_SIZE% %EXP_BL_HASH%
>>"%LOG%" echo waiting 8s so real-time scanning can settle...
ping 127.0.0.1 -n 9 >nul 2>&1
pushd "%TGT%"
>>"%LOG%" 2>&1 "%TGT%\doc-tool-cli.exe" --version
set "RC=%ERRORLEVEL%"
popd
>>"%LOG%" echo exit code: %RC%

:cleanup5
rd /s /q "%TGT%" 2>nul
>>"%LOG%" echo.

>>"%LOG%" echo --- 6. security software processes ---
tasklist /fo table 2>&1 | findstr /i /c:"esafe" /c:"safenet" /c:"360" /c:"symantec" /c:"mcafee" /c:"kaspersky" /c:"trend" /c:"sophos" /c:"eset" /c:"huorong" /c:"qianxin" /c:"deep" /c:"edr" /c:"dlp" /c:"MsMpEng" >>"%LOG%" 2>&1
>>"%LOG%" echo (empty means none of the known names matched - not proof of absence)
>>"%LOG%" echo.
>>"%LOG%" echo ================ end of report ================

:show
del "%TMPH%" 2>nul
type "%LOG%"
echo.
echo ------------------------------------------------------------
echo Report saved to:
echo   %LOG%
echo Please send that file back.
echo ------------------------------------------------------------
pause
exit /b 0

rem ==================== subroutines ====================

:count
rem %1 = folder, %2 = expected count, %3 = label
set "N=0"
for /f %%N in ('dir /s /b /a-d "%~1" 2^>nul ^| find /c /v ""') do set "N=%%N"
>>"%LOG%" echo   %~3 : %N% files   expected: %~2
if not "%N%"=="%~2" >>"%LOG%" echo     ^<== COUNT MISMATCH: extraction incomplete or files removed
goto :eof

:chk
rem %1 = file, %2 = expected size, %3 = expected sha256 or '-'
>>"%LOG%" echo   %~nx1
if not exist "%~1" (
    >>"%LOG%" echo     MISSING ^<== this file is gone
    goto :eof
)
for %%A in ("%~1") do set "SZ=%%~zA"
>>"%LOG%" echo     size: %SZ%   expected: %~2
if not "%SZ%"=="%~2" >>"%LOG%" echo     ^<== SIZE MISMATCH: truncated, replaced or encrypted
type "%~1" >nul 2>&1
if errorlevel 1 (
    >>"%LOG%" echo     ^<== CANNOT READ: locked or access denied by security software
    goto :eof
)
if "%~3"=="-" goto :eof
certutil -hashfile "%~1" SHA256 > "%TMPH%" 2>&1
if errorlevel 1 (
    >>"%LOG%" echo     hash: certutil unavailable or blocked, not checked
    goto :eof
)
findstr /i /c:"%~3" "%TMPH%" >nul 2>&1
if errorlevel 1 (
    >>"%LOG%" echo     ^<== HASH MISMATCH: content differs from the official build
    >>"%LOG%" find /v "CertUtil" "%TMPH%"
) else (
    >>"%LOG%" echo     hash: MATCH
)
goto :eof
