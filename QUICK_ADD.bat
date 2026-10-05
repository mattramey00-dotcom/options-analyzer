@echo off
title Earnings Play Analyzer - Quick Add Ticker
color 0E

:: Navigate to the folder this script lives in
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║     QUICK ADD — Fetch a single ticker            ║
echo  ╚══════════════════════════════════════════════════╝
echo.

if "%~1"=="" (
    set /p TICKER="  Enter ticker symbol: "
) else (
    set TICKER=%~1
)

echo.
echo  Fetching %TICKER%...
echo.

python fetch_stock.py %TICKER%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ✗ Failed to fetch %TICKER%. Check the symbol and try again.
    pause
    exit /b 1
)

echo.
echo  ✓ Done! Refresh your browser to see %TICKER% in the dashboard.
echo  ✓ Your existing tickers are preserved (data is merged).
echo.
pause
