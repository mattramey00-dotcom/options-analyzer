#!/usr/bin/env python3
"""
=============================================================
  EARNINGS PLAY ANALYZER — Unified Scoring (single source)
=============================================================
  ONE scoring implementation for the whole app.

  History: the score used to be computed in THREE places with
  three different formulas — scan_earnings.py (base-50 + bonuses
  capped at 100), index.html computeScore(), and index.html
  computeQuickScore() — so the grid, the ticker bar and the
  analysis view routinely showed different numbers for the same
  stock (e.g. RF 79 on the card vs 74 in the analysis).

  Now: this module computes the score ONCE in Python, ships it
  in stock_data.json as `score`, and the page only renders it.

  Design rules:
  * Components sum to EXACTLY 100 max — no base-50-plus-cap
    compression, so the top of the board can actually rank.
  * Missing data is NEVER scored as neutral. An unavailable
    component is excluded and the total is rescaled over the
    components that were measurable, flagged `partial: true`
    with a note naming what was missing.
  * Short interest is gated primarily on days-to-cover (DTC /
    shortRatio — how fast shorts can exit), with SI % of float
    kept as context. A high SI% with a low DTC (e.g. AAL: 13.9%
    but 1.5 days) is fast-cover fuel, not slow borrow stress.
  * Premium selling is scored on implied vs realized earnings
    move: if the options market prices a bigger move than the
    stock has actually averaged on earnings, the premium seller
    is being paid more than history says the move costs.

  Used by: fetch_stock.py, scan_earnings.py
=============================================================
"""

from datetime import datetime, timedelta

SCORE_VERSION = 2

# (key, label, max points) — max points sum to exactly 100.
COMPONENTS = [
    ('price',      'Price band ($15–20 sweet spot)', 12),
    ('pe',         'P/E valuation',                  12),
    ('position',   '52-week position',               10),
    ('short',      'Short borrow (days to cover)',   12),
    ('timing',     'Days to earnings',                8),
    ('surprises',  'Earnings surprise track record', 10),
    ('premium',    'Premium edge (implied vs realized move)', 12),
    ('quality',    'Quality & sentiment',            10),
    ('momentum',   'Price momentum',                  6),
    ('growth',     'Revenue growth',                  4),
    ('flow',       'Insider & analyst flow',          4),
]
assert sum(m for _, _, m in COMPONENTS) == 100


def _c(key, label, max_pts, points, detail):
    """One scored component. points=None means 'not measurable'."""
    return {
        'key': key,
        'label': label,
        'max': max_pts,
        'points': points,
        'detail': detail,
        'available': points is not None,
    }


def _num(x):
    """True for a real, usable number (not None / NaN / bool)."""
    return isinstance(x, (int, float)) and x == x and not isinstance(x, bool)


# ============ INDIVIDUAL COMPONENTS ============

def _score_price(price):
    label, mx = 'Price band ($15–20 sweet spot)', 12
    if not _num(price) or price <= 0:
        return _c('price', label, mx, None, 'Price unavailable')
    if 15 <= price <= 20:
        pts, note = 12, 'in the $15–20 sweet spot'
    elif 12 <= price <= 25:
        pts, note = 9, 'in the $12–25 workable band'
    elif 10 <= price <= 30:
        pts, note = 6, 'in the $10–30 outer band'
    elif 8 <= price <= 40:
        pts, note = 3, 'outside the preferred band — 100-lot capital is heavy or premium thin'
    else:
        pts, note = 0, 'far outside the $8–40 workable range'
    return _c('price', label, mx, pts, f"${price:.2f} — {note}")


def _score_pe(pe):
    label, mx = 'P/E valuation', 12
    if not _num(pe):
        return _c('pe', label, mx, None, 'P/E unavailable')
    if pe <= 0:
        return _c('pe', label, mx, 0, 'No positive P/E (unprofitable) — no valuation credit')
    if pe <= 15:
        pts = 12
    elif pe <= 25:
        pts = 9
    elif pe <= 40:
        pts = 6
    elif pe <= 50:
        pts = 3
    else:
        pts = 0
    return _c('pe', label, mx, pts, f"P/E {pe:.1f} (threshold < 50, S&P avg ~16)")


