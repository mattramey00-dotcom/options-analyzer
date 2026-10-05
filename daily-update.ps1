# daily-update.ps1
# Unattended daily refresh for the Earnings Play Analyzer.
# Mirrors UPDATE_AND_LAUNCH.bat's data steps (scan -> refetch -> push to
# GitHub Pages) but drops the interactive parts (pause, local server,
# browser launch) since this is meant to run with nobody at the keyboard.
#
# Edit the settings below the same way you'd edit UPDATE_AND_LAUNCH.bat.

$ErrorActionPreference = "Continue"

# ============================================================
#  YOUR WATCHLIST — leave blank to auto-scan instead (see below)
# ============================================================
$Watchlist = ""   # e.g. "SOFI F HIMS NIO PLTR HOOD LC AMD"

# ============================================================
#  AUTO-SCAN SETTINGS (used when $Watchlist is blank)
# ============================================================
$ScanEnabled  = $true
$ScanDays     = 60
$ScanPriceMin = 8
$ScanPriceMax = 30
$ScanMaxPE    = 50

# ============================================================
#  DON'T EDIT BELOW THIS LINE (unless you know what you're doing)
# ============================================================

$projectDir = $PSScriptRoot
Set-Location $projectDir

$logDir = Join-Path $projectDir "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir "daily-update.log"

function Log($msg) {
    "$(Get-Date -Format o)  $msg" | Out-File -FilePath $log -Append
}

Log "=== Daily update starting ==="

# Clear old data so only fresh results appear (matches UPDATE_AND_LAUNCH.bat)
if (Test-Path "stock_data.json") {
    Remove-Item "stock_data.json" -Force
    Log "Cleared old stock_data.json"
}

if ($Watchlist -eq "") {
    if ($ScanEnabled) {
        Log "Scanning next $ScanDays days, price \$$ScanPriceMin-\$$ScanPriceMax, max P/E $ScanMaxPE ..."
        python scan_earnings.py --days $ScanDays --price-min $ScanPriceMin --price-max $ScanPriceMax --max-pe $ScanMaxPE *>> $log
        Log "Scan complete."
    } else {
        Log "Scan disabled and no watchlist set — nothing to fetch. Exiting."
        exit 0
    }
    Log "Re-fetching scan results with full catalyst data..."
    python refetch_full.py *>> $log
} else {
    Log "Fetching watchlist: $Watchlist"
    python fetch_stock.py $Watchlist.Split(" ") *>> $log
}

Log "Pushing data to GitHub Pages..."
git add index.html stock_data.json dashboard.html *>> $log
git commit -m "Daily update $(Get-Date -Format 'yyyy-MM-dd HH:mm')" *>> $log
git push *>> $log

if ($LASTEXITCODE -eq 0) {
    Log "Pushed to GitHub. Site will update in ~1 minute: https://mattramey00-dotcom.github.io/options-analyzer"
} else {
    Log "GitHub push failed (exit code $LASTEXITCODE) — check network/auth and $log for details."
}

Log "=== Daily update finished ==="
