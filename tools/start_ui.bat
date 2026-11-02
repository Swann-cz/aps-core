@echo off
rem Double-click: starts backend (8765) and UI (5173), then opens the browser. Close the two windows to stop.
cd /d "%~dp0.."
start "APS server" cmd /k python -m server
start "APS ui" cmd /k npm --prefix ui run dev
timeout /t 5 /nobreak >nul
start "" http://localhost:5173
