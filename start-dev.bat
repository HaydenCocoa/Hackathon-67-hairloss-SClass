@echo off
title SClass launcher
rem Double-click to start the SClass backend (FastAPI) and frontend (Vue).
rem First run also installs everything it needs.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Setup] Creating the Python environment - first run only...
  py -3 -m venv .venv
  if errorlevel 1 goto :nopython
  ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
  if errorlevel 1 goto :failed
)

if not exist "frontend\node_modules" (
  echo [Setup] Installing frontend packages - first run only...
  pushd frontend
  call npm ci
  if errorlevel 1 (
    popd
    goto :failed
  )
  popd
)

echo Starting backend on http://127.0.0.1:8000 ...
start "SClass Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000"

echo Starting frontend on http://127.0.0.1:5173 ...
start "SClass Frontend" cmd /k "cd frontend && npm run dev"

echo Opening the Student Page in your browser...
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:5173/#/student"
echo.
echo Done. Close the "SClass Backend" and "SClass Frontend" windows to stop.
timeout /t 5 >nul
exit /b 0

:nopython
echo.
echo Python was not found. Install Python 3.10 or newer from python.org
echo and tick "Add python.exe to PATH" during installation.
pause
exit /b 1

:failed
echo.
echo Setup failed. Check the error above, or send a screenshot.
pause
exit /b 1