def _score_position(price, wk52_high):
    label, mx = '52-week position', 10
    if not _num(price) or not _num(wk52_high) or wk52_high <= 0:
        return _c('position', label, mx, None, '52-week high unavailable')
    pct = (wk52_high - price) / wk52_high * 100
    if pct >= 30:
        pts = 10
    elif pct >= 20:
        pts = 8
    elif pct >= 15:
        pts = 6
    elif pct >= 10:
        pts = 4
    elif pct >= 5:
        pts = 2
    else:
        pts = 0
    return _c('position', label, mx, pts, f"{pct:.1f}% below the 52-week high (${wk52_high:.2f})")


def _score_short(short_ratio, short_pct):
    """Gated primarily on days-to-cover; SI% of float is context."""
    label, mx = 'Short borrow (days to cover)', 12
    dtc = short_ratio if _num(short_ratio) and short_ratio > 0 else None
    si = short_pct if _num(short_pct) else None
    if dtc is not None:
        if dtc <= 1:
            pts = 12
        elif dtc <= 2:
            pts = 10
        elif dtc <= 3:
            pts = 8
        elif dtc <= 5:
            pts = 5
        elif dtc <= 8:
            pts = 2
        else:
            pts = 0
        ctx = f", short interest {si:.1f}% of float" if si is not None else ""
        return _c('short', label, mx, pts,
                  f"{dtc:.1f} days to cover{ctx} — "
                  + ("shorts can exit fast; squeeze pops fade quickly" if dtc <= 2
                     else "moderate cover time" if dtc <= 5
                     else "slow cover — crowded exit, borrow stress"))
    if si is not None:
        # Fallback: SI% only (weaker signal, say so in the detail)
        if si < 3:
            pts = 8
        elif si < 5:
            pts = 6
        elif si < 8:
            pts = 4
        elif si < 10:
            pts = 2
        else:
            pts = 0
        return _c('short', label, mx, pts,
                  f"Days to cover n/a — scored on short interest {si:.1f}% of float (weaker signal)")
    return _c('short', label, mx, None, 'Short interest / days to cover unavailable')


def _score_timing(days):
    label, mx = 'Days to earnings', 8
    if not _num(days):
        return _c('timing', label, mx, None, 'Earnings date unavailable')
    if days >= 14:
        pts = 8
    elif days >= 7:
        pts = 6
    elif days >= 3:
        pts = 3
    else:
        pts = 0
    return _c('timing', label, mx, pts, f"{int(days)} days to earnings (target ≥ 7 for entry)")


def _score_surprises(surprises):
    label, mx = 'Earnings surprise track record', 10
    real = [x for x in (surprises or [])
            if isinstance(x, dict) and _num(x.get('pct'))
            and not (x.get('est') in (0, 0.0, None) and x.get('actual') in (0, 0.0, None))]
    if not real:
        return _c('surprises', label, mx, None, 'No usable surprise history')
    beats = sum(1 for x in real if x['pct'] > 0)
    n = len(real)
    pts = {4: 10, 3: 8, 2: 5, 1: 2, 0: 0}[beats] if n >= 4 else round(10 * beats / n)
    return _c('surprises', label, mx, pts, f"{beats}/{n} beats in recent reported quarters")


