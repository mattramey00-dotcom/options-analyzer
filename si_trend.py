#!/usr/bin/env python3
"""
Short-interest trend — the one squeeze component the live feed
can't give directly. yfinance reports only the CURRENT settlement
figure, so this module keeps a small dated history (si_history.json,
committed by the daily Action alongside stock_data.json) and the
trend is the signed % change vs the most recent observation at
least MIN_GAP_DAYS old — roughly one FINRA settlement cycle, so
the comparison is report-to-report, not day-to-day noise.

History can be seeded from the git history of stock_data.json
(daily snapshots carry each ticker's short % of float), which is
how the first trend values were produced in November 2026.
"""
import json
import os
from datetime import date, timedelta

HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'si_history.json')
MIN_GAP_DAYS = 10
PRUNE_DAYS = 150


def load_history(path=HISTORY_PATH):
    try:
        with open(path) as f:
            h = json.load(f)
        return h if isinstance(h, dict) else {}
    except Exception:
        return {}


def save_history(hist, path=HISTORY_PATH):
    with open(path, 'w') as f:
        json.dump(hist, f, indent=1, sort_keys=True)


def trend_for(ticker, current_pct, hist=None, today=None):
    """Signed % change in short % of float vs the newest stored
    observation at least MIN_GAP_DAYS old. None when there is no
    usable prior observation — the scorer then marks the trend
    component honestly unmeasured."""
    if current_pct is None or current_pct <= 0:
        return None
    hist = hist if hist is not None else load_history()
    today = today or date.today()
    cutoff = today - timedelta(days=MIN_GAP_DAYS)
    entries = (hist or {}).get(ticker) or {}
    usable = []
    for dstr, pct in entries.items():
        try:
            d = date.fromisoformat(dstr)
            p = float(pct)
        except Exception:
            continue
        if d <= cutoff and p > 0:
            usable.append((d, p))
    if not usable:
        return None
    usable.sort()
    prior = usable[-1][1]
    return round((current_pct - prior) / prior * 100, 1)


def record(ticker, pct, hist=None, today=None):
    """Store today's observation (one per day) and prune old ones.
    Mutates and returns the history dict; caller saves."""
    if pct is None or pct <= 0:
        return hist
    hist = hist if hist is not None else load_history()
    today = today or date.today()
    entries = hist.setdefault(ticker, {})
    entries[today.isoformat()] = round(float(pct), 2)
    cutoff = today - timedelta(days=PRUNE_DAYS)
    for dstr in list(entries.keys()):
        try:
            if date.fromisoformat(dstr) < cutoff:
                del entries[dstr]
        except Exception:
            del entries[dstr]
    return hist
