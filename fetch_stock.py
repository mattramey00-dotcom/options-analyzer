#!/usr/bin/env python3
"""
=============================================================
  EARNINGS PLAY ANALYZER — Stock Data Fetcher
=============================================================
  This script pulls live data for any stock ticker and saves
  it as a JSON file that the dashboard reads automatically.

  SETUP (one time):
    pip install yfinance

  USAGE:
    python fetch_stock.py SOFI
    python fetch_stock.py F HIMS NIO PLTR
    python fetch_stock.py SOFI --output my_folder

  OUTPUT:
    Creates stock_data.json in the same folder (or --output dir)
    Open earnings-analyzer.html in your browser — it reads this file.
=============================================================
"""

import yfinance as yf
import json
import sys
import os
import argparse
from datetime import datetime, timedelta, date

# Unified scoring + shared data helpers — the SINGLE source of truth
# for the composite score (see scoring.py). The dashboard only renders
# the score computed here; it never recomputes its own.
from scoring import (compute_score, compute_squeeze_score, compute_div_yield,
                     compute_earnings_move, detect_guidance, covered_call_flags)

def fetch_stock_data(ticker_symbol):
    """Fetch comprehensive data for a single ticker."""
    print(f"\n{'='*50}")
    print(f"  Fetching: {ticker_symbol.upper()}")
    print(f"{'='*50}")

    ticker = yf.Ticker(ticker_symbol.upper())

    # === BASIC INFO ===
    print("  [1/14] Getting company info...")
    try:
        info = ticker.info
    except Exception as e:
        print(f"  ✗ ERROR: Could not fetch data for {ticker_symbol}. Is the ticker correct?")
        print(f"    Details: {e}")
        return None

    if not info or 'currentPrice' not in info and 'regularMarketPrice' not in info:
        # Try fallback
        price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
        if not price:
            print(f"  ✗ ERROR: No price data found for {ticker_symbol}.")
            return None

    price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose', 0)

    # Dividend yield via the shared helper: yfinance's raw dividendYield
    # field is inconsistent (fraction vs percent) and the old inline
    # `* 100` produced absurd values (RF showed 405.0%).
    div_yield = compute_div_yield(info, price)

    stock_data = {
        'name': info.get('longName') or info.get('shortName', ticker_symbol.upper()),
        'sector': info.get('sector', 'Unknown'),
        'industry': info.get('industry', 'Unknown'),
        'price': round(price, 2),
        'dayLow': round(info.get('dayLow') or info.get('regularMarketDayLow', price * 0.98), 2),
        'dayHigh': round(info.get('dayHigh') or info.get('regularMarketDayHigh', price * 1.02), 2),
        'wk52Low': round(info.get('fiftyTwoWeekLow', price * 0.7), 2),
        'wk52High': round(info.get('fiftyTwoWeekHigh', price * 1.3), 2),
        'pe': round(info.get('trailingPE') or -1, 1),
        'fwdPe': round(info.get('forwardPE') or -1, 1),
        'eps': round(info.get('trailingEps') or 0, 2),
        'fwdEps': round(info.get('forwardEps') or 0, 2),
        'mktCap': format_large_number(info.get('marketCap', 0)),
        'avgVol': format_large_number(info.get('averageVolume', 0)),
        'div': round(info.get('dividendRate') or 0, 2),
        'divYield': div_yield['divYield'],
        'divYieldPct': div_yield['divYieldPct'],
        'divYieldSuspect': div_yield['divYieldSuspect'],
        'beta': round(info.get('beta') or 1.0, 2),
        'shortInt': f"{round((info.get('shortPercentOfFloat') or 0) * 100, 1)}%",
        'shortRatio': round(info.get('shortRatio') or 0, 1),
    }

    # === ANALYST TARGETS ===
    print("  [2/14] Getting analyst targets...")
    stock_data['targets'] = {
        'low': round(info.get('targetLowPrice') or price * 0.8, 2),
        'avg': round(info.get('targetMeanPrice') or price, 2),
        'high': round(info.get('targetHighPrice') or price * 1.4, 2),
    }

    # Analyst ratings
    rec = info.get('recommendationKey', 'hold')
    num_analysts = info.get('numberOfAnalystOpinions', 10)
    if rec in ['strong_buy', 'buy']:
        stock_data['analystRatings'] = {'buy': int(num_analysts * 0.6), 'hold': int(num_analysts * 0.3), 'sell': int(num_analysts * 0.1)}
    elif rec == 'hold':
        stock_data['analystRatings'] = {'buy': int(num_analysts * 0.3), 'hold': int(num_analysts * 0.5), 'sell': int(num_analysts * 0.2)}
    else:
        stock_data['analystRatings'] = {'buy': int(num_analysts * 0.15), 'hold': int(num_analysts * 0.35), 'sell': int(num_analysts * 0.5)}

    # === EARNINGS DATA ===
    print("  [3/14] Getting earnings history...")
    try:
        earnings_hist = ticker.earnings_history
        if earnings_hist is not None and not earnings_hist.empty:
            surprises = []
            for _, row in earnings_hist.tail(4).iterrows():
                est = row.get('epsEstimate') or row.get('epsactual', 0)
                actual = row.get('epsActual') or row.get('epsactual', 0)
                if est and est != 0:
                    pct = round(((actual - est) / abs(est)) * 100, 1)
                else:
                    pct = 0
                q_date = row.name if hasattr(row, 'name') else ''
                surprises.append({'q': str(q_date)[:7], 'est': round(est, 2), 'actual': round(actual, 2), 'pct': pct})
            stock_data['surprises'] = surprises[-4:] if surprises else get_default_surprises()
        else:
            stock_data['surprises'] = get_default_surprises()
    except:
        # Fallback: try quarterly earnings
        try:
            qe = ticker.quarterly_earnings
            if qe is not None and not qe.empty:
                surprises = []
                for idx, row in qe.tail(4).iterrows():
                    rev = row.get('Revenue', 0)
                    earn = row.get('Earnings', 0)
                    surprises.append({
                        'q': str(idx),
                        'est': round(earn * 0.95 / 1e6, 2) if earn else 0,
                        'actual': round(earn / 1e6, 2) if earn else 0,
                        'pct': 5.0
                    })
                stock_data['surprises'] = surprises if surprises else get_default_surprises()
            else:
                stock_data['surprises'] = get_default_surprises()
        except:
            stock_data['surprises'] = get_default_surprises()

    # === EARNINGS DATE ===
    print("  [4/14] Getting next earnings date...")
    earn_date = None
    try:
        cal = ticker.calendar
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get('Earnings Date', None)
                if ed is None:
                    # Try alternate keys
                    for key in cal:
                        if 'earning' in str(key).lower() or 'date' in str(key).lower():
                            ed = cal[key]
                            break
                if isinstance(ed, list) and len(ed) > 0:
                    ed = ed[0]
                if ed is not None:
                    # Convert whatever type it is to a Python datetime
                    if hasattr(ed, 'to_pydatetime'):
                        earn_date = ed.to_pydatetime()
                    elif hasattr(ed, 'strftime'):
                        earn_date = ed
                    elif isinstance(ed, str):
                        try:
                            earn_date = datetime.strptime(ed, '%Y-%m-%d')
                        except:
                            earn_date = None
            elif hasattr(cal, 'columns'):
                # It's a DataFrame
                try:
                    if 'Earnings Date' in cal.columns:
                        ed = cal['Earnings Date'].iloc[0]
                    elif len(cal.columns) > 0:
                        ed = cal.iloc[0, 0]
                    else:
                        ed = None
                    if ed is not None and hasattr(ed, 'to_pydatetime'):
                        earn_date = ed.to_pydatetime()
                    elif ed is not None and hasattr(ed, 'strftime'):
                        earn_date = ed
                except:
                    earn_date = None
    except Exception as e:
        print(f"    (earnings date lookup failed: {e})")
        earn_date = None

    # Fallback if nothing worked
    if earn_date is None:
        earn_date = datetime.now() + timedelta(days=45)

    # Make sure earn_date is naive datetime (no timezone issues)
    if hasattr(earn_date, 'tzinfo') and earn_date.tzinfo is not None:
        earn_date = earn_date.replace(tzinfo=None)

    # Convert date to datetime if needed (yfinance sometimes returns datetime.date)
    if type(earn_date).__name__ == 'date' and not isinstance(earn_date, datetime):
        earn_date = datetime(earn_date.year, earn_date.month, earn_date.day)

    stock_data['earningsDate'] = earn_date.strftime('%b %d, %Y')
    stock_data['daysToEarnings'] = max(0, (earn_date - datetime.now()).days)

    # === LAST YEAR EARNINGS ===
    stock_data['lastYearEarnings'] = {
        'q': stock_data['surprises'][0]['q'] if stock_data['surprises'] else 'N/A',
        'eps': stock_data['surprises'][0]['actual'] if stock_data['surprises'] else 0,
        'revenue': stock_data['mktCap'],
        'reaction': '+/- TBD'
    }

    # === 52-WEEK PRICE HISTORY ===
    print("  [5/14] Getting 52-week price history...")
    try:
        hist = ticker.history(period="1y", interval="1wk")
        if hist is not None and not hist.empty:
            closes = hist['Close'].dropna().tolist()
            # Sample down to ~24 points
            if len(closes) > 24:
                step = len(closes) / 24
                stock_data['prices52w'] = [round(closes[int(i * step)], 2) for i in range(24)]
            else:
                stock_data['prices52w'] = [round(c, 2) for c in closes]
        else:
            stock_data['prices52w'] = [price] * 24
    except:
        stock_data['prices52w'] = [price] * 24

    # === 90-DAY RISK RANGE ===
    print("  [6/14] Computing 90-day risk range...")
    try:
        hist90 = ticker.history(period="3mo")
        if hist90 is not None and not hist90.empty:
            stock_data['risk90d'] = {
                'best': round(hist90['High'].max(), 2),
                'worst': round(hist90['Low'].min(), 2),
            }
        else:
            stock_data['risk90d'] = {'best': round(price * 1.2, 2), 'worst': round(price * 0.8, 2)}
    except:
        stock_data['risk90d'] = {'best': round(price * 1.2, 2), 'worst': round(price * 0.8, 2)}

    # === PEER COMPANIES ===
    print("  [7/14] Getting sector peers...")
    try:
        # Use recommendations or manually map common peers
        peers = get_sector_peers(info.get('sector', ''), info.get('industry', ''), ticker_symbol.upper())
        peer_data = []
        for p_ticker in peers[:4]:
            try:
                p = yf.Ticker(p_ticker)
                p_info = p.info
                p_price = p_info.get('currentPrice') or p_info.get('regularMarketPrice') or p_info.get('previousClose', 0)
                p_pe = p_info.get('trailingPE') or -1
                rec_key = p_info.get('recommendationKey', 'hold')
                rating = 'Buy' if rec_key in ['strong_buy', 'buy'] else ('Sell' if rec_key in ['sell', 'strong_sell'] else 'Hold')
                target = p_info.get('targetMeanPrice') or p_price
                # 30-day change
                try:
                    p_hist = p.history(period="1mo")
                    if p_hist is not None and len(p_hist) >= 2:
                        chg = round(((p_hist['Close'].iloc[-1] / p_hist['Close'].iloc[0]) - 1) * 100, 1)
                    else:
                        chg = 0
                except:
                    chg = 0

                peer_data.append({
                    'ticker': p_ticker,
                    'name': p_info.get('shortName', p_ticker),
                    'price': round(p_price, 2),
                    'pe': round(p_pe, 1) if p_pe and p_pe > 0 else -1,
                    'rating': rating,
                    'target': round(target, 2),
                    'chg': chg,
                })
            except:
                continue
        stock_data['peers'] = peer_data if peer_data else [{'ticker': 'N/A', 'name': 'No peers found', 'price': 0, 'pe': 0, 'rating': 'Hold', 'target': 0, 'chg': 0}]
    except:
        stock_data['peers'] = [{'ticker': 'N/A', 'name': 'No peers found', 'price': 0, 'pe': 0, 'rating': 'Hold', 'target': 0, 'chg': 0}]

    # === DESCRIPTION & SENTIMENT ===
    print("  [8/14] Building sentiment analysis...")
    stock_data['description'] = info.get('longBusinessSummary', 'No description available.')[:500]

    # Simple sentiment heuristics
    pe = stock_data['pe']
    fwd_pe = stock_data['fwdPe']
    if pe > 0 and pe < 15:
        value = 'Undervalued'
    elif pe > 0 and pe < 30:
        value = 'Fair Value'
    elif pe > 50 or pe < 0:
        value = 'Overvalued' if pe > 50 else 'Speculative'
    else:
        value = 'Fair Value'

    profit_margin = info.get('profitMargins') or 0
    quality = 'High Quality' if profit_margin > 0.15 else ('Mixed' if profit_margin > 0.05 else 'Low')

    debt_equity = info.get('debtToEquity') or 0
    current_ratio = info.get('currentRatio') or 1
    if current_ratio > 1.5 and debt_equity < 100:
        financials = 'Strong'
    elif current_ratio > 1 or debt_equity < 200:
        financials = 'Adequate'
    else:
        financials = 'Weak'

    stock_data['sentiment'] = {'value': value, 'quality': quality, 'financials': financials}
    stock_data['peerMismatch'] = f"Review {ticker_symbol.upper()} vs peers on Finviz and Fidelity research. Compare P/E, margins, and growth rates to identify why this stock may trade at a premium or discount."

    # === OPTIONS PLACEHOLDER ===
    # (Pull real options from Fidelity — this generates reasonable placeholder strikes)
    print("  [*] Generating options strike grid (use Fidelity for real premiums)...")
    atm = round(price)
    step = max(0.5, round(price * 0.03, 1))  # ~3% increments
    if price < 5:
        step = 0.5
    elif price < 20:
        step = 1
    elif price < 50:
        step = 2.5
    else:
        step = 5

    strikes = [round(atm - 4*step + i*step, 1) for i in range(9)]
    strikes = [s for s in strikes if s > 0]

    # Rough Black-Scholes-ish estimate for placeholder premiums
    iv = info.get('impliedVolatility') or 0.4
    days_exp = stock_data['daysToEarnings'] + 14  # expiry ~2 weeks after earnings
    calls = []
    puts = []
    for s in strikes:
        moneyness = (price - s) / price
        time_val = price * iv * (days_exp / 365) ** 0.5 * 0.4
        intrinsic_call = max(0, price - s)
        intrinsic_put = max(0, s - price)
        call_price = round(max(0.01, intrinsic_call + time_val * max(0.1, 1 - moneyness * 3)), 2)
        put_price = round(max(0.01, intrinsic_put + time_val * max(0.1, 1 + moneyness * 3)), 2)
        calls.append(call_price)
        puts.append(put_price)

    stock_data['options'] = {
        'strikes': strikes,
        'calls': calls,
        'puts': puts,
        'expiry': (datetime.now() + timedelta(days=days_exp)).strftime('%b %d, %Y') + ' (est.)',
    }

    # === NEW: RECENT NEWS HEADLINES ===
    print("  [*] Getting recent news headlines...")
    try:
        news_items = ticker.news
        if news_items:
            stock_data['news'] = []
            for n in news_items[:6]:
                title = n.get('title', '')
                publisher = n.get('publisher', '')
                link = n.get('link', '')
                pub_time = n.get('providerPublishTime', 0)
                if pub_time:
                    try:
                        age_days = (datetime.now() - datetime.fromtimestamp(pub_time)).days
                        age_str = f"{age_days}d ago" if age_days > 0 else "Today"
                    except:
                        age_str = ""
                else:
                    age_str = ""
                if title:
                    stock_data['news'].append({
                        'title': title[:120],
                        'publisher': publisher,
                        'link': link,
                        'age': age_str,
                    })
        else:
            stock_data['news'] = []
    except:
        stock_data['news'] = []

    # === NEW: INSIDER TRANSACTIONS ===
    print("  [*] Getting insider transactions...")
    try:
        insiders = ticker.insider_transactions
        if insiders is not None and not insiders.empty:
            recent = insiders.head(10)
            buys = 0
            sells = 0
            buy_value = 0
            sell_value = 0
            insider_list = []
            for _, row in recent.iterrows():
                txn_type = str(row.get('Text', '') or row.get('Transaction', '')).lower()
                shares = abs(row.get('Shares', 0) or 0)
                value = abs(row.get('Value', 0) or 0)
                insider_name = row.get('Insider', '') or row.get('insiderName', '')
                
                if any(w in txn_type for w in ['purchase', 'buy', 'acquisition']):
                    buys += 1
                    buy_value += value
                    insider_list.append({
                        'name': str(insider_name)[:30],
                        'type': 'Buy',
                        'shares': int(shares),
                        'value': round(value, 0),
                    })
                elif any(w in txn_type for w in ['sale', 'sell', 'disposition']):
                    sells += 1
                    sell_value += value
                    insider_list.append({
                        'name': str(insider_name)[:30],
                        'type': 'Sell',
                        'shares': int(shares),
                        'value': round(value, 0),
                    })
            
            stock_data['insiderActivity'] = {
                'buys': buys,
                'sells': sells,
                'buyValue': format_large_number(buy_value),
                'sellValue': format_large_number(sell_value),
                'netSignal': 'Bullish' if buys > sells else ('Bearish' if sells > buys else 'Neutral'),
                'recent': insider_list[:5],
            }
        else:
            stock_data['insiderActivity'] = {'buys': 0, 'sells': 0, 'buyValue': '0', 'sellValue': '0', 'netSignal': 'No Data', 'recent': []}
    except:
        stock_data['insiderActivity'] = {'buys': 0, 'sells': 0, 'buyValue': '0', 'sellValue': '0', 'netSignal': 'No Data', 'recent': []}

    # === NEW: ANALYST UPGRADES / DOWNGRADES ===
    print("  [*] Getting analyst upgrades/downgrades...")
    try:
        upgrades = ticker.upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            recent_90d = upgrades.tail(10)
            upgrade_list = []
            up_count = 0
            down_count = 0
            for idx, row in recent_90d.iterrows():
                firm = row.get('Firm', '') or row.get('firm', '')
                to_grade = row.get('ToGrade', '') or row.get('toGrade', '')
                from_grade = row.get('FromGrade', '') or row.get('fromGrade', '')
                action = row.get('Action', '') or row.get('action', '')
                
                action_str = str(action).lower()
                if 'up' in action_str or 'init' in action_str:
                    up_count += 1
                elif 'down' in action_str:
                    down_count += 1
                
                date_str = ''
                if hasattr(idx, 'strftime'):
                    date_str = idx.strftime('%b %d')
                elif hasattr(idx, 'to_pydatetime'):
                    date_str = idx.to_pydatetime().strftime('%b %d')
                
                upgrade_list.append({
                    'firm': str(firm)[:25],
                    'action': str(action),
                    'toGrade': str(to_grade),
                    'fromGrade': str(from_grade),
                    'date': date_str,
                })
            
            stock_data['analystActions'] = {
                'upgrades': up_count,
                'downgrades': down_count,
                'netSignal': 'Bullish' if up_count > down_count else ('Bearish' if down_count > up_count else 'Neutral'),
                'recent': upgrade_list[-6:],
            }
        else:
            stock_data['analystActions'] = {'upgrades': 0, 'downgrades': 0, 'netSignal': 'No Data', 'recent': []}
    except:
        stock_data['analystActions'] = {'upgrades': 0, 'downgrades': 0, 'netSignal': 'No Data', 'recent': []}

    # === NEW: PRICE MOMENTUM (5d, 30d, 90d returns) ===
    print("  [*] Computing price momentum...")
    try:
        hist_6m = ticker.history(period="6mo")
        if hist_6m is not None and not hist_6m.empty:
            # dropna: yfinance appends a NaN row for the current partial
            # session — without this the latest "close" is NaN and every
            # momentum value silently becomes None.
            closes = hist_6m['Close'].dropna()
            current = closes.iloc[-1]
            
            def pct_change(n_days):
                # None (not 0) when there isn't enough history — a missing
                # value must render as "n/a" and stay out of the score.
                # Returning 0 here is what used to let null momentum be
                # scored and displayed as if it were measured ("Mixed").
                if len(closes) > n_days:
                    ref = closes.iloc[-n_days]
                    if ref and current == current and ref == ref:
                        return round(((current / ref) - 1) * 100, 1)
                return None

            d5, d30, d90 = pct_change(5), pct_change(21), pct_change(63)
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

    # === NEW: REVENUE GROWTH ===
    print("  [*] Getting revenue growth...")
    try:
        rev_growth = info.get('revenueGrowth', None)
        earnings_growth = info.get('earningsGrowth', None)
        qtr_rev_growth = info.get('quarterlyRevenueGrowth', None)
        qtr_earn_growth = info.get('quarterlyEarningsGrowth', None)
        
        stock_data['growthMetrics'] = {
            'revenueGrowth': round(rev_growth * 100, 1) if rev_growth else None,
            'earningsGrowth': round(earnings_growth * 100, 1) if earnings_growth else None,
            'qtrRevenueGrowth': round(qtr_rev_growth * 100, 1) if qtr_rev_growth else None,
            'qtrEarningsGrowth': round(qtr_earn_growth * 100, 1) if qtr_earn_growth else None,
            'signal': 'Strong' if (rev_growth and rev_growth > 0.15) else (
                'Growing' if (rev_growth and rev_growth > 0) else (
                    'Declining' if (rev_growth and rev_growth < 0) else 'Unknown'
                )
            ),
        }
    except:
        stock_data['growthMetrics'] = {'revenueGrowth': None, 'earningsGrowth': None, 'qtrRevenueGrowth': None, 'qtrEarningsGrowth': None, 'signal': 'Unknown'}

    # === NEW: IMPLIED VOLATILITY & EXPECTED MOVE ===
    print("  [*] Computing implied volatility & expected move...")
    try:
        iv_val = info.get('impliedVolatility') or None
        # Also try to get from options chain
        if iv_val is None:
            try:
                opts = ticker.options
                if opts and len(opts) > 0:
                    chain = ticker.option_chain(opts[0])
                    if chain and hasattr(chain, 'calls') and not chain.calls.empty:
                        # ATM IV approximation from nearest-the-money call
                        atm_mask = (chain.calls['strike'] - price).abs()
                        nearest_idx = atm_mask.idxmin()
                        iv_val = chain.calls.loc[nearest_idx, 'impliedVolatility']
            except:
                pass
        
        if iv_val and iv_val > 0:
            # Expected move = price * IV * sqrt(days/365)
            days_to_earn = stock_data['daysToEarnings'] or 30
            expected_move_pct = round(iv_val * (days_to_earn / 365) ** 0.5 * 100, 1)
            expected_move_dollar = round(price * iv_val * (days_to_earn / 365) ** 0.5, 2)
            
            stock_data['impliedVolatility'] = {
                'iv': round(iv_val * 100, 1),
                'expectedMovePct': expected_move_pct,
                'expectedMoveDollar': expected_move_dollar,
                'signal': 'High IV' if iv_val > 0.6 else ('Moderate IV' if iv_val > 0.3 else 'Low IV'),
            }
        else:
            stock_data['impliedVolatility'] = {'iv': None, 'expectedMovePct': None, 'expectedMoveDollar': None, 'signal': 'Unknown'}
    except:
        stock_data['impliedVolatility'] = {'iv': None, 'expectedMovePct': None, 'expectedMoveDollar': None, 'signal': 'Unknown'}

    # === NEW: ADDITIONAL FUNDAMENTALS (profit margin, debt/equity, float, ex-div, estimate revisions) ===
    print("  [*] Getting additional fundamentals...")
    stock_data['fundamentalsExtra'] = {
        'profitMargin': round((info.get('profitMargins') or 0) * 100, 1),
        'grossMargin': round((info.get('grossMargins') or 0) * 100, 1),
        'operatingMargin': round((info.get('operatingMargins') or 0) * 100, 1),
        'debtToEquity': round(info.get('debtToEquity') or 0, 1),
        'currentRatio': round(info.get('currentRatio') or 0, 2),
        'floatShares': format_large_number(info.get('floatShares') or 0),
        'sharesOutstanding': format_large_number(info.get('sharesOutstanding') or 0),
        'exDivDate': str(info.get('exDividendDate', 'N/A')),
        'earningsEstRevision': round(((info.get('forwardEps') or 0) / (info.get('trailingEps') or 1) - 1) * 100, 1) if info.get('trailingEps') and info.get('trailingEps') != 0 else 0,
    }

    # === NEW: REALIZED EARNINGS MOVE vs IMPLIED ===
    print("  [*] Computing realized earnings-day moves...")
    realized = compute_earnings_move(ticker)
    iv_block = stock_data.get('impliedVolatility') or {}
    implied_pct = iv_block.get('expectedMovePct')
    stock_data['earningsMove'] = {
        'avgAbsMovePct': realized['avgAbsMovePct'] if realized else None,
        'count': realized['count'] if realized else 0,
        'moves': realized['moves'] if realized else [],
        'impliedMovePct': implied_pct,
        'edgeRatio': round(implied_pct / realized['avgAbsMovePct'], 2) if (realized and implied_pct) else None,
    }

    # === NEW: GUIDANCE FLAG ===
    # No reliable free structured source exists — 'unknown', never guessed.
    stock_data['guidance'] = detect_guidance(ticker)

    # === NEW: COVERED-CALL DIVIDEND FLAGS (ex-div / early assignment) ===
    stock_data['dividendFlags'] = covered_call_flags(info, stock_data['daysToEarnings'])

    # === UNIFIED SCORE (single source of truth — scoring.py) ===
    print("  [*] Computing unified score...")
    iv_pct = iv_block.get('iv')
    facts = {
        'price': stock_data['price'],
        'pe': stock_data['pe'],
        'wk52High': stock_data['wk52High'],
        'shortRatio': stock_data['shortRatio'],
        'shortPct': round((info.get('shortPercentOfFloat') or 0) * 100, 1),
        'daysToEarnings': stock_data['daysToEarnings'],
        'surprises': stock_data['surprises'],
        'impliedMovePct': implied_pct,
        'realizedMovePct': stock_data['earningsMove']['avgAbsMovePct'],
        'ivPct': iv_pct,
        'sentiment': stock_data['sentiment'],
        'momentum': stock_data['momentum'],
        'revenueGrowth': stock_data['growthMetrics'].get('revenueGrowth'),
        'insiderSignal': stock_data['insiderActivity'].get('netSignal'),
        'analystSignal': stock_data['analystActions'].get('netSignal'),
    }
    stock_data['score'] = compute_score(facts)

    # === SQUEEZE SCORE (second, independent score — scoring.py) ===
    # Same record, opposite lens: crowded shorts + a dated catalyst.
    # siTrend is None on purpose: yfinance reports only the CURRENT
    # short interest, so there is no prior report to compare against
    # — the trend component stays honestly unmeasured (n/a) rather
    # than being guessed.
    print("  [*] Computing squeeze score...")
    stock_data['squeezeScore'] = compute_squeeze_score({
        'shortPct': facts['shortPct'],
        'shortRatio': stock_data['shortRatio'],
        'daysToEarnings': stock_data['daysToEarnings'],
        'siTrend': None,
        'realizedMovePct': stock_data['earningsMove']['avgAbsMovePct'],
        'avgVol': info.get('averageVolume'),
    })

    print(f"\n  ✓ {ticker_symbol.upper()} — ${stock_data['price']} — Done!")
    return stock_data