def _score_premium(implied_move_pct, realized_move_pct, iv_pct):
    label, mx = 'Premium edge (implied vs realized move)', 12
    if _num(implied_move_pct) and _num(realized_move_pct) and realized_move_pct > 0:
        ratio = implied_move_pct / realized_move_pct
        if ratio >= 1.25:
            pts = 12
        elif ratio >= 1.10:
            pts = 10
        elif ratio >= 1.00:
            pts = 8
        elif ratio >= 0.85:
            pts = 5
        elif ratio >= 0.70:
            pts = 2
        else:
            pts = 0
        return _c('premium', label, mx, pts,
                  f"Implied move ±{implied_move_pct:.1f}% vs realized avg ±{realized_move_pct:.1f}% "
                  f"(ratio {ratio:.2f}×) — "
                  + ("premium overpays vs history" if ratio >= 1.0
                     else "premium underpays vs the stock's actual earnings moves"))
    if _num(iv_pct):
        # IV known but no realized history: partial credit on IV level only.
        if iv_pct >= 50:
            pts = 6
        elif iv_pct >= 35:
            pts = 5
        elif iv_pct >= 25:
            pts = 4
        else:
            pts = 3
        return _c('premium', label, mx, pts,
                  f"IV {iv_pct:.1f}% — realized earnings-move history n/a, partial credit only")
    if _num(implied_move_pct):
        return _c('premium', label, mx, 4,
                  f"Implied move ±{implied_move_pct:.1f}% — realized history n/a, partial credit only")
    return _c('premium', label, mx, None, 'Implied volatility / expected move unavailable')


def _score_quality(sentiment):
    label, mx = 'Quality & sentiment', 10
    s = sentiment or {}
    value, quality, financials = s.get('value'), s.get('quality'), s.get('financials')
    if value is None and quality is None and financials is None:
        return _c('quality', label, mx, None, 'Sentiment labels unavailable')
    pts = 0.0
    pts += {'Undervalued': 4, 'Fair Value': 2, 'Speculative': 1, 'Overvalued': 0}.get(value, 1)
    pts += 3 if (quality and 'High' in str(quality)) else (1.5 if quality == 'Mixed' else 0)
    pts += {'Strong': 3, 'Improving': 3, 'Adequate': 1.5, 'Weak': 0}.get(financials, 1)
    pts = round(min(pts, 10) * 2) / 2
    return _c('quality', label, mx, pts,
              f"Value: {value or 'n/a'} • Quality: {quality or 'n/a'} • Financials: {financials or 'n/a'}")


def _score_momentum(momentum):
    label, mx = 'Price momentum', 6
    m = momentum or {}
    d5, d30 = m.get('day5'), m.get('day30')
    if not _num(d5) or not _num(d30):
        # The old bug: nulls rendered as "Mixed" and scored as if measured.
        return _c('momentum', label, mx, None, 'Momentum n/a — insufficient price history')
    if d5 > 0 and d30 > 0:
        pts = 6
    elif d30 > 0:
        pts = 4
    elif d5 < 0 and d30 < 0:
        pts = 0
    elif d30 < 0:
        pts = 1
    else:
        pts = 3
    return _c('momentum', label, mx, pts,
              f"5d {d5:+.1f}% • 30d {d30:+.1f}% • 90d "
              f"{('%+.1f%%' % m['day90']) if _num(m.get('day90')) else 'n/a'}")


def _score_growth(revenue_growth):
    label, mx = 'Revenue growth', 4
    if not _num(revenue_growth):
        return _c('growth', label, mx, None, 'Revenue growth n/a')
    g = revenue_growth
    if g > 15:
        pts = 4
    elif g > 5:
        pts = 3
    elif g > 0:
        pts = 2
    elif g > -5:
        pts = 1
    else:
        pts = 0
    return _c('growth', label, mx, pts, f"Revenue growth {g:+.1f}%")


def _score_flow(insider_signal, analyst_signal):
    label, mx = 'Insider & analyst flow', 4
    table = {'Bullish': 2, 'Neutral': 1, 'Bearish': 0}
    parts, earned, present_max = [], 0.0, 0
    for name, sig in (('Insiders', insider_signal), ('Analysts', analyst_signal)):
        if sig in table:
            earned += table[sig]
            present_max += 2
            parts.append(f"{name}: {sig}")
    if present_max == 0:
        return _c('flow', label, mx, None, 'Insider / analyst flow: no data')
    pts = round(earned / present_max * mx * 2) / 2
    return _c('flow', label, mx, pts, ' • '.join(parts))


# ============ MAIN ENTRY ============

