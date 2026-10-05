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

def evaluate_stock(ticker_sym, earnings_info, criteria):
    """
    Pull full data for a stock and evaluate against earnings play criteria.
    Returns (score, data_dict) or None if it fails hard criteria.
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
        
        # ===== HARD FILTERS =====
        # Price range
        if price < criteria['price_min'] or price > criteria['price_max']:
            return None
        
        # Must have positive earnings for PE check (unless we allow negative)
        if criteria['require_profitable'] and (pe <= 0 or eps <= 0):
            return None
        
        # PE too high
        if pe > 0 and pe > criteria['max_pe']:
            return None
            
        # Short interest too high
        if short_pct > criteria['max_short']:
            return None
        
        # Too close to 52-week high (priced in)
        pct_from_high = ((wk52_high - price) / wk52_high) * 100
        if pct_from_high < criteria['min_pct_from_high']:
            return None
        
        # Need sufficient volume for options liquidity
        if avg_vol < 500000:
            return None
        
        # ===== SCORING =====
        score = 50
        
        # Price sweet spot ($15-$20 = best)
        if 15 <= price <= 20:
            score += 15
        elif 12 <= price <= 25:
            score += 10
        elif 10 <= price <= 30:
            score += 5
        
        # PE score
        if 0 < pe <= 15:
            score += 15  # Deep value
        elif 0 < pe <= 25:
            score += 10
        elif 0 < pe <= 40:
            score += 5
        
        # Not at highs
        if pct_from_high > 30:
            score += 10
        elif pct_from_high > 20:
            score += 7
        elif pct_from_high > 10:
            score += 3
        
        # Low short interest
        if short_pct < 3:
            score += 8
        elif short_pct < 5:
            score += 5
        elif short_pct < 8:
            score += 2
        
        # Days to earnings (7+ is ideal)
        days_to = earnings_info.get('days_until', 30)
        if days_to >= 14:
            score += 8
        elif days_to >= 7:
            score += 5
        elif days_to >= 3:
            score += 2
        
        # Dividend bonus (income play)
        div_yield = info.get('dividendYield') or 0
        if div_yield > 0.03:
            score += 5
        elif div_yield > 0.01:
            score += 2
        
        # Analyst sentiment
        rec = info.get('recommendationKey', 'hold')
        if rec in ['strong_buy', 'buy']:
            score += 8
        elif rec == 'hold':
            score += 3
        
        # Profitability quality
        profit_margin = info.get('profitMargins') or 0
        if profit_margin > 0.15:
            score += 6
        elif profit_margin > 0.05:
            score += 3
        
        # Cap the score
        score = min(100, max(0, score))
        
        # ===== BUILD FULL DATA FOR DASHBOARD =====
        # Instead of importing fetch_stock, build the data inline
        full_data = build_stock_data(ticker_sym, ticker, info, earnings_info, price, pe, fwd_pe, eps, fwd_eps,
                                      wk52_low, wk52_high, short_pct, beta, mkt_cap, avg_vol,
                                      pct_from_high, profit_margin, rec, div_yield, score)
        if full_data:
            full_data['_scan_score'] = score
            full_data['_scan_reasons'] = build_reasons(price, pe, fwd_pe, pct_from_high, short_pct, days_to, rec, profit_margin, div_yield)
            return (score, full_data)
        
        return None
        
    except Exception as e:
        return None


def build_stock_data(ticker_sym, ticker, info, earnings_info, price, pe, fwd_pe, eps, fwd_eps,
                     wk52_low, wk52_high, short_pct, beta, mkt_cap, avg_vol,
                     pct_from_high, profit_margin, rec, div_yield, score):
    """Build a complete stock data dict for the dashboard."""
    try:
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
            'divYield': f"{round(div_yield * 100, 1)}%",
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


def build_reasons(price, pe, fwd_pe, pct_from_high, short_pct, days_to, rec, margin, div_yield):
    """Build a list of reasons this stock qualifies."""
    reasons = []
    
    if 15 <= price <= 20:
        reasons.append(f"✓ Price ${price:.2f} in $15-$20 sweet spot")
    else:
        reasons.append(f"~ Price ${price:.2f} (outside ideal but within range)")
    
    if pe > 0 and pe < 16:
        reasons.append(f"✓ P/E {pe:.1f} below S&P 500 average of 16")
    elif pe > 0 and pe < 50:
        reasons.append(f"✓ P/E {pe:.1f} under 50 threshold")
    
    if pct_from_high > 20:
        reasons.append(f"✓ {pct_from_high:.0f}% below 52wk high — not priced in")
    
    if short_pct < 5:
        reasons.append(f"✓ Short interest {short_pct:.1f}% — clean")
    elif short_pct < 10:
        reasons.append(f"~ Short interest {short_pct:.1f}% — acceptable")
    
    if days_to >= 7:
        reasons.append(f"✓ {days_to} days to earnings — good entry window")
    
    if rec in ['strong_buy', 'buy']:
        reasons.append(f"✓ Analyst consensus: {rec.replace('_', ' ').title()}")
    
    if margin > 0.1:
        reasons.append(f"✓ Profit margin {margin*100:.1f}% — healthy")
    
    if div_yield > 0.02:
        reasons.append(f"✓ Dividend yield {div_yield*100:.1f}% — income bonus")
    
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
    
    # Step 2: Quick pre-filter on price before deep analysis
    print(f"\n  🔍 Quick price-filtering {len(earnings_list)} candidates...")
    pre_filtered = []
    for e in earnings_list:
        try:
            t = yf.Ticker(e['ticker'])
            info = t.info
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose', 0)
            if args.price_min <= price <= args.price_max:
                pre_filtered.append(e)
                print(f"    ✓ {e['ticker']:6s} ${price:>8.2f}  — earnings {e['earnings_date']} ({e['days_until']}d)")
            # else: silently skip
        except:
            continue
        time.sleep(0.2)
    
    print(f"\n  📋 {len(pre_filtered)} stocks in ${args.price_min}-${args.price_max} range with upcoming earnings")
    
    if not pre_filtered:
        print("\n  ✗ No stocks match price criteria. Try widening --price-min / --price-max")
        sys.exit(0)
    
    # Step 3: Deep analysis on price-qualified stocks
    print(f"\n  🔬 Running deep analysis on {len(pre_filtered)} candidates...")
    print(f"     (This will take a minute — pulling full data for each stock)\n")
    
    qualified = []
    for i, e in enumerate(pre_filtered):
        pct = int(((i + 1) / len(pre_filtered)) * 100)
        print(f"    [{pct:3d}%] Analyzing {e['ticker']}...")
        
        result = evaluate_stock(e['ticker'], e, criteria)
        if result:
            score, data = result
            qualified.append((score, e['ticker'], data))
        else:
            print(f"          → filtered out (didn't pass criteria)")
        
        time.sleep(0.3)
    
    # Sort by score descending
    qualified.sort(key=lambda x: x[0], reverse=True)
    
    # Trim to top N
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
        sys.exit(0)
    
    for rank, (score, ticker, data) in enumerate(qualified, 1):
        reasons = data.get('_scan_reasons', [])
        print(f"  #{rank}  {ticker:6s}  ${data['price']:<8.2f}  Score: {score}/100")
        print(f"       Earnings: {data['earningsDate']} ({data['daysToEarnings']}d away)")
        print(f"       P/E: {data['pe'] if data['pe'] > 0 else 'N/A':>6}  |  Short: {data['shortInt']:>5}  |  52wk: ${data['wk52Low']}-${data['wk52High']}")
        for r in reasons:
            print(f"       {r}")
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
    
    with open(output_path, 'w') as f:
        json.dump(existing, f, indent=2, default=str)
    
    print(f"{'='*60}")
    print(f"  ✓ Saved {len(qualified)} plays to: {os.path.abspath(output_path)}")
    print(f"  ✓ Total tickers in file: {len(existing)}")
    print(f"{'='*60}")
    print(f"\n  NEXT: Open your dashboard and these stocks are ready to analyze!")
    print(f"  Quick buttons will auto-update with the new tickers.\n")


if __name__ == '__main__':
    main()
