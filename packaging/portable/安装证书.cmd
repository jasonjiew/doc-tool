@echo off
setlocal
rem Doc Tool one-click trust installer for the company code-signing cert.
rem Double-click this file, answer Yes on the security prompt that appears.
rem Works for the current user only - no admin rights needed.
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.

set "CER=%~dp0codesign.cer"
if not exist "%CER%" set "CER=%~dp0DocTool\codesign.cer"
if not exist "%CER%" (
    echo [ERROR] Cannot find codesign.cer next to this script.
    pause
    exit /b 1
)

echo Installing the Jiangsu Konsung code-signing certificate for user %USERNAME%.
echo When Windows asks to confirm the certificate, click Yes.
echo.

certutil -user -addstore Root "%CER%"
if errorlevel 1 goto fail
certutil -user -addstore TrustedPublisher "%CER%"
if errorlevel 1 goto fail

echo.
echo OK - the certificate is now trusted on this machine.
echo (If Windows still warns on first run, choose "More info" then "Run anyway".)
pause
exit /b 0

:fail
echo.
echo [ERROR] Import failed. You can also import manually:
echo   double-click codesign.cer -^> Install Certificate -^> Current User -^>
echo   "Place all certificates in the following store" -^> Browse -^>
echo   "Trusted Root Certification Authorities" -^> Finish.
pause
exit /b 1
