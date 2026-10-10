#!/usr/bin/env python3
"""
=============================================================
  EARNINGS PLAY AUTO-SCANNER
=============================================================
  Scans the next 7-30 days of earnings, filters stocks through
  your criteria, and delivers qualified plays automatically.

  SETUP (one time):
    pip install yfinance requests

  USAGE:
    python scan_earnings.py              ← scans next 14 days (default)
    python scan_earnings.py --days 7     ← scans next 7 days
    python scan_earnings.py --days 30    ← scans next 30 days
    python scan_earnings.py --price-min 10 --price-max 25
    python scan_earnings.py --max-pe 50
    python scan_earnings.py --top 10     ← show top 10 results

  OUTPUT:
    Prints qualified plays to the terminal
    Saves them to stock_data.json for the dashboard
=============================================================
"""

import yfinance as yf
import json
import sys
import os
import argparse
import requests
import time
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed

# Unified scoring + shared helpers — the SINGLE source of truth for the
# composite score (see scoring.py). The dashboard only renders the score
# computed here / in fetch_stock.py; it never recomputes its own.
from scoring import (compute_score, compute_squeeze_score, compute_div_yield,
                     compute_earnings_move, detect_guidance, covered_call_flags,
                     hard_filter_failures)

# ========== EARNINGS CALENDAR SCRAPER ==========

def get_earnings_calendar(from_date, to_date):
    """
    Scrape Yahoo Finance earnings calendar for a date range.
    Returns list of dicts with ticker, company, earnings date, EPS estimate.
    """
    print(f"\n  📅 Scanning earnings from {from_date} to {to_date}...")
    
    all_earnings = []
    current = from_date
    
    while current <= to_date:
        date_str = current.strftime('%Y-%m-%d')
        url = f"https://finance.yahoo.com/calendar/earnings?day={date_str}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml',
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                # Parse the earnings from the page
                earnings = parse_yahoo_earnings_page(resp.text, date_str)
                all_earnings.extend(earnings)
                print(f"    {date_str}: found {len(earnings)} stocks reporting")
            else:
                print(f"    {date_str}: HTTP {resp.status_code} (skipped)")
        except Exception as e:
            print(f"    {date_str}: error ({e})")
        
        current += timedelta(days=1)
        time.sleep(0.5)  # Be nice to Yahoo
    
    # Deduplicate by ticker
    seen = set()
    unique = []
    for e in all_earnings:
        if e['ticker'] not in seen:
            seen.add(e['ticker'])
            unique.append(e)
            
    print(f"\n  📊 Total unique stocks with earnings: {len(unique)}")
    return unique


def parse_yahoo_earnings_page(html, date_str):
    """Parse earnings entries from Yahoo Finance calendar HTML."""
    entries = []
    
    # Simple parsing - look for ticker symbols in the earnings table
    # Yahoo uses JSON-embedded data or table rows
    try:
        # Try to find ticker symbols using pattern matching
        import re
        
        # Look for patterns like "/quote/AAPL" in the HTML
        ticker_pattern = re.findall(r'/quote/([A-Z]{1,5})(?:\?|")', html)
        
        # Deduplicate while preserving order
        seen = set()
        tickers = []
        for t in ticker_pattern:
            if t not in seen and len(t) <= 5 and t.isalpha():
                seen.add(t)
                tickers.append(t)
        
        for ticker in tickers:
            entries.append({
                'ticker': ticker,
                'earnings_date': date_str,
            })
    except:
        pass
    
    return entries


