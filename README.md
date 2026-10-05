# Earnings Play Analyzer — Setup Guide

## What You Get
A complete earnings play screening tool that analyzes any stock against your criteria:
- **$15-$20 price range** sweet spot for 100-lot plays
- **P/E < 50** vs S&P 500 historical average of 16
- **52-week range** position (avoid stocks at highs)
- **Short interest < 10%**
- **Earnings surprise trends** (last 4 quarters)
- **Peer comparison** with sector sentiment
- **90-day risk range** for strike selection
- **Options chain** placeholder + direct Fidelity link for real premiums
- **Risk/reward calculator** for covered calls on 100 shares

---

## Step 1: Install Python (if you don't have it)

**Check if Python is installed:**
Open Terminal (Mac) or Command Prompt (Windows) and type:
```
python3 --version
```
If you see a version number (like `Python 3.11.5`), you're good — skip to Step 2.

**If not installed:**
- **Mac:** Open Terminal and run: `brew install python3` (or download from python.org)
- **Windows:** Download from https://www.python.org/downloads/ — **check "Add Python to PATH" during install**

---

## Step 2: Install the Yahoo Finance library

Open Terminal / Command Prompt and run:
```
pip install yfinance
```

If that doesn't work, try:
```
pip3 install yfinance
```

You should see it download and install. This only needs to be done once.

---

## Step 3: Set up your folder

Create a folder anywhere on your computer (like your Desktop) called `earnings-analyzer`.

Put these two files in it:
```
earnings-analyzer/
  ├── earnings-analyzer.html    ← the dashboard
  └── fetch_stock.py            ← the data fetcher
```

---

## Step 4: Fetch stock data

Open Terminal / Command Prompt, navigate to your folder, and run:

**Single stock:**
```
cd ~/Desktop/earnings-analyzer
python3 fetch_stock.py SOFI
```

**Multiple stocks at once:**
```
python3 fetch_stock.py F SOFI HIMS NIO PLTR HOOD LC UPST
```

**What happens:**
- The script pulls live data from Yahoo Finance for each ticker
- It saves everything to `stock_data.json` in the same folder
- You'll see a progress log for each stock

Your folder now looks like:
```
earnings-analyzer/
  ├── earnings-analyzer.html
  ├── fetch_stock.py
  └── stock_data.json           ← auto-created with live data
```

---

## Step 5: Open the dashboard

**Option A: Simple double-click (works for demo data)**
Just double-click `earnings-analyzer.html` to open it in your browser.

**Option B: Local server (required for live JSON loading)**
Because browsers block loading local JSON files for security, you need a simple local server. This sounds scary but it's one command:

**Mac / Linux:**
```
cd ~/Desktop/earnings-analyzer
python3 -m http.server 8000
```

**Windows:**
```
cd Desktop\earnings-analyzer
python -m http.server 8000
```

Then open your browser and go to:
```
http://localhost:8000/earnings-analyzer.html
```

**You'll see the header change from "Demo" to "LIVE" with your tickers listed.**

---

## Step 6: Analyze stocks

1. Type any ticker you fetched into the search bar (or click the quick-select buttons)
2. Click **⚡ Analyze**
3. Review the full criteria checklist, fundamentals, peers, and sentiment score
4. Click **"Open in Fidelity ↗"** to pull real-time options chain data from your Fidelity account
5. Use the 90-day best/worst range to set your strike prices

---

## Daily Workflow

Each trading day (or whenever you want fresh data):

```
cd ~/Desktop/earnings-analyzer
python3 fetch_stock.py SOFI F HIMS AMD INTC BAC
```

Then refresh your browser tab — the dashboard auto-reads the new data.

**Pro tip:** Create a batch script so you can update with one click:

**Mac (save as `update.sh`):**
```bash
#!/bin/bash
cd ~/Desktop/earnings-analyzer
python3 fetch_stock.py SOFI F HIMS NIO PLTR HOOD LC AMD
echo "Done! Refresh your browser."
```
Then run: `chmod +x update.sh` and double-click it.

**Windows (save as `update.bat`):**
```bat
@echo off
cd %USERPROFILE%\Desktop\earnings-analyzer
python fetch_stock.py SOFI F HIMS NIO PLTR HOOD LC AMD
echo Done! Refresh your browser.
pause
```
Double-click to run.

---

## Options Data (from Fidelity)

The Python script generates **estimated** options premiums based on implied volatility. 
For real premiums before placing a trade:

1. Click **"Open in Fidelity ↗"** on the Options Chain card
2. This opens Fidelity's option chain tool with your ticker pre-loaded
3. Select the expiration ~1-2 weeks after the earnings date
4. Look at the ATM and OTM calls for covered call premiums
5. Fidelity lets you export the chain to CSV if you want to save it

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `pip: command not found` | Try `pip3` instead, or `python3 -m pip install yfinance` |
| `No module named yfinance` | Run `pip install yfinance` again |
| Dashboard shows "Demo" not "Live" | Make sure `stock_data.json` is in the same folder as the HTML file, and you're using `localhost:8000` not `file://` |
| Stock data looks stale | Re-run `python3 fetch_stock.py TICKER` to refresh |
| Peer data missing | Some small-cap stocks don't have good peer mapping — the script does its best |
| "No price data found" error | Check the ticker symbol is correct (use the Yahoo Finance symbol) |

---

## File Reference

| File | Purpose |
|------|---------|
| `earnings-analyzer.html` | The dashboard — open in browser |
| `fetch_stock.py` | Python script that pulls live data from Yahoo Finance |
| `stock_data.json` | Auto-generated data file (don't edit manually) |
| `README.md` | This setup guide |
