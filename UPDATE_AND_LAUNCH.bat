@echo off
title Earnings Play Analyzer - Daily Update
color 0A

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║     EARNINGS PLAY ANALYZER — Daily Updater       ║
echo  ║     Edit your watchlist below, then double-click  ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ============================================================
::  YOUR WATCHLIST — Edit these tickers to whatever you want!
::  Just separate them with spaces. Add or remove as needed.
:: ============================================================

set WATCHLIST=

:: ============================================================
::  AUTO-SCAN SETTINGS
::  Set SCAN_ENABLED=1 to auto-find earnings plays for you
::  Set SCAN_ENABLED=0 to just fetch your watchlist above
:: ============================================================

set SCAN_ENABLED=1
set SCAN_DAYS=60
set SCAN_PRICE_MIN=8
set SCAN_PRICE_MAX=30
set SCAN_MAX_PE=50

:: ============================================================
::  DON'T EDIT BELOW THIS LINE (unless you know what you're doing)
:: ============================================================

:: Navigate to the folder this script lives in
cd /d "%~dp0"

:: Clear old data so only fresh scan results appear
if exist stock_data.json del stock_data.json

echo  [1/5] Auto-scanning for earnings plays...
echo  ─────────────────────────────────────────
echo.

if "%SCAN_ENABLED%"=="1" (
    echo  Scanning next %SCAN_DAYS% days for stocks in $%SCAN_PRICE_MIN%-$%SCAN_PRICE_MAX% range...
    python scan_earnings.py --days %SCAN_DAYS% --price-min %SCAN_PRICE_MIN% --price-max %SCAN_PRICE_MAX% --max-pe %SCAN_MAX_PE%
    echo.
    echo  ✓ Scan complete! Any qualifying plays saved to stock_data.json
    echo.
) else (
    echo  Auto-scan disabled. Set SCAN_ENABLED=1 to enable.
    echo.
)

if "%WATCHLIST%"=="" (
    echo  [2/5] Re-fetching scan results with full catalyst data...
    echo  ─────────────────────────────────────────
    echo.
    python refetch_full.py
    echo.
) else (
    echo  [2/5] Fetching watchlist data: %WATCHLIST%
    echo  ─────────────────────────────────────────
    echo.
    python fetch_stock.py %WATCHLIST%
)

echo  [3/5] Pushing data to GitHub Pages...
echo  ─────────────────────────────────────────
echo.
git add index.html stock_data.json dashboard.html >nul 2>&1
git commit -m "Update data %date% %time:~0,5%" >nul 2>&1
git push >nul 2>&1
if %errorlevel%==0 (
    echo  ✓ Pushed to GitHub! Site will update in ~1 minute.
    echo  ✓ https://mattramey00-dotcom.github.io/options-analyzer
) else (
    echo  ✗ GitHub push failed. Check your internet connection.
    echo    You can still view locally below.
)
echo.

echo.
echo  [4/5] Starting local web server on port 8000...
echo  ─────────────────────────────────────────
echo.

:: Kill any existing server on port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Start the server LOCKED TO LOCALHOST (only your PC can access it)
start /B python -m http.server 8000 --bind 127.0.0.1 >nul 2>&1

:: Give the server a moment to start
timeout /t 2 /nobreak >nul

echo  [5/5] Opening dashboard in your browser...
echo  ─────────────────────────────────────────
echo.

:: Open the dashboard (with cache-bust to force fresh load)
start http://localhost:8000/dashboard.html?v=%random%

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║  ✓ ALL DONE!                                     ║
echo  ║                                                  ║
echo  ║  Dashboard is open at:                           ║
echo  ║  http://localhost:8000/dashboard.html              ║
echo  ║                                                  ║
echo  ║  Mobile/remote access:                           ║
echo  ║  https://mattramey00-dotcom.github.io/options-analyzer  ║
echo  ║                                                  ║
echo  ║  Tickers loaded: %WATCHLIST%
echo  ║                                                  ║
echo  ║  ► Keep this window open while using the dashboard║
echo  ║  ► Close this window to stop the server          ║
echo  ║  ► Edit this .bat file to change your watchlist  ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  Press any key to shut down the server and exit...
pause >nul

:: Kill the server
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo  Server stopped. Goodbye!
timeout /t 2 /nobreak >nul