def get_earnings_via_yfinance_screener(days_ahead=14):
    """
    Alternative method: use a broad universe of common stocks
    and check which ones have earnings in the next N days.
    More reliable than scraping Yahoo calendar.
    """
    print(f"\n  📅 Scanning stock universe for earnings in next {days_ahead} days...")
    
    # Broad universe of liquid stocks in the $5-$50 range
    # This covers most of the stocks that would match the criteria
    universe = [
        # Financials / Fintech
        'SOFI', 'LC', 'HOOD', 'UPST', 'NU', 'AFRM', 'PSFE', 'OLO', 'PAYO',
        'OPEN', 'UWMC', 'RKT', 'CLOV', 'MARA', 'RIOT', 'COIN',
        # Auto / EV
        'F', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'FSR', 'GOEV', 'WKHS',
        # Tech under $50
        'PLTR', 'BB', 'NOK', 'SKLZ', 'WISH', 'BARK', 'IRNT', 'DNA',
        'AI', 'BBAI', 'SOUN', 'IONQ', 'RGTI', 'QUBT',
        # Healthcare / Biotech
        'HIMS', 'TDOC', 'AMWL', 'OSCR', 'GDRX', 'SDC', 'TALK', 'MNDY',
        # Consumer / Retail
        'DKNG', 'PENN', 'CHWY', 'ETSY', 'POSH', 'REAL', 'WISH', 'DTC',
        'AMC', 'GME', 'EXPR', 'BBBY', 'CLAR',
        # Energy / Mining
        'TELL', 'ET', 'CTRA', 'SM', 'RIG', 'BTU', 'CLF', 'X', 'AA',
        # Industrials
        'PLUG', 'FCEL', 'BLNK', 'CHPT', 'QS', 'MVST',
        # Mid-cap value
        'WFC', 'BAC', 'C', 'USB', 'KEY', 'RF', 'HBAN', 'CFG', 'ZION',
        'CMA', 'ALLY', 'FITB', 'MTB', 'TFC',
        # REITs
        'VICI', 'MPW', 'AGNC', 'NLY', 'STWD', 'ARR',
        # Other
        'SNAP', 'PINS', 'U', 'RBLX', 'CRSR', 'LOGI',
        'T', 'VZ', 'TMUS', 'LUMN',
        'WBD', 'PARA', 'FOX',
        'HPE', 'HPQ', 'DELL',
        'INTC', 'AMD', 'MU', 'QCOM',
        'KO', 'PEP', 'TAP', 'SAM',
        'CCL', 'RCL', 'NCLH',
        'DAL', 'UAL', 'AAL', 'LUV', 'SAVE',
    ]
    
    cutoff = datetime.now() + timedelta(days=days_ahead)
    earnings_upcoming = []
    
    print(f"  Checking {len(universe)} stocks...")
    
    batch_size = 10
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i+batch_size]
        pct = min(100, int((i / len(universe)) * 100))
        print(f"    [{pct:3d}%] Checking: {', '.join(batch)}...")
        
        for ticker_sym in batch:
            try:
                t = yf.Ticker(ticker_sym)
                cal = t.calendar
                
                if cal is None:
                    continue
                    
                # Extract earnings date
                earn_date = None
                if isinstance(cal, dict):
                    ed = cal.get('Earnings Date', None)
                    if isinstance(ed, list) and len(ed) > 0:
                        ed = ed[0]
                    if ed is not None:
                        if hasattr(ed, 'to_pydatetime'):
                            earn_date = ed.to_pydatetime()
                        elif isinstance(ed, date) and not isinstance(ed, datetime):
                            earn_date = datetime(ed.year, ed.month, ed.day)
                        elif isinstance(ed, datetime):
                            earn_date = ed
                
                if earn_date is None:
                    continue
                
                # Strip timezone
                if hasattr(earn_date, 'tzinfo') and earn_date.tzinfo is not None:
                    earn_date = earn_date.replace(tzinfo=None)
                
                # Check if within our window
                days_until = (earn_date - datetime.now()).days
                if 0 < days_until <= days_ahead:
                    earnings_upcoming.append({
                        'ticker': ticker_sym,
                        'earnings_date': earn_date.strftime('%Y-%m-%d'),
                        'days_until': days_until,
                    })
                    
            except Exception:
                continue
        
        time.sleep(0.3)  # Rate limiting
    
    # Sort by days until earnings
    earnings_upcoming.sort(key=lambda x: x['days_until'])
    
    print(f"\n  📊 Found {len(earnings_upcoming)} stocks with earnings in next {days_ahead} days")
    return earnings_upcoming


# ========== CRITERIA FILTER ==========

def _excluded_record(ticker_sym, info, earnings_info, price, pe, short_pct, reasons):
    """Minimal dashboard record for a hard-filter failure.

    Fail loudly: the ticker stays in stock_data.json with
    excluded:true + the reasons, instead of silently vanishing
    (the old behavior, which made 'scanner found nothing' and
    'scanner dropped it' indistinguishable).
    """
    # Squeeze score even here: an earnings-mode reject (e.g. short
    # interest above the earnings cap) is a PRIME squeeze candidate,
    # so the excluded record must stay scorable in Squeeze mode.
    # Computed from what the exclusion path actually knows — fuel,
    # burn, catalyst, liquidity; trend and realized move stay n/a.
    squeeze = None
    try:
        squeeze = compute_squeeze_score({
            'shortPct': short_pct,
            'shortRatio': info.get('shortRatio') if info else None,
            'daysToEarnings': earnings_info.get('days_until'),
            'siTrend': None,        # feed carries current SI only
            'realizedMovePct': None,  # not measured on the exclusion path
            'avgVol': info.get('averageVolume') if info else None,
        })
    except Exception:
        squeeze = None
    return {
        'name': (info.get('longName') or info.get('shortName', ticker_sym)) if info else ticker_sym,
        'sector': info.get('sector', 'Unknown') if info else 'Unknown',
        'industry': info.get('industry', 'Unknown') if info else 'Unknown',
        'price': round(price, 2) if price else 0,
        'pe': round(pe, 1) if pe and pe > 0 else -1,
        'shortInt': f"{round(short_pct, 1)}%" if short_pct is not None else 'n/a',
        'shortRatio': round(info.get('shortRatio') or 0, 1) if info else 0,
        'earningsDate': earnings_info.get('earnings_date', 'TBD'),
        'daysToEarnings': earnings_info.get('days_until', 0),
        'excluded': True,
        'excludedReasons': reasons,
        'score': None,
        'squeezeScore': squeeze,
    }


