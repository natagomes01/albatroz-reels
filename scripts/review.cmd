@echo off
rem Windows twin of review.command. Double-click (or `scripts\review.cmd [job]`): starts the
rem review page and opens it. With no job it takes the most recently changed folder in jobs\.
rem If the page is already running, it only opens the browser.
setlocal
cd /d "%~dp0.." || exit /b 1
set "job=%~1"
if not "%job%"=="" goto have
for /f "delims=" %%d in ('dir /b /ad /o-d jobs ^| findstr /v /b "_"') do (
  set "job=%%d"
  goto have
)
:have
netstat -ano -p tcp | findstr /r /c:"127.0.0.1:8765 .*LISTENING" >nul
if not errorlevel 1 (
  start "" "http://127.0.0.1:8765"
  exit /b 0
)
echo Review page for %job% (close this window or press Ctrl+C to stop it)
where uv >nul 2>nul
if not errorlevel 1 (
  uv run shorts review "%job%" --port 8765
) else (
  ".venv\Scripts\shorts.exe" review "%job%" --port 8765
)
