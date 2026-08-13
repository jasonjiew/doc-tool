@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

where python >nul 2>&1
if errorlevel 1 goto python_not_found

rem If PySide6 is vendored under .vendor\site-packages (some PCs' DLP
rem blocks "pip install" atomic renames; use scripts\setup_pyside6.py instead),
rem prepend it to PYTHONPATH so the app can find PySide6.
rem When PySide6 is pip-installed normally, this branch is skipped.
rem NOTE: keep this file ASCII-only - cmd.exe parses batch files with the
rem system ANSI codepage, so non-ASCII bytes can corrupt parsing.
if exist ".vendor\site-packages\PySide6" (
    set "PYTHONPATH=%~dp0.vendor\site-packages;%PYTHONPATH%"
)

rem Probe for the GUI library (QtWidgets). If it is missing (no pip install
rem and no .vendor), offer to download and install it once so a fresh checkout still works.
python -c "from PySide6.QtWidgets import QApplication" >nul 2>&1
if errorlevel 1 goto pyside6_missing

:launch
python -m doc_tool.app
set "APP_EXIT_CODE=%errorlevel%"
if not "%APP_EXIT_CODE%"=="0" goto startup_failed

endlocal
exit /b 0

:pyside6_missing
echo.
echo [ERROR] PySide6 is missing, so the GUI cannot start.
echo        Install it now? One-time download, about 200 MB.
set /p "INSTALL_CONFIRM=Install PySide6 now? [Y/N]: "
if /I not "%INSTALL_CONFIRM%"=="Y" goto install_declined

echo.
echo Installing PySide6 into .vendor\site-packages. Please wait...
python scripts\setup_pyside6.py
if errorlevel 1 goto install_failed

rem setup_pyside6.py extracts wheels under .vendor\site-packages;
rem add that to PYTHONPATH before launching the app.
if exist ".vendor\site-packages\PySide6" (
    set "PYTHONPATH=%~dp0.vendor\site-packages;%PYTHONPATH%"
)
goto launch

:install_failed
echo.
echo [ERROR] PySide6 installation failed.
echo        Retry manually with:  python scripts\setup_pyside6.py
echo        It needs network access to download the PySide6 wheels.
pause
endlocal
exit /b 1

:install_declined
echo.
echo PySide6 was not installed. When you are ready, run:
echo   python scripts\setup_pyside6.py
echo then start this launcher again.
pause
endlocal
exit /b 1

:python_not_found
echo [ERROR] Python was not found. Install Python 3.13 and add it to PATH.
pause
endlocal
exit /b 1

:startup_failed
echo.
echo [ERROR] Doc Tool failed to start. Exit code: %APP_EXIT_CODE%
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
