@echo off
:: Change to the folder where this .bat file lives (the project folder)
cd /d "%~dp0"

echo.
echo ============================================
echo   Weather AI Trading Agent - Starting Everything
echo ============================================
echo   Project folder: %~dp0
echo.

:: Step 1:: Start the FastAPI dashboard in the background silently
echo Starting Dashboard Server...
start /B py web\dashboard.py >nul 2>&1

:: Step 2: Wait for dashboard to boot
echo [2/3] Waiting 3 seconds for dashboard to boot...
timeout /t 3 /nobreak > nul

:: Step 3: Open browser automatically
echo [3/3] Opening browser...
start "" "http://localhost:8000"

:: Step 4: Start agent loop in THIS window
echo.
echo ============================================
echo   Agent is now running every 60 minutes!
echo   Press Ctrl+C to stop.
echo ============================================
echo.

py -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); exec(open('main.py', encoding='utf-8').read())" --loop --hermes-run

pause
