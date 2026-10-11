@echo off
setlocal
cd /d "%~dp0"
title AI Escape Room Solver

rem Pick the Python to use: the project's virtual environment if it exists.
set "PY="
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not defined PY (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python 3 was not found. Install Python 3.9 or newer from https://www.python.org/downloads/
        echo         and tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
    echo [NOTE] No virtual environment found - using the Python on your PATH.
    echo        Recommended one-time setup:
    echo            python -m venv venv
    echo            venv\Scripts\python -m pip install -r requirements.txt
    set "PY=python"
)

"%PY%" -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Flask is not installed for this Python.
    echo         Run:  "%PY%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting AI Escape Room Solver at http://127.0.0.1:5000
echo Press Ctrl+C in this window to stop the server.
start "" "http://127.0.0.1:5000"
"%PY%" -m backend.app
if errorlevel 1 (
    echo.
    echo [ERROR] The server stopped with an error. If the message above mentions port 5000 being in use,
    echo         close the other program or run:  set PORT=5001 ^&^& run.bat
    pause
)
endlocal