def compute_score(facts):
    """
    facts: dict with any of —
      price, pe, wk52High, shortRatio (days to cover), shortPct (% of float),
      daysToEarnings, surprises (list), impliedMovePct, realizedMovePct,
      ivPct, sentiment {value, quality, financials}, momentum {day5, day30, day90},
      revenueGrowth, insiderSignal, analystSignal

    Returns:
      {total, grade, partial, partialNote, components: [...], version}
      total is None when nothing at all was measurable.
    """
    comps = [
        _score_price(facts.get('price')),
        _score_pe(facts.get('pe')),
        _score_position(facts.get('price'), facts.get('wk52High')),
        _score_short(facts.get('shortRatio'), facts.get('shortPct')),
        _score_timing(facts.get('daysToEarnings')),
        _score_surprises(facts.get('surprises')),
        _score_premium(facts.get('impliedMovePct'), facts.get('realizedMovePct'), facts.get('ivPct')),
        _score_quality(facts.get('sentiment')),
        _score_momentum(facts.get('momentum')),
        _score_growth(facts.get('revenueGrowth')),
        _score_flow(facts.get('insiderSignal'), facts.get('analystSignal')),
    ]
    earned = sum(c['points'] for c in comps if c['available'])
    avail_max = sum(c['max'] for c in comps if c['available'])
    missing = [c['label'] for c in comps if not c['available']]

    if avail_max == 0:
        total, partial, note = None, True, 'No scoring data available'
    elif missing:
        total = round(100 * earned / avail_max)
        partial = True
        note = ('Partial data — not measured: ' + ', '.join(missing)
                + f'. Score rescaled over the {avail_max} measurable points.')
    else:
        total = round(earned)
        partial = False
        note = ''

    grade = None
    if total is not None:
        grade = 'STRONG' if total >= 75 else ('OKAY' if total >= 50 else 'WEAK')

    return {
        'total': total,
        'grade': grade,
        'partial': partial,
        'partialNote': note,
        'components': comps,
        'version': SCORE_VERSION,
    }


# ============ SQUEEZE SCORE ============
#
# The SECOND, independent score (added 2026-10-09 at Matt's
# request): same records, opposite lens. The earnings score above
# REWARDS calm, cheap, premium-rich names and PENALIZES crowded
# shorts (they distort the covered-call trade). The squeeze score
# rewards exactly what the earnings score avoids — crowded shorts
# (fuel) in front of a dated catalyst (ignition) — and its strategy
# is a married put / call spread, NEVER a covered call (a covered
# call sells away the upside a squeeze exists to capture).
#
# Same rules as the earnings score: components sum to EXACTLY 100,
# missing components are excluded + rescaled + flagged partial,
# and nothing is ever fabricated. One extra rule the earnings
# score doesn't need: a squeeze REQUIRES a dated catalyst within
# ~30 days. Without one the setup is ineligible and the total is
# capped — fuel with no ignition date is just a crowded stock.

SQUEEZE_SCORE_VERSION = 1

# (key, label, max points) — max points sum to exactly 100.
SQUEEZE_COMPONENTS = [
    ('fuel',      'Fuel load (short interest % of float)',   40),
    ('catalyst',  'Catalyst (dated earnings event ≤ ~30d)', 15),
    ('burn',      'Burn time (days to cover)',               15),
    ('trend',     'Short interest trend (vs prior report)',  10),
    ('movement',  'Realized earnings movement',              10),
    ('liquidity', 'Liquidity (average daily volume)',        10),
]
assert sum(m for _, _, m in SQUEEZE_COMPONENTS) == 100

CATALYST_WINDOW_DAYS = 30
SQUEEZE_INELIGIBLE_CAP = 39
FAST_COVER_DTC = 1.5