def evaluate_stock(ticker_sym, earnings_info, criteria):
    """
    Pull full data for a stock and evaluate against earnings play criteria.

    Returns one of:
      (score, data_dict)   — passed the hard filters, fully scored
      (None, excluded_dict) — failed hard filters; dict carries
                              excluded:true + excludedReasons so the
                              ticker stays visible in the dashboard
      None                 — data fetch failed entirely (no price)
    """
    try:
        ticker = yf.Ticker(ticker_sym)
        info = ticker.info

        if not info:
            return None

        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        if not price:
            return None

        pe = info.get('trailingPE') or -1
        fwd_pe = info.get('forwardPE') or -1
        eps = info.get('trailingEps') or 0
        fwd_eps = info.get('forwardEps') or 0
        wk52_low = info.get('fiftyTwoWeekLow') or price * 0.7
        wk52_high = info.get('fiftyTwoWeekHigh') or price * 1.3
        short_pct = (info.get('shortPercentOfFloat') or 0) * 100
        beta = info.get('beta') or 1.0
        mkt_cap = info.get('marketCap') or 0
        avg_vol = info.get('averageVolume') or 0
        pct_from_high = ((wk52_high - price) / wk52_high) * 100

        # ===== HARD FILTERS — fail loudly, never silently =====
        failures = hard_filter_failures(
            {'price': price, 'pe': pe, 'eps': eps, 'shortPct': short_pct,
             'pctFromHigh': pct_from_high, 'avgVol': avg_vol},
            criteria)
        if failures:
            return (None, _excluded_record(ticker_sym, info, earnings_info,
                                           price, pe, short_pct, failures))

        rec = info.get('recommendationKey', 'hold')
        profit_margin = info.get('profitMargins') or 0
        days_to = earnings_info.get('days_until', 30)

        # ===== BUILD FULL DATA FOR DASHBOARD =====
        # Instead of importing fetch_stock, build the data inline
        full_data = build_stock_data(ticker_sym, ticker, info, earnings_info, price, pe, fwd_pe, eps, fwd_eps,
                                      wk52_low, wk52_high, short_pct, beta, mkt_cap, avg_vol,
                                      pct_from_high, profit_margin, rec)
        if not full_data:
            return None

        # ===== UNIFIED SCORE (single source of truth — scoring.py) =====
        iv_block = full_data.get('impliedVolatility') or {}
        move_block = full_data.get('earningsMove') or {}
        facts = {
            'price': price,
            'pe': pe,
            'wk52High': wk52_high,
            'shortRatio': full_data.get('shortRatio'),
            'shortPct': round(short_pct, 1),
            'daysToEarnings': days_to,
            'surprises': full_data.get('surprises'),
            'impliedMovePct': iv_block.get('expectedMovePct'),
            'realizedMovePct': move_block.get('avgAbsMovePct'),
            'ivPct': iv_block.get('iv'),
            'sentiment': full_data.get('sentiment'),
            'momentum': full_data.get('momentum'),
            'revenueGrowth': (full_data.get('growthMetrics') or {}).get('revenueGrowth'),
            'insiderSignal': None,   # scanner pass doesn't pull insider flow
            'analystSignal': None,   # (refetch_full.py fills the full record)
        }
        score_obj = compute_score(facts)
        full_data['score'] = score_obj
        full_data['_scan_score'] = score_obj['total']
        full_data['_scan_reasons'] = build_reasons(score_obj)

        # ===== SQUEEZE SCORE (second, independent score) =====
        squeeze_obj = compute_squeeze_score({
            'shortPct': round(short_pct, 1),
            'shortRatio': full_data.get('shortRatio'),
            'daysToEarnings': days_to,
            'siTrend': None,   # feed carries current SI only — honest n/a
            'realizedMovePct': move_block.get('avgAbsMovePct'),
            'avgVol': avg_vol,
        })
        full_data['squeezeScore'] = squeeze_obj
        full_data['_scan_squeeze_score'] = squeeze_obj['total']
        return (score_obj['total'], full_data)

    except Exception as e:
        return None


