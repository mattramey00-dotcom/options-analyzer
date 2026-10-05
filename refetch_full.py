#!/usr/bin/env python3
"""
Helper: reads stock_data.json, gets the ticker list, 
and re-fetches each one through fetch_stock.py for full catalyst data.
"""
import json
import os
import subprocess
import sys

json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_data.json')

if not os.path.exists(json_path):
    print("  No stock_data.json found — nothing to re-fetch.")
    sys.exit(0)

try:
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    tickers = list(data.keys())
    if not tickers:
        print("  No tickers in stock_data.json.")
        sys.exit(0)
    
    print(f"  Re-fetching {len(tickers)} tickers with full catalyst data: {', '.join(tickers)}")
    
    # Call fetch_stock.py with all tickers
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fetch_script = os.path.join(script_dir, 'fetch_stock.py')
    
    subprocess.run([sys.executable, fetch_script] + tickers, cwd=script_dir)
    
except Exception as e:
    print(f"  Error: {e}")
    sys.exit(1)