def _sq_fuel(short_pct):
    label, mx = 'Fuel load (short interest % of float)', 40
    if not _num(short_pct):
        return _c('fuel', label, mx, None, 'Short interest % of float unavailable')
    si = short_pct
    if si >= 25:
        pts, band = 40, 'TINDERBOX — over a quarter of the float is short'
    elif si >= 20:
        pts, band = 35, 'very high fuel load'
    elif si >= 15:
        pts, band = 30, 'high fuel load'
    elif si >= 12:
        pts, band = 25, 'crowded'
    elif si >= 10:
        pts, band = 19, 'crowded'
    elif si >= 7:
        pts, band = 12, 'some fuel, not crowded'
    elif si >= 5:
        pts, band = 7, 'light fuel'
    elif si >= 3:
        pts, band = 3, 'minimal fuel'
    else:
        pts, band = 0, 'no fuel — hardly anyone is short'
    return _c('fuel', label, mx, pts,
              f"Short interest {si:.1f}% of float — {band} "
              f"(bands: <5% minimal, 5–10% some, 10–15% crowded, 15–25% high, >25% tinderbox)")


def _sq_burn(short_ratio):
    label, mx = 'Burn time (days to cover)', 15
    dtc = short_ratio if _num(short_ratio) and short_ratio > 0 else None
    if dtc is None:
        return _c('burn', label, mx, None, 'Days to cover unavailable')
    if dtc >= 5:
        pts, note = 15, 'slow burn — covering takes the better part of a week of volume; a squeeze can build over multiple sessions'
    elif dtc >= 3:
        pts, note = 13, 'slow burn — shorts need days of average volume to exit'
    elif dtc >= 2:
        pts, note = 10, 'moderate burn time'
    elif dtc >= FAST_COVER_DTC:
        pts, note = 7, 'brisk cover — the squeeze window is short'
    elif dtc >= 1:
        pts, note = 4, 'FAST COVER — shorts can exit in ~a day of volume; any pop likely resolves in 1–2 sessions'
    else:
        pts, note = 2, 'FAST COVER — shorts can exit in under a day of volume; any pop likely resolves in 1–2 sessions'
    return _c('burn', label, mx, pts, f"{dtc:.1f} days to cover — {note}")


def _sq_catalyst(days):
    """Returns (component, eligible). A dated event inside the
    window is REQUIRED — no catalyst, no squeeze, whatever the fuel."""
    label, mx = 'Catalyst (dated earnings event ≤ ~30d)', 15
    if not _num(days):
        return (_c('catalyst', label, mx, None,
                   'No dated earnings event in the data feed — catalyst unconfirmed'), False)
    if days > CATALYST_WINDOW_DAYS:
        return (_c('catalyst', label, mx, 0,
                    f"Next earnings ~{int(days)} days out — outside the ~{CATALYST_WINDOW_DAYS}-day "
                    f"squeeze window. Fuel without a near catalyst is just a crowded stock"), False)
    if 4 <= days <= 21:
        pts, note = 15, 'in the entry sweet spot — close enough to ignite, far enough to position'
    elif days >= 22:
        pts, note = 12, 'inside the window, at the far edge'
    else:
        pts, note = 11, 'imminent — the event is now; entry from here is a chase'
    return (_c('catalyst', label, mx, pts,
               f"Earnings in {int(days)} days — {note}"), True)


def _sq_trend(si_trend):
    """si_trend: 'rising'/'flat'/'falling', or a signed % change vs
    the prior short-interest report, or None. yfinance exposes only
    the CURRENT report, so in practice this is None → unavailable →
    excluded + partial. Never guessed."""
    label, mx = 'Short interest trend (vs prior report)', 10
    if si_trend is None:
        return _c('trend', label, mx, None,
                  'SI trend n/a — the feed reports current short interest only; '
                  'no prior-report comparison is available')
    if _num(si_trend):
        chg = si_trend
        if chg >= 10:
            pts = 10
        elif chg > 2:
            pts = 8
        elif chg >= -2:
            pts = 5
        elif chg > -10:
            pts = 2
        else:
            pts = 0
        return _c('trend', label, mx, pts,
                  f"Short interest {chg:+.1f}% vs the prior report — "
                  + ('the crowd is still piling in' if chg > 2
                     else 'the crowd is leaving — fuel is draining' if chg < -2
                     else 'roughly flat'))
    t = str(si_trend).strip().lower()
    if t == 'rising':
        return _c('trend', label, mx, 8, 'Short interest rising vs the prior report — the crowd is still piling in')
    if t == 'flat':
        return _c('trend', label, mx, 5, 'Short interest roughly flat vs the prior report')
    if t == 'falling':
        return _c('trend', label, mx, 2, 'Short interest falling vs the prior report — fuel is draining before the catalyst')
    return _c('trend', label, mx, None, f"SI trend value '{si_trend}' not recognized — treated as n/a")


