@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PAUSE_AT_END=1"
set "PIPELINE_ARGS=%*"
if /i "%~1"=="--no-pause" (
  set "PAUSE_AT_END=0"
  set "PIPELINE_ARGS=%~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9"
)
where python >nul 2>nul || goto :python_error
python -c "import yaml,lxml,PIL,win32com.client" >nul 2>nul || goto :dependency_error
python scripts\run_pipeline.py all %PIPELINE_ARGS%
set "RESULT=%ERRORLEVEL%"
goto :finish
:python_error
echo [FAIL] Python 3 was not found on PATH.
set "RESULT=1"
goto :finish
:dependency_error
echo [FAIL] Missing dependency. Run: python -m pip install pyyaml lxml pillow pywin32
set "RESULT=1"
:finish
if "%RESULT%"=="0" (echo [SUCCESS] All document pipelines completed.) else (echo [FAIL] Document pipeline failed.)
if "%PAUSE_AT_END%"=="1" pause
exit /b %RESULT%
