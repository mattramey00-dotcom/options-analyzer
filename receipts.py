#!/usr/bin/env python3
"""
Receipts — the app's own track record. The scanner snapshots the
scores of every name reporting within SNAPSHOT_WINDOW_DAYS days
(price, both scores, direction verdict, the priced/implied move),
then grades each snapshot after the print against the actual move:
close of the last trading day before the earnings date vs close of
the first trading day after it (the same window convention as
scoring.compute_earnings_move — captures BMO and AMC prints).

Grades are factual, not win/loss theatre:
  premiumRead — 'cheap' when the actual |move| beat the priced
    move (premium buyers got more than they paid for), 'rich'
    when it fell short. The earnings score grades premium and
    structure, so this is its honest scoreboard.
  squeezeRead — only for names whose snapshot squeeze score was
    >= 45 (a real candidate): 'fired' (+2% or more through the
    print), 'fell' (-2% or worse), 'flat' in between.

receipts.json is committed by the daily Action next to
stock_data.json and read by the app's Receipts view.
"""
import json
import os
from datetime import date, timedelta

RECEIPTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'receipts.json')
SNAPSHOT_WINDOW_DAYS = 7
GRADE_GIVE_UP_DAYS = 21
SQUEEZE_CANDIDATE_MIN = 45


def load_receipts(path=RECEIPTS_PATH):
    try:
        with open(path) as f:
            r = json.load(f)
        if isinstance(r, dict) and isinstance(r.get('entries'), list):
            return r
    except Exception:
        pass
    return {'version': 1, 'entries': []}


def save_receipts(receipts, path=RECEIPTS_PATH):
    with open(path, 'w') as f:
        json.dump(receipts, f, indent=1)


def _score_total(obj):
    return obj.get('total') if isinstance(obj, dict) else None


def snapshot_due(data, receipts, today=None):
    """Add pre-print snapshots for names reporting within the
    window. Idempotent per (ticker, earningsDate). Returns the
    number added."""
    today = today or date.today()
    have = {(e.get('ticker'), e.get('earningsDate')) for e in receipts['entries']}
    added = 0
    for ticker, rec in (data or {}).items():
        if not isinstance(rec, dict):
            continue
        days = rec.get('daysToEarnings')
        edate = rec.get('earningsDate')
        if not isinstance(days, (int, float)) or not (1 <= days <= SNAPSHOT_WINDOW_DAYS):
            continue
        if not edate or edate == 'TBD':
            continue
        if (ticker, edate) in have:
            continue
        iv = rec.get('impliedVolatility') or {}
        em = rec.get('earningsMove') or {}
        expected = iv.get('expectedMovePct') or em.get('impliedMovePct')
        direction = rec.get('direction') or {}
        receipts['entries'].append({
            'ticker': ticker,
            'name': rec.get('name') or ticker,
            'earningsDate': edate,
            'snappedOn': today.isoformat(),
            'price': rec.get('price'),
            'earningsScore': _score_total(rec.get('score')),
            'squeezeScore': _score_total(rec.get('squeezeScore')),
            'direction': direction.get('verdict') if isinstance(direction, dict) else None,
            'expectedMovePct': expected,
            'graded': False,
        })
        have.add((ticker, edate))
        added += 1
    return added


def _grade_one(entry):
    """Fetch closes around the print and fill the grade fields.
    Returns True when graded. Uses yfinance lazily so importing
    this module never requires it."""
    import yfinance as yf
    ed = date.fromisoformat(entry['earningsDate'])
    hist = yf.Ticker(entry['ticker']).history(
        start=(ed - timedelta(days=10)).isoformat(),
        end=(ed + timedelta(days=7)).isoformat(),
        auto_adjust=False)
    if hist is None or hist.empty:
        return False
    days = [(ix.date() if hasattr(ix, 'date') else ix, float(c))
            for ix, c in zip(hist.index, hist['Close'].tolist())]
    pre = [c for d, c in days if d < ed]
    post = [c for d, c in days if d > ed]
    if not pre or not post:
        return False
    pre_close, post_close = pre[-1], post[0]
    if not pre_close:
        return False
    move = round((post_close / pre_close - 1) * 100, 1)
    entry['preClose'] = round(pre_close, 2)
    entry['postClose'] = round(post_close, 2)
    entry['movePct'] = move
    exp = entry.get('expectedMovePct')
    entry['premiumRead'] = None
    if isinstance(exp, (int, float)) and exp > 0:
        entry['premiumRead'] = 'cheap' if abs(move) >= exp else 'rich'
    entry['squeezeRead'] = None
    sq = entry.get('squeezeScore')
    if isinstance(sq, (int, float)) and sq >= SQUEEZE_CANDIDATE_MIN:
        entry['squeezeRead'] = 'fired' if move >= 2 else ('fell' if move <= -2 else 'flat')
    entry['graded'] = True
    entry['gradedOn'] = date.today().isoformat()
    return True


def grade_due(receipts, today=None):
    """Grade every snapshot whose print has landed. Entries older
    than GRADE_GIVE_UP_DAYS that still can't be graded are dropped
    rather than left 'awaiting' forever. Returns (graded, dropped)."""
    today = today or date.today()
    graded = dropped = 0
    keep = []
    for entry in receipts['entries']:
        if entry.get('graded'):
            keep.append(entry)
            continue
        try:
            ed = date.fromisoformat(entry['earningsDate'])
        except Exception:
            dropped += 1
            continue
        if ed >= today:
            keep.append(entry)
            continue
        try:
            ok = _grade_one(entry)
        except Exception:
            ok = False
        if ok:
            graded += 1
            keep.append(entry)
        elif (today - ed).days > GRADE_GIVE_UP_DAYS:
            dropped += 1
        else:
            keep.append(entry)
    receipts['entries'] = keep
    return graded, dropped