def _sq_movement(realized_move_pct):
    label, mx = 'Realized earnings movement', 10
    if not _num(realized_move_pct):
        return _c('movement', label, mx, None,
                  'Realized earnings-move history n/a — unproven that this name jumps on its prints')
    m = realized_move_pct
    if m >= 10:
        pts = 10
    elif m >= 7:
        pts = 8
    elif m >= 5:
        pts = 6
    elif m >= 3.5:
        pts = 4
    elif m >= 2:
        pts = 2
    else:
        pts = 0
    return _c('movement', label, mx, pts,
              f"Averages ±{m:.1f}% on its earnings prints — "
              + ('a proven mover: the catalyst reliably produces a spike' if m >= 5
                 else 'modest historical moves — even a good setup may pop less here'))


def _sq_liquidity(avg_vol):
    label, mx = 'Liquidity (average daily volume)', 10
    if not _num(avg_vol) or avg_vol <= 0:
        return _c('liquidity', label, mx, None, 'Average volume unavailable')
    v = avg_vol
    if v >= 20_000_000:
        pts = 10
    elif v >= 5_000_000:
        pts = 8
    elif v >= 1_000_000:
        pts = 6
    elif v >= 500_000:
        pts = 4
    elif v >= 100_000:
        pts = 2
    else:
        pts = 0
    return _c('liquidity', label, mx, pts,
              f"Average volume {v:,.0f} shares/day — "
              + ('deep liquidity; getting out is not the problem' if v >= 5_000_000
                 else 'workable liquidity' if v >= 500_000
                 else 'thin — exits get expensive exactly when everyone runs for them'))


def compute_squeeze_score(facts):
    """
    facts: dict with any of —
      shortPct (% of float), shortRatio (days to cover),
      daysToEarnings, siTrend ('rising'/'flat'/'falling', signed
      % change, or None), realizedMovePct (avg |earnings move|),
      avgVol (raw shares/day)

    Returns the same shape as compute_score —
      {total, grade, partial, partialNote, components, version}
    plus squeeze-specific fields:
      eligible  — False when no dated catalyst sits inside the
                  ~30-day window; the total is then capped at
                  SQUEEZE_INELIGIBLE_CAP no matter the fuel
      capNote   — why the cap applied ('' when eligible)
      fastCover — True when days-to-cover < 1.5: any pop likely
                  resolves in 1–2 sessions
      flags     — machine-readable list, e.g. ['fast-cover']
    total is None when nothing at all was measurable.
    """
    catalyst_comp, eligible = _sq_catalyst(facts.get('daysToEarnings'))
    comps = [
        _sq_fuel(facts.get('shortPct')),
        catalyst_comp,
        _sq_burn(facts.get('shortRatio')),
        _sq_trend(facts.get('siTrend')),
        _sq_movement(facts.get('realizedMovePct')),
        _sq_liquidity(facts.get('avgVol')),
    ]
    earned = sum(c['points'] for c in comps if c['available'])
    avail_max = sum(c['max'] for c in comps if c['available'])
    missing = [c['label'] for c in comps if not c['available']]

    if avail_max == 0:
        total, partial, note = None, True, 'No squeeze data available'
    elif missing:
        total = round(100 * earned / avail_max)
        partial = True
        note = ('Partial data — not measured: ' + ', '.join(missing)
                + f'. Score rescaled over the {avail_max} measurable points.')
    else:
        total = round(earned)
        partial = False
        note = ''

    cap_note = ''
    if total is not None and not eligible:
        cap_note = (f'Not squeeze-eligible: no dated earnings catalyst within '
                    f'~{CATALYST_WINDOW_DAYS} days — score capped at {SQUEEZE_INELIGIBLE_CAP}. '
                    f'Fuel without an ignition date is just a crowded stock.')
        total = min(total, SQUEEZE_INELIGIBLE_CAP)

    dtc = facts.get('shortRatio')
    fast_cover = bool(_num(dtc) and 0 < dtc < FAST_COVER_DTC)

    grade = None
    if total is not None:
        grade = 'PRIMED' if total >= 65 else ('LOADED' if total >= 45 else 'THIN')

    return {
        'total': total,
        'grade': grade,
        'partial': partial,
        'partialNote': note,
        'components': comps,
        'version': SQUEEZE_SCORE_VERSION,
        'eligible': eligible,
        'capNote': cap_note,
        'fastCover': fast_cover,
        'flags': (['fast-cover'] if fast_cover else [])
                 + ([] if eligible else ['no-catalyst']),
    }