def build_stock_data(ticker_sym, ticker, info, earnings_info, price, pe, fwd_pe, eps, fwd_eps,
                     wk52_low, wk52_high, short_pct, beta, mkt_cap, avg_vol,
                     pct_from_high, profit_margin, rec):
    """Build a complete stock data dict for the dashboard."""
    try:
        # Shared dividend-yield helper (the old inline *100 of yfinance's
        # inconsistent field is how RF ended up showing a 405% yield).
        div_yield = compute_div_yield(info, price)
        stock_data = {
            'name': info.get('longName') or info.get('shortName', ticker_sym),
            'sector': info.get('sector', 'Unknown'),
            'industry': info.get('industry', 'Unknown'),
            'price': round(price, 2),
            'dayLow': round(info.get('dayLow') or price * 0.98, 2),
            'dayHigh': round(info.get('dayHigh') or price * 1.02, 2),
            'wk52Low': round(wk52_low, 2),
            'wk52High': round(wk52_high, 2),
            'pe': round(pe, 1) if pe > 0 else -1,
            'fwdPe': round(fwd_pe, 1) if fwd_pe and fwd_pe > 0 else -1,
            'eps': round(eps, 2),
            'fwdEps': round(fwd_eps, 2) if fwd_eps else 0,
            'mktCap': format_number(mkt_cap),
            'avgVol': format_number(avg_vol),
            'div': round(info.get('dividendRate') or 0, 2),
            'divYield': div_yield['divYield'],
            'divYieldPct': div_yield['divYieldPct'],
            'divYieldSuspect': div_yield['divYieldSuspect'],
            'beta': round(beta, 2),
            'shortInt': f"{round(short_pct, 1)}%",
            'shortRatio': round(info.get('shortRatio') or 0, 1),
            'earningsDate': earnings_info.get('earnings_date', 'TBD'),
            'daysToEarnings': earnings_info.get('days_until', 0),
        }
        
        # Analyst targets
        stock_data['targets'] = {
            'low': round(info.get('targetLowPrice') or price * 0.8, 2),
            'avg': round(info.get('targetMeanPrice') or price, 2),
            'high': round(info.get('targetHighPrice') or price * 1.4, 2),
        }
        
        # Analyst ratings
        num_analysts = info.get('numberOfAnalystOpinions', 10)
        if rec in ['strong_buy', 'buy']:
            stock_data['analystRatings'] = {'buy': int(num_analysts * 0.6), 'hold': int(num_analysts * 0.3), 'sell': int(num_analysts * 0.1)}
        elif rec == 'hold':
            stock_data['analystRatings'] = {'buy': int(num_analysts * 0.3), 'hold': int(num_analysts * 0.5), 'sell': int(num_analysts * 0.2)}
        else:
            stock_data['analystRatings'] = {'buy': int(num_analysts * 0.15), 'hold': int(num_analysts * 0.35), 'sell': int(num_analysts * 0.5)}
        
        # Earnings surprises (last 4 quarters)
        try:
            eh = ticker.earnings_history
            if eh is not None and not eh.empty:
                surprises = []
                for _, row in eh.tail(4).iterrows():
                    est = row.get('epsEstimate') or 0
                    actual = row.get('epsActual') or 0
                    pct = round(((actual - est) / abs(est)) * 100, 1) if est != 0 else 0
                    surprises.append({'q': str(row.name)[:7], 'est': round(est, 2), 'actual': round(actual, 2), 'pct': pct})
                stock_data['surprises'] = surprises[-4:] if surprises else default_surprises()
            else:
                stock_data['surprises'] = default_surprises()
        except:
            stock_data['surprises'] = default_surprises()
        
        stock_data['lastYearEarnings'] = {
            'q': stock_data['surprises'][0]['q'] if stock_data['surprises'] else 'N/A',
            'eps': stock_data['surprises'][0]['actual'] if stock_data['surprises'] else 0,
            'revenue': stock_data['mktCap'],
            'reaction': '+/- TBD'
        }
        
        # 52-week price history
        try:
            hist = ticker.history(period="1y", interval="1wk")
            if hist is not None and not hist.empty:
                closes = hist['Close'].dropna().tolist()
                if len(closes) > 24:
                    step = len(closes) / 24
                    stock_data['prices52w'] = [round(closes[int(i * step)], 2) for i in range(24)]
                else:
                    stock_data['prices52w'] = [round(c, 2) for c in closes]
            else:
                stock_data['prices52w'] = [price] * 24
        except:
            stock_data['prices52w'] = [price] * 24
        
        # 90-day risk range
        try:
            hist90 = ticker.history(period="3mo")
            if hist90 is not None and not hist90.empty:
                stock_data['risk90d'] = {'best': round(hist90['High'].max(), 2), 'worst': round(hist90['Low'].min(), 2)}
            else:
                stock_data['risk90d'] = {'best': round(price * 1.2, 2), 'worst': round(price * 0.8, 2)}
        except:
            stock_data['risk90d'] = {'best': round(price * 1.2, 2), 'worst': round(price * 0.8, 2)}
        
        # Sentiment
        value = 'Undervalued' if pe > 0 and pe < 15 else ('Fair Value' if pe > 0 and pe < 30 else ('Overvalued' if pe > 50 else 'Speculative'))
        quality = 'High Quality' if profit_margin > 0.15 else ('Mixed' if profit_margin > 0.05 else 'Low')
        debt_equity = info.get('debtToEquity') or 0
        current_ratio = info.get('currentRatio') or 1
        financials = 'Strong' if current_ratio > 1.5 and debt_equity < 100 else ('Adequate' if current_ratio > 1 else 'Weak')
        stock_data['sentiment'] = {'value': value, 'quality': quality, 'financials': financials}

        # Momentum — None (not 0) when history is short, so missing data
        # renders "n/a" and stays out of the score instead of faking "Mixed".
        try:
            hist_6m = ticker.history(period="6mo")
            if hist_6m is not None and not hist_6m.empty:
                closes = hist_6m['Close'].dropna()  # trailing partial-session row is NaN
                current = closes.iloc[-1]

                def _pc(n):
                    if len(closes) > n:
                        ref = closes.iloc[-n]
                        if ref and current == current and ref == ref:
                            return round(((current / ref) - 1) * 100, 1)
                    return None

                d5, d30, d90 = _pc(5), _pc(21), _pc(63)
                if d5 is None or d30 is None:
                    trend = 'No Data'
                elif d30 > 0 and d5 > 0:
                    trend = 'Bullish'
                elif d30 < 0 and d5 < 0:
                    trend = 'Bearish'
                else:
                    trend = 'Mixed'
                stock_data['momentum'] = {'day5': d5, 'day30': d30, 'day90': d90, 'trend': trend}
            else:
                stock_data['momentum'] = {'day5': None, 'day30': None, 'day90': None, 'trend': 'No Data'}
        except:
            stock_data['momentum'] = {'day5': None, 'day30': None, 'day90': None, 'trend': 'No Data'}

        # Revenue growth
        rev_growth = info.get('revenueGrowth')
        stock_data['growthMetrics'] = {
            'revenueGrowth': round(rev_growth * 100, 1) if rev_growth else None,
            'earningsGrowth': round(info.get('earningsGrowth') * 100, 1) if info.get('earningsGrowth') else None,
            'qtrRevenueGrowth': round(info.get('quarterlyRevenueGrowth') * 100, 1) if info.get('quarterlyRevenueGrowth') else None,
            'qtrEarningsGrowth': round(info.get('quarterlyEarningsGrowth') * 100, 1) if info.get('quarterlyEarningsGrowth') else None,
            'signal': 'Strong' if (rev_growth and rev_growth > 0.15) else (
                'Growing' if (rev_growth and rev_growth > 0) else (
                    'Declining' if (rev_growth and rev_growth < 0) else 'Unknown')),
        }

        # Implied volatility & expected move (info first, ATM chain fallback)
        iv_val = info.get('impliedVolatility') or None
        if iv_val is None:
            try:
                opts = ticker.options
                if opts:
                    chain = ticker.option_chain(opts[0])
                    if chain and not chain.calls.empty:
                        nearest = (chain.calls['strike'] - price).abs().idxmin()
                        iv_val = chain.calls.loc[nearest, 'impliedVolatility']
            except:
                pass
        if iv_val and iv_val > 0:
            days_to_earn = stock_data['daysToEarnings'] or 30
            stock_data['impliedVolatility'] = {
                'iv': round(iv_val * 100, 1),
                'expectedMovePct': round(iv_val * (days_to_earn / 365) ** 0.5 * 100, 1),
                'expectedMoveDollar': round(price * iv_val * (days_to_earn / 365) ** 0.5, 2),
                'signal': 'High IV' if iv_val > 0.6 else ('Moderate IV' if iv_val > 0.3 else 'Low IV'),
            }
        else:
            stock_data['impliedVolatility'] = {'iv': None, 'expectedMovePct': None, 'expectedMoveDollar': None, 'signal': 'Unknown'}

        # Realized earnings move (avg |move| over last 4–8 prints) vs implied
        realized = compute_earnings_move(ticker)
        implied_pct = stock_data['impliedVolatility'].get('expectedMovePct')
        stock_data['earningsMove'] = {
            'avgAbsMovePct': realized['avgAbsMovePct'] if realized else None,
            'count': realized['count'] if realized else 0,
            'moves': realized['moves'] if realized else [],
            'impliedMovePct': implied_pct,
            'edgeRatio': round(implied_pct / realized['avgAbsMovePct'], 2) if (realized and implied_pct) else None,
        }

        # Guidance flag — 'unknown' unless a reliable source says otherwise
        stock_data['guidance'] = detect_guidance(ticker)

        # Covered-call dividend flags (ex-div / early assignment)
        stock_data['dividendFlags'] = covered_call_flags(info, stock_data['daysToEarnings'])

        # Extra fundamentals (same shape as fetch_stock.py)
        stock_data['fundamentalsExtra'] = {
            'profitMargin': round((info.get('profitMargins') or 0) * 100, 1),
            'grossMargin': round((info.get('grossMargins') or 0) * 100, 1),
            'operatingMargin': round((info.get('operatingMargins') or 0) * 100, 1),
            'debtToEquity': round(info.get('debtToEquity') or 0, 1),
            'currentRatio': round(info.get('currentRatio') or 0, 2),
            'floatShares': format_number(info.get('floatShares') or 0),
            'sharesOutstanding': format_number(info.get('sharesOutstanding') or 0),
            'exDivDate': str(info.get('exDividendDate', 'N/A')),
            'earningsEstRevision': 0,
        }

        stock_data['description'] = (info.get('longBusinessSummary') or 'No description available.')[:500]
        stock_data['peerMismatch'] = f"Review {ticker_sym} vs sector peers on Finviz and Fidelity research."
        
        # Placeholder peers (dashboard has Fidelity links for real comparison)
        stock_data['peers'] = [{'ticker': 'See Fidelity', 'name': 'Use research links', 'price': 0, 'pe': 0, 'rating': 'N/A', 'target': 0, 'chg': 0}]
        
        # Options placeholder
        atm = round(price)
        step = max(0.5, round(price * 0.03, 1))
        if price < 5: step = 0.5
        elif price < 20: step = 1
        elif price < 50: step = 2.5
        else: step = 5
        
        strikes = [round(atm - 4*step + i*step, 1) for i in range(9)]
        strikes = [s for s in strikes if s > 0]
        
        iv = info.get('impliedVolatility') or 0.4
        days_exp = stock_data['daysToEarnings'] + 14
        calls, puts = [], []
        for s in strikes:
            moneyness = (price - s) / price
            time_val = price * iv * (days_exp / 365) ** 0.5 * 0.4
            calls.append(round(max(0.01, max(0, price - s) + time_val * max(0.1, 1 - moneyness * 3)), 2))
            puts.append(round(max(0.01, max(0, s - price) + time_val * max(0.1, 1 + moneyness * 3)), 2))
        
        stock_data['options'] = {
            'strikes': strikes,
            'calls': calls,
            'puts': puts,
            'expiry': (datetime.now() + timedelta(days=days_exp)).strftime('%b %d, %Y') + ' (est.)',
        }
        
        return stock_data
    except Exception as e:
        print(f"          → error building data: {e}")
        return None


