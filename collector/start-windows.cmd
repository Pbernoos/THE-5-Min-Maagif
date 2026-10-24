@echo off
setlocal
cd /d "%~dp0"
echo Read-only BTC collector. Do not start a second collector on the same database.
echo No wallet, orders, model promotion, or data deletion.
if exist ".venv\Scripts\python.exe" goto run
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if not errorlevel 1 (
  python -m venv .venv
  goto install
)
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
  goto install
)
echo Python 3.11 or newer is required. Install from python.org, reopen this window, retry.
pause
exit /b 1
:install
if not exist ".venv\Scripts\python.exe" goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:run
".venv\Scripts\python.exe" -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
  echo Missing dependencies. Run: .venv\Scripts\python.exe -m pip install -r requirements.txt
  goto failed
)
".venv\Scripts\python.exe" collector.py collect
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Not started or collection stopped with an error. Preserve data and copy the error for diagnosis.
pause
exit /b 1