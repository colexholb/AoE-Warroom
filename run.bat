@echo off
rem Starts AoE Warroom. Usage:
rem   run.bat         - only this PC can open it (http://localhost:8000)
rem   run.bat lan     - friends on your network can open http://<this-PC-IP>:8000
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
)
.venv\Scripts\python -m pip install -q -r requirements.txt || goto :error

set HOST=127.0.0.1
if /i "%1"=="lan" (
  set HOST=0.0.0.0
  echo Friends can open one of these addresses:
  for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=1" %%b in ("%%a") do echo    http://%%b:8000
)
start "" http://localhost:8000
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host %HOST% --port 8000
goto :eof

:error
echo Setup failed.
pause