# ============ HARD FILTERS (scanner) ============

def hard_filter_failures(facts, criteria):
    """
    Returns a list of human-readable failure reasons (empty = passes).
    The scanner keeps failing tickers in stock_data.json with
    excluded:true + these reasons instead of silently dropping them.
    facts: price, pe, eps, shortPct, pctFromHigh, avgVol
    criteria: price_min, price_max, max_pe, max_short,
              min_pct_from_high, require_profitable
    """
    reasons = []
    price, pe, eps = facts.get('price'), facts.get('pe'), facts.get('eps')
    short_pct, pfh, vol = facts.get('shortPct'), facts.get('pctFromHigh'), facts.get('avgVol')

    if _num(price):
        if price < criteria['price_min']:
            reasons.append(f"Price ${price:.2f} below the ${criteria['price_min']:.0f} minimum")
        if price > criteria['price_max']:
            reasons.append(f"Price ${price:.2f} above the ${criteria['price_max']:.0f} maximum")
    if criteria.get('require_profitable') and _num(pe) and _num(eps) and (pe <= 0 or eps <= 0):
        reasons.append("Not profitable (P/E ≤ 0) — fails the profitable-only filter")
    if _num(pe) and pe > 0 and pe > criteria['max_pe']:
        reasons.append(f"P/E {pe:.1f} above the {criteria['max_pe']:.0f} maximum")
    if _num(short_pct) and short_pct > criteria['max_short']:
        reasons.append(f"Short interest {short_pct:.1f}% of float above the {criteria['max_short']:.0f}% maximum")
    if _num(pfh) and pfh < criteria['min_pct_from_high']:
        reasons.append(f"Only {pfh:.1f}% below the 52-week high (needs ≥ {criteria['min_pct_from_high']:.0f}%) — too close to highs, likely priced in")
    if _num(vol) and vol < 500000:
        reasons.append(f"Average volume {vol:,.0f} below 500K — options too illiquid for a clean 100-lot play")
    return reasons


# ============ DIVIDEND YIELD (bug fix) ============

def compute_div_yield(info, price):
    """
    yfinance's `dividendYield` is inconsistent — a fraction (0.024)
    for some tickers, an already-percent number (4.05) for others —
    and the old code multiplied it by 100 unconditionally, which is
    how RF ended up displaying a 405.0% yield.

    Prefer dividendRate / price (both unambiguous). Sanity-clamp:
    anything over 25% is flagged 'check' and never displayed raw.

    Returns {divYield: display str, divYieldPct: float|None, divYieldSuspect: bool}
    """
    rate = info.get('dividendRate')
    raw = info.get('dividendYield')
    pct = None
    if _num(rate) and rate > 0 and _num(price) and price > 0:
        pct = rate / price * 100
    elif _num(raw) and raw > 0:
        # Heuristic: values ≤ 1.5 are fractions (150% yield doesn't
        # exist); larger values are already in percent form.
        pct = raw * 100 if raw <= 1.5 else raw
    if pct is None or pct <= 0:
        return {'divYield': '0%', 'divYieldPct': 0.0, 'divYieldSuspect': False}
    pct = round(pct, 1)
    if pct > 25:
        return {'divYield': '⚠ check', 'divYieldPct': None, 'divYieldSuspect': True}
    return {'divYield': f"{pct}%", 'divYieldPct': pct, 'divYieldSuspect': False}


