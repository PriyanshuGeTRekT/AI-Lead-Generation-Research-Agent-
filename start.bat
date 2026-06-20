@echo off
REM ── RazorInfotech HRMS Leads AI — one-click launcher ───────────────────────
REM Starts the backend (FastAPI :8000) and the frontend (Vite :5173) together,
REM each in its own window, then opens the app in your browser.

cd /d "%~dp0"

echo ============================================================
echo   RazorInfotech HRMS Leads AI - starting...
echo ============================================================

REM 1) Backend API (port 8000)
start "HRMS Leads - Backend (8000)" cmd /k python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

REM 2) Frontend (port 5173)
start "HRMS Leads - Frontend (5173)" cmd /k "cd frontend && npm run dev"

REM 3) Give them a few seconds, then open the browser
echo Waiting for servers to come up...
timeout /t 6 /nobreak >nul
start "" http://localhost:5173

echo.
echo App opening at http://localhost:5173
echo (Two server windows opened. Close them to stop the app.)