def default_surprises():
    return [{'q': 'N/A', 'est': 0, 'actual': 0, 'pct': 0}] * 4


def format_number(n):
    if not n: return '0'
    abs_n = abs(n)
    if abs_n >= 1e12: return f"{n/1e12:.1f}T"
    elif abs_n >= 1e9: return f"{n/1e9:.1f}B"
    elif abs_n >= 1e6: return f"{n/1e6:.1f}M"
    elif abs_n >= 1e3: return f"{n/1e3:.1f}K"
    return str(round(n))


def build_reasons(score_obj):
    """Terminal-display reasons, rendered from the unified score breakdown
    so what the CLI shows is exactly what the dashboard shows."""
    if not score_obj:
        return []
    reasons = []
    for c in score_obj.get('components', []):
        if not c['available']:
            reasons.append(f"· {c['label']}: n/a — excluded from score")
        elif c['points'] >= c['max'] * 0.6:
            reasons.append(f"✓ {c['detail']} (+{c['points']:g}/{c['max']:g})")
        elif c['points'] > 0:
            reasons.append(f"~ {c['detail']} (+{c['points']:g}/{c['max']:g})")
        else:
            reasons.append(f"✗ {c['detail']} (+0/{c['max']:g})")
    if score_obj.get('partial'):
        reasons.append(f"⚠ {score_obj.get('partialNote', 'Partial data')}")
    return reasons