# ============ REALIZED EARNINGS MOVE ============

def compute_earnings_move(ticker, earnings_hist=None):
    """
    Average absolute % move around the last 4–8 earnings prints,
    measured close-to-close from the last close before the report
    to the close one trading day after it (captures both BMO and
    AMC prints without needing the announcement timestamp).

    Returns {avgAbsMovePct, count, moves:[...]} or None when the
    history isn't there. Honest absence beats a fabricated number.
    """
    try:
        eh = earnings_hist if earnings_hist is not None else ticker.earnings_history
        if eh is None or len(eh) == 0:
            return None
        dates = []
        for idx in list(eh.index)[-8:]:
            try:
                d = idx.date() if hasattr(idx, 'date') else idx
            except Exception:
                continue
            dates.append(d)
        if len(dates) < 2:
            return None
        hist = ticker.history(period='2y', auto_adjust=False)
        if hist is None or hist.empty:
            return None
        hist_dates = [ix.date() if hasattr(ix, 'date') else ix for ix in hist.index]
        closes = hist['Close'].tolist()
        moves = []
        for d in dates:
            # first trading day on/after the report date
            after_idx = next((i for i, hd in enumerate(hist_dates) if hd >= d), None)
            if after_idx is None or after_idx < 1 or after_idx + 1 >= len(closes):
                continue
            before = closes[after_idx - 1]
            after = closes[after_idx + 1]
            if before and after and before == before and after == after:
                moves.append(round(abs(after / before - 1) * 100, 1))
        if len(moves) < 2:
            return None
        moves = moves[-8:]
        return {
            'avgAbsMovePct': round(sum(moves) / len(moves), 1),
            'count': len(moves),
            'moves': moves,
        }
    except Exception:
        return None


# ============ GUIDANCE FLAG ============

def detect_guidance(ticker):
    """
    Guidance direction on the most recent print (raised / held /
    cut). There is no reliable free structured source for this —
    it lives in press releases and call transcripts — so this
    returns 'unknown' rather than guessing. The field exists so
    the UI can show the gap honestly and the flag can be wired to
    a real source later without a schema change.
    """
    return {
        'flag': 'unknown',
        'note': 'Guidance direction is not in the free data feed — check the earnings press release before entering.',
    }


# ============ COVERED-CALL DIVIDEND FLAGS ============

def _parse_ex_div(value):
    """yfinance exDividendDate arrives as epoch seconds, a date, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value).date()
        except Exception:
            return None
    if hasattr(value, 'date'):
        try:
            return value.date()
        except Exception:
            return None
    if isinstance(value, datetime):
        return value.date()
    return value  # assume already a date


def covered_call_flags(info, days_to_earnings):
    """
    Ex-dividend / early-assignment risk for a covered call held
    from now through ~2 weeks after earnings (the app's standard
    holding window). If the ex-div date lands inside that window
    and the short call is in the money into it, the call is likely
    to be exercised the day before the ex-date.
    """
    rate = info.get('dividendRate')
    pays = _num(rate) and rate > 0
    ex_date = _parse_ex_div(info.get('exDividendDate'))
    window_days = (days_to_earnings or 0) + 14
    in_window = False
    note = ''
    if pays and ex_date is not None:
        today = datetime.now().date()
        if today <= ex_date <= today + timedelta(days=window_days):
            in_window = True
            note = (f"Ex-dividend date {ex_date.isoformat()} falls inside the covered-call "
                    f"holding window — an in-the-money short call is likely to be exercised "
                    f"early (the day before the ex-date). Plan strike/expiry around it.")
    return {
        'paysDividend': bool(pays),
        'exDivDate': ex_date.isoformat() if ex_date else None,
        'exDivInWindow': in_window,
        'note': note,
    }
