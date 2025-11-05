@echo off
REM Quick start script for Windows

echo ========================================
echo  Superclaims AI Processor - Quick Start
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Please install Python 3.11+ first.
    pause
    exit /b 1
)

echo [OK] Python found
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment exists
)

REM Activate virtual environment
echo [SETUP] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo [SETUP] Installing dependencies...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo [OK] Dependencies installed
echo.

REM Check for .env file
if not exist ".env" (
    echo [SETUP] Creating .env file from template...
    copy .env.example .env
    echo [OK] .env file created
    echo.
    echo [IMPORTANT] Edit .env file and add your API keys:
    echo    - GOOGLE_API_KEY (for Gemini)
    echo    - OR OPENAI_API_KEY (for GPT-4)
    echo.
    pause
) else (
    echo [OK] .env file exists
)

echo.
echo [START] Starting application...
echo    API: http://localhost:8000
echo    Docs: http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop the server
echo.

REM Run the application
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