def get_default_surprises():
    return [
        {'q': 'Q4', 'est': 0, 'actual': 0, 'pct': 0},
        {'q': 'Q3', 'est': 0, 'actual': 0, 'pct': 0},
        {'q': 'Q2', 'est': 0, 'actual': 0, 'pct': 0},
        {'q': 'Q1', 'est': 0, 'actual': 0, 'pct': 0},
    ]


def get_sector_peers(sector, industry, exclude_ticker):
    """Return a list of peer tickers for common sectors."""
    peer_map = {
        'Technology': ['AAPL', 'MSFT', 'GOOGL', 'META', 'CRM', 'ORCL', 'ADBE', 'NOW'],
        'Information Technology': ['AAPL', 'MSFT', 'GOOGL', 'CRM', 'ORCL', 'ADBE', 'NOW', 'PLTR'],
        'Financial Services': ['JPM', 'BAC', 'GS', 'MS', 'C', 'WFC', 'SCHW', 'SOFI'],
        'Financials': ['JPM', 'BAC', 'GS', 'SOFI', 'HOOD', 'LC', 'UPST', 'NU'],
        'Healthcare': ['JNJ', 'UNH', 'PFE', 'ABBV', 'MRK', 'LLY', 'TDOC', 'HIMS'],
        'Consumer Discretionary': ['AMZN', 'TSLA', 'HD', 'NKE', 'SBUX', 'F', 'GM', 'RIVN'],
        'Consumer Cyclical': ['AMZN', 'TSLA', 'HD', 'NKE', 'F', 'GM', 'RIVN', 'LI'],
        'Communication Services': ['GOOGL', 'META', 'DIS', 'NFLX', 'T', 'VZ', 'TMUS'],
        'Industrials': ['CAT', 'BA', 'HON', 'UPS', 'GE', 'RTX', 'LMT', 'DE'],
        'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'VLO'],
        'Real Estate': ['AMT', 'PLD', 'CCI', 'EQIX', 'SPG', 'O', 'VICI', 'DLR'],
        'Utilities': ['NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'SRE', 'XEL'],
        'Basic Materials': ['LIN', 'APD', 'ECL', 'SHW', 'NEM', 'FCX', 'NUE', 'DOW'],
        'Consumer Staples': ['PG', 'KO', 'PEP', 'WMT', 'COST', 'CL', 'MO', 'PM'],
    }

    # Try industry-specific first, then sector
    candidates = peer_map.get(sector, peer_map.get(industry, ['SPY', 'QQQ', 'IWM', 'DIA']))
    return [t for t in candidates if t != exclude_ticker][:5]


def format_large_number(n):
    """Format large numbers like 39200000000 → '39.2B'."""
    if not n or n == 0:
        return '0'
    abs_n = abs(n)
    if abs_n >= 1e12:
        return f"{n/1e12:.1f}T"
    elif abs_n >= 1e9:
        return f"{n/1e9:.1f}B"
    elif abs_n >= 1e6:
        return f"{n/1e6:.1f}M"
    elif abs_n >= 1e3:
        return f"{n/1e3:.1f}K"
    return str(round(n))


def main():
    parser = argparse.ArgumentParser(
        description='Fetch stock data for the Earnings Play Analyzer dashboard.',
        epilog='Example: python fetch_stock.py SOFI F HIMS'
    )
    parser.add_argument('tickers', nargs='+', help='One or more stock ticker symbols')
    parser.add_argument('--output', '-o', default='.', help='Output directory for stock_data.json (default: current dir)')

    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════╗
║     EARNINGS PLAY ANALYZER — Data Fetcher        ║
║     Pulling live data from Yahoo Finance         ║
╚══════════════════════════════════════════════════╝
    """)

    all_data = {}
    failed = []

    # Load existing data so we can MERGE (not overwrite)
    output_path = os.path.join(args.output, 'stock_data.json')
    if os.path.exists(output_path):
        try:
            with open(output_path, 'r') as f:
                all_data = json.load(f)
            print(f"  ► Loaded existing data: {', '.join(all_data.keys())}")
            print(f"  ► New/updated tickers will be merged in\n")
        except:
            all_data = {}

    for t in args.tickers:
        ticker = t.upper().strip()
        data = fetch_stock_data(ticker)
        if data:
            all_data[ticker] = data
        else:
            failed.append(ticker)

    if not all_data:
        print("\n✗ No data fetched. Check your ticker symbols and internet connection.")
        sys.exit(1)

    # Save JSON
    # NaN/Infinity are not valid JSON (RFC 8259) — Python's json module
    # happily writes them as bare `NaN`/`Infinity` tokens anyway, which
    # a browser's strict JSON.parse() then rejects outright (seen in the
    # wild as Safari throwing "SyntaxError: The string did not match the
    # expected pattern" on stock_data.json, while direct navigation and
    # Python's own json.loads() both silently accepted the same file).
    # Sanitize them to null before writing, and keep allow_nan=False as
    # a hard guard so any future NaN that slips past this is a loud
    # failure here instead of a silent bad file on the live site.
    def sanitize_json(obj):
        if isinstance(obj, float):
            return None if (obj != obj or obj in (float('inf'), float('-inf'))) else obj
        if isinstance(obj, dict):
            return {k: sanitize_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize_json(v) for v in obj]
        return obj

    output_path = os.path.join(args.output, 'stock_data.json')
    with open(output_path, 'w') as f:
        json.dump(sanitize_json(all_data), f, indent=2, default=str, allow_nan=False)

    print(f"\n{'='*50}")
    print(f"  ✓ SUCCESS — Saved to: {os.path.abspath(output_path)}")
    print(f"  ✓ Tickers: {', '.join(all_data.keys())}")
    if failed:
        print(f"  ✗ Failed: {', '.join(failed)}")
    print(f"{'='*50}")
    print(f"\n  NEXT STEPS:")
    print(f"  1. Place stock_data.json in the SAME FOLDER as earnings-analyzer.html")
    print(f"  2. Open earnings-analyzer.html in your browser")
    print(f"  3. Type any ticker you fetched and click Analyze")
    print(f"  4. Use the Fidelity links for real-time options chain data")
    print(f"\n  To add more tickers later, just run:")
    print(f"    python fetch_stock.py AAPL MSFT TSLA")
    print()


if __name__ == '__main__':
    main()