# ========== MAIN ==========

def main():
    parser = argparse.ArgumentParser(
        description='Auto-scan upcoming earnings and find plays matching your criteria.',
        epilog='Example: python scan_earnings.py --days 14 --price-min 10 --price-max 25'
    )
    parser.add_argument('--days', type=int, default=14, help='Scan next N days (default: 14)')
    parser.add_argument('--price-min', type=float, default=8, help='Minimum price (default: $8)')
    parser.add_argument('--price-max', type=float, default=30, help='Maximum price (default: $30)')
    parser.add_argument('--max-pe', type=float, default=50, help='Maximum P/E ratio (default: 50)')
    parser.add_argument('--max-short', type=float, default=10, help='Maximum short interest %% (default: 10)')
    parser.add_argument('--min-pct-from-high', type=float, default=10, help='Min %% below 52wk high (default: 10)')
    parser.add_argument('--require-profitable', action='store_true', default=False, help='Only show profitable companies')
    parser.add_argument('--top', type=int, default=20, help='Show top N results (default: 20)')
    parser.add_argument('--output', '-o', default='.', help='Output directory (default: current)')
    
    args = parser.parse_args()
    
    criteria = {
        'price_min': args.price_min,
        'price_max': args.price_max,
        'max_pe': args.max_pe,
        'max_short': args.max_short,
        'min_pct_from_high': args.min_pct_from_high,
        'require_profitable': args.require_profitable,
    }
    
    print("""
╔══════════════════════════════════════════════════════╗
║     EARNINGS PLAY AUTO-SCANNER                       ║
║     Finding plays that match YOUR criteria            ║
╚══════════════════════════════════════════════════════╝
    """)
    
    print(f"  Criteria:")
    print(f"    Price range:     ${args.price_min} - ${args.price_max}")
    print(f"    Max P/E:         {args.max_pe}")
    print(f"    Max short int:   {args.max_short}%")
    print(f"    Min from high:   {args.min_pct_from_high}%")
    print(f"    Profitable only: {'Yes' if args.require_profitable else 'No'}")
    print(f"    Scan window:     Next {args.days} days")
    
    # Step 1: Find stocks with upcoming earnings
    earnings_list = get_earnings_via_yfinance_screener(days_ahead=args.days)
    
    if not earnings_list:
        print("\n  ✗ No earnings found in the scan window. Try --days 30")
        sys.exit(0)
    
    # Step 2: Quick pre-filter on price before deep analysis.
    # Out-of-range names are NOT silently skipped anymore — they get a
    # minimal excluded record with the reason, same as hard-filter fails.
    print(f"\n  🔍 Quick price-filtering {len(earnings_list)} candidates...")
    pre_filtered = []
    excluded = []
    for e in earnings_list:
        try:
            t = yf.Ticker(e['ticker'])
            info = t.info
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose', 0)
            if price and args.price_min <= price <= args.price_max:
                pre_filtered.append(e)
                print(f"    ✓ {e['ticker']:6s} ${price:>8.2f}  — earnings {e['earnings_date']} ({e['days_until']}d)")
            elif price:
                reason = (f"Price ${price:.2f} below the ${args.price_min:.0f} minimum"
                          if price < args.price_min else
                          f"Price ${price:.2f} above the ${args.price_max:.0f} maximum")
                excluded.append((e['ticker'], _excluded_record(
                    e['ticker'], info, e, price,
                    info.get('trailingPE') or -1,
                    (info.get('shortPercentOfFloat') or 0) * 100,
                    [reason])))
                print(f"    ✗ {e['ticker']:6s} ${price:>8.2f}  — filtered: {reason}")
        except:
            continue
        time.sleep(0.2)

    print(f"\n  📋 {len(pre_filtered)} stocks in ${args.price_min}-${args.price_max} range with upcoming earnings")

    if not pre_filtered and not excluded:
        print("\n  ✗ No stocks match price criteria. Try widening --price-min / --price-max")
        sys.exit(0)
    
    # Step 3: Deep analysis on price-qualified stocks
    print(f"\n  🔬 Running deep analysis on {len(pre_filtered)} candidates...")
    print(f"     (This will take a minute — pulling full data for each stock)\n")
    
    qualified = []
    for i, e in enumerate(pre_filtered):
        pct = int(((i + 1) / len(pre_filtered)) * 100) if pre_filtered else 100
        print(f"    [{pct:3d}%] Analyzing {e['ticker']}...")

        result = evaluate_stock(e['ticker'], e, criteria)
        if result:
            score, data = result
            if score is not None:
                qualified.append((score, e['ticker'], data))
            else:
                # Hard-filter failure — kept, with reasons (fail loudly)
                excluded.append((e['ticker'], data))
                print(f"          → filtered out: {'; '.join(data.get('excludedReasons', []))}")
        else:
            print(f"          → data fetch failed (no price available)")

        time.sleep(0.3)

    # Sort by score descending (None totals — nothing measurable — last)
    qualified.sort(key=lambda x: (x[0] is not None, x[0] or 0), reverse=True)

    # Trim display/save set to top N (excluded records are never trimmed)
    qualified = qualified[:args.top]

    # Step 4: Display results
    print(f"\n{'='*60}")
    print(f"  🏆 TOP {len(qualified)} EARNINGS PLAYS")
    print(f"{'='*60}\n")

    if not qualified:
        print("  No stocks passed all criteria filters.")
        print("  Try relaxing some parameters:")
        print("    --price-min 5 --price-max 40")
        print("    --max-pe 80")
        print("    --max-short 15")
    else:
        for rank, (score, ticker, data) in enumerate(qualified, 1):
            reasons = data.get('_scan_reasons', [])
            partial_tag = ' (partial data)' if (data.get('score') or {}).get('partial') else ''
            print(f"  #{rank}  {ticker:6s}  ${data['price']:<8.2f}  Score: {score}/100{partial_tag}")
            print(f"       Earnings: {data['earningsDate']} ({data['daysToEarnings']}d away)")
            print(f"       P/E: {data['pe'] if data['pe'] > 0 else 'N/A':>6}  |  Short: {data['shortInt']:>5}  |  52wk: ${data['wk52Low']}-${data['wk52High']}")
            sq = data.get('squeezeScore') or {}
            if sq.get('total') is not None:
                sq_line = f"       Squeeze: {sq['total']}/100 {sq.get('grade', '')}{' (partial data)' if sq.get('partial') else ''}{' ⚡ fast cover' if sq.get('fastCover') else ''}"
                print(sq_line)
                if sq.get('capNote'):
                    print(f"       ⚠ {sq['capNote']}")
            for r in reasons:
                print(f"       {r}")
            print()

    if excluded:
        print(f"  ✗ FILTERED OUT of Earnings mode — kept in stock_data.json with reasons ({len(excluded)}):")
        for ticker, rec in excluded:
            sq = rec.get('squeezeScore') or {}
            sq_txt = (f"  |  Squeeze: {sq['total']}/100 {sq.get('grade', '')}" if sq.get('total') is not None else "")
            print(f"     {ticker:6s} ${rec.get('price', 0):<8.2f}  {'; '.join(rec.get('excludedReasons', []))}{sq_txt}")
        print()

    # Step 5: Save to stock_data.json
    output_path = os.path.join(args.output, 'stock_data.json')

    # Merge with existing data
    existing = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, 'r') as f:
                existing = json.load(f)
        except:
            existing = {}

    for score, ticker, data in qualified:
        # Clean internal scan fields before saving
        clean_data = {k: v for k, v in data.items() if not k.startswith('_')}
        existing[ticker] = clean_data

    # Excluded records are saved too (excluded:true + reasons) so a
    # filtered name stays visible in the dashboard instead of vanishing.
    for ticker, rec in excluded:
        existing[ticker] = rec
    
    # NaN/Infinity are not valid JSON (RFC 8259) — Python's json module
    # writes them as bare `NaN`/`Infinity` tokens anyway, which a
    # browser's strict JSON.parse() rejects outright (this previously
    # broke the live site silently: Python's own json.loads() and direct
    # navigation both accept such a file fine, only the page's own
    # fetch().then(r => r.json()) call threw). Sanitize to null before
    # writing, and keep allow_nan=False as a hard guard.
    def sanitize_json(obj):
        if isinstance(obj, float):
            return None if (obj != obj or obj in (float('inf'), float('-inf'))) else obj
        if isinstance(obj, dict):
            return {k: sanitize_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize_json(v) for v in obj]
        return obj

    with open(output_path, 'w') as f:
        json.dump(sanitize_json(existing), f, indent=2, default=str, allow_nan=False)
    
    print(f"{'='*60}")
    print(f"  ✓ Saved {len(qualified)} plays + {len(excluded)} excluded (with reasons) to: {os.path.abspath(output_path)}")
    print(f"  ✓ Total tickers in file: {len(existing)}")
    print(f"{'='*60}")
    print(f"\n  NEXT: Open your dashboard and these stocks are ready to analyze!")
    print(f"  Quick buttons will auto-update with the new tickers.\n")


if __name__ == '__main__':
    main()
