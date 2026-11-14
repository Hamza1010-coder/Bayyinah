@echo off
setlocal
cd /d "%~dp0"

rem Prefer the Python launcher: on many Windows machines `python` is the
rem Microsoft Store stub, which opens the Store instead of running anything.
where py >nul 2>nul
if %errorlevel%==0 (set "PYEXE=py") else (set "PYEXE=python")

set PYTHONIOENCODING=utf-8

echo.
echo   Bayyinah - Arabic-first compliance copilot
echo   -------------------------------------------
echo   Open:  http://127.0.0.1:8080
echo.
echo   Keep this window open. Press Ctrl+C to stop.
echo.

rem Open the browser a moment after the server starts listening.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8080'"

%PYEXE% -m bayyinah serve --port 8080
if errorlevel 1 (
  echo.
  echo   The server exited with an error. Common causes:
  echo     - port 8080 already in use  ^(try: start.bat 8090^)
  echo     - Python not installed       ^(install Python 3.10+ from python.org^)
  echo.
)
pause
