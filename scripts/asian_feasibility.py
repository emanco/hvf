"""
Asian Range Scalper — Quick Feasibility Check

Validates whether the edge exists before building a backtest engine.
Runs on VPS with MT5 access. Uses M5 data.

Checks per pair:
1. Range distribution (median, percentiles, CV)
2. Spread-to-range ratio
3. Mean-reversion rate (touch extreme → return to midpoint)
4. Containment rate (does the 2h range hold until 06:00?)
5. Touches per session

Usage:
    python scripts/asian_feasibility.py
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Ensure hvf_trader is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# ─── Configuration ────────────────────────────────────────────────────────

PAIRS = ["EURGBP", "USDCHF", "EURUSD", "NZDUSD", "AUDNZD", "EURAUD", "GBPJPY"]
TIMEFRAME = mt5.TIMEFRAME_M15  # M5 not available on IC Markets; M15 gives 24 bars/session
LOOKBACK_DAYS = 365  # 1 year of data

# Asian session in UTC
FORMATION_START_H = 0   # 00:00 UTC
FORMATION_END_H = 2     # 02:00 UTC
SESSION_END_H = 6       # 06:00 UTC

# Pip values
PIP_VALUES = {
    "EURUSD": 0.0001, "NZDUSD": 0.0001, "EURGBP": 0.0001,
    "USDCHF": 0.0001, "EURAUD": 0.0001, "AUDNZD": 0.0001,
    "GBPJPY": 0.01, "EURJPY": 0.01, "CHFJPY": 0.01,
}

# Thresholds from strategy design doc
MIN_RANGE_PIPS = 15
MAX_RANGE_PIPS = 35
MAX_SPREAD_RATIO = 0.25          # spread / range
MIN_REVERSION_RATE = 0.60        # 60%
MIN_CONTAINMENT_RATE = 0.65      # 65%
MIN_TOUCHES = 1.5                # per session
MAX_CV = 0.70                    # range coefficient of variation
TOUCH_PROXIMITY_PIPS = 2         # "touching" = within 2 pips of extreme
REVERSION_TARGET = 0.5           # return to 50% of range (midpoint)


# ─── MT5 Setup ────────────────────────────────────────────────────────────

def init_mt5():
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}")
        sys.exit(1)
    login = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    if not mt5.login(login, password, server):
        print(f"MT5 login failed: {mt5.last_error()}")
        sys.exit(1)
    print(f"Connected to MT5: account {login}")


def fetch_m5_data(symbol: str, days: int) -> pd.DataFrame:
    """Fetch M5 OHLCV data for the given symbol."""
    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=days)
    rates = mt5.copy_rates_range(symbol, TIMEFRAME, from_date, now)
    if rates is None or len(rates) == 0:
        print(f"  {symbol}: No M5 data available")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    print(f"  {symbol}: {len(df)} M5 bars ({df.index[0].date()} to {df.index[-1].date()})")
    return df


# ─── Analysis Functions ───────────────────────────────────────────────────

def extract_sessions(df: pd.DataFrame, pip_val: float) -> list[dict]:
    """Group M5 bars into Asian sessions and compute per-session stats."""
    sessions = []

    # Group by date
    df["date"] = df.index.date
    for date, group in df.groupby("date"):
        # Filter to Asian session hours (UTC)
        asian = group[(group.index.hour >= FORMATION_START_H) &
                      (group.index.hour < SESSION_END_H)]
        if len(asian) < 10:  # need at least ~10 M15 bars for a meaningful session
            continue

        # Skip weekends (Saturday/Sunday)
        if asian.index[0].weekday() >= 5:
            continue

        # Formation window bars
        formation = asian[(asian.index.hour >= FORMATION_START_H) &
                          (asian.index.hour < FORMATION_END_H)]
        if len(formation) < 4:  # need at least 4 M15 bars in 2h formation window
            continue

        # Trading window bars
        trading = asian[(asian.index.hour >= FORMATION_END_H) &
                        (asian.index.hour < SESSION_END_H)]
        if len(trading) < 6:  # need at least 6 M15 bars in 4h trading window
            continue

        # Range from formation window
        form_high = formation["high"].max()
        form_low = formation["low"].min()
        range_price = form_high - form_low
        range_pips = range_price / pip_val

        # Full session high/low (for containment check)
        session_high = asian["high"].max()
        session_low = asian["low"].min()

        # Spread: MT5 spread field is in points (smallest price increment).
        # For 5-digit pairs (EURUSD etc.), 1 pip = 10 points. For JPY pairs, 1 pip = 10 points.
        # So spread_in_pips = spread_in_points / 10
        avg_spread_points = asian["spread"].mean() if "spread" in asian.columns else 0
        avg_spread_pips = avg_spread_points / 10.0 if avg_spread_points > 0 else 0

        # Containment: did price stay within formation range during trading window?
        trading_high = trading["high"].max()
        trading_low = trading["low"].min()
        contained = (trading_high <= form_high) and (trading_low >= form_low)

        # Mean-reversion: count touches and reversions
        midpoint = (form_high + form_low) / 2
        touch_buffer = TOUCH_PROXIMITY_PIPS * pip_val
        reversion_target_price = range_price * REVERSION_TARGET

        touches_low = 0
        touches_high = 0
        reversions_from_low = 0
        reversions_from_high = 0

        # Walk through trading window bars
        last_touch = None
        last_touch_idx = -999
        min_separation_bars = 2  # at least 30 min between touches (M15 bars)

        for i, (ts, bar) in enumerate(trading.iterrows()):
            # Check low touch
            if bar["low"] <= form_low + touch_buffer and (i - last_touch_idx) >= min_separation_bars:
                touches_low += 1
                last_touch = "low"
                last_touch_idx = i
                # Check if price returns to midpoint before session end
                remaining = trading.iloc[i:]
                if remaining["high"].max() >= midpoint:
                    reversions_from_low += 1

            # Check high touch
            if bar["high"] >= form_high - touch_buffer and (i - last_touch_idx) >= min_separation_bars:
                touches_high += 1
                last_touch = "high"
                last_touch_idx = i
                remaining = trading.iloc[i:]
                if remaining["low"].min() <= midpoint:
                    reversions_from_high += 1

        total_touches = touches_low + touches_high
        total_reversions = reversions_from_low + reversions_from_high

        sessions.append({
            "date": date,
            "range_pips": range_pips,
            "range_price": range_price,
            "form_high": form_high,
            "form_low": form_low,
            "contained": contained,
            "touches_low": touches_low,
            "touches_high": touches_high,
            "total_touches": total_touches,
            "reversions": total_reversions,
            "avg_spread_pips": avg_spread_pips,
            "trading_bars": len(trading),
        })

    return sessions


def analyze_pair(symbol: str, sessions: list[dict]) -> dict:
    """Compute summary statistics for a pair's Asian sessions."""
    if not sessions:
        return None

    ranges = [s["range_pips"] for s in sessions]
    spreads = [s["avg_spread_pips"] for s in sessions if s["avg_spread_pips"] > 0]
    containment = [s["contained"] for s in sessions]
    touches = [s["total_touches"] for s in sessions]

    # Reversion rate (only sessions with at least 1 touch)
    sessions_with_touches = [s for s in sessions if s["total_touches"] > 0]
    if sessions_with_touches:
        total_touches = sum(s["total_touches"] for s in sessions_with_touches)
        total_reversions = sum(s["reversions"] for s in sessions_with_touches)
        reversion_rate = total_reversions / total_touches if total_touches > 0 else 0
    else:
        reversion_rate = 0
        total_touches = 0

    # Range stats
    range_median = np.median(ranges)
    range_mean = np.mean(ranges)
    range_std = np.std(ranges)
    range_cv = range_std / range_mean if range_mean > 0 else 999
    range_p25 = np.percentile(ranges, 25)
    range_p75 = np.percentile(ranges, 75)

    # Spread stats
    spread_median = np.median(spreads) if spreads else 0
    spread_to_range = spread_median / range_median if range_median > 0 else 999

    # In-range sessions (15-35 pips)
    in_range_sessions = [s for s in sessions if MIN_RANGE_PIPS <= s["range_pips"] <= MAX_RANGE_PIPS]
    pct_tradeable = len(in_range_sessions) / len(sessions) * 100 if sessions else 0

    return {
        "symbol": symbol,
        "sessions": len(sessions),
        "range_median": range_median,
        "range_p25": range_p25,
        "range_p75": range_p75,
        "range_cv": range_cv,
        "spread_median": spread_median,
        "spread_rt": spread_median * 2,  # round-trip
        "spread_to_range": spread_to_range * 2,  # round-trip as % of range
        "containment_rate": np.mean(containment) if containment else 0,
        "touches_avg": np.mean(touches) if touches else 0,
        "reversion_rate": reversion_rate,
        "total_touches": total_touches,
        "pct_tradeable": pct_tradeable,
    }


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    init_mt5()

    print(f"\n{'='*70}")
    print(f"Asian Range Scalper — Feasibility Analysis")
    print(f"Formation: {FORMATION_START_H:02d}:00-{FORMATION_END_H:02d}:00 UTC")
    print(f"Trading:   {FORMATION_END_H:02d}:00-{SESSION_END_H:02d}:00 UTC")
    print(f"Lookback:  {LOOKBACK_DAYS} days")
    print(f"{'='*70}\n")

    print("Fetching M5 data...")
    results = []

    for symbol in PAIRS:
        df = fetch_m5_data(symbol, LOOKBACK_DAYS)
        if df.empty:
            continue

        pip_val = PIP_VALUES.get(symbol, 0.0001)
        sessions = extract_sessions(df, pip_val)

        if not sessions:
            print(f"  {symbol}: No valid Asian sessions found")
            continue

        stats = analyze_pair(symbol, sessions)
        if stats:
            results.append(stats)

    if not results:
        print("\nNo data to analyze. Check MT5 connection and data availability.")
        mt5.shutdown()
        return

    # ─── Summary Table ────────────────────────────────────────────────

    print(f"\n{'='*70}")
    print("RESULTS SUMMARY")
    print(f"{'='*70}\n")

    # Header
    print(f"{'Pair':<10} {'Sessions':>8} {'Range':>7} {'CV':>6} {'Spread':>7} "
          f"{'Sprd%':>6} {'Contain':>8} {'Touches':>8} {'Revert':>7} "
          f"{'Tradeable':>10} {'Verdict':>8}")
    print("-" * 100)

    for r in sorted(results, key=lambda x: x["reversion_rate"], reverse=True):
        # Pass/fail checks
        checks = []
        if r["range_median"] < 10:
            checks.append("range_tiny")
        if r["range_cv"] > MAX_CV:
            checks.append("cv_high")
        if r["spread_to_range"] > MAX_SPREAD_RATIO:
            checks.append("spread")
        if r["containment_rate"] < MIN_CONTAINMENT_RATE:
            checks.append("contain")
        if r["reversion_rate"] < MIN_REVERSION_RATE:
            checks.append("revert")
        if r["touches_avg"] < MIN_TOUCHES:
            checks.append("touches")

        verdict = "PASS" if not checks else "FAIL"

        print(f"{r['symbol']:<10} {r['sessions']:>8} {r['range_median']:>6.1f}p "
              f"{r['range_cv']:>5.2f} {r['spread_median']:>6.1f}p "
              f"{r['spread_to_range']*100:>5.1f}% {r['containment_rate']*100:>7.0f}% "
              f"{r['touches_avg']:>7.1f} {r['reversion_rate']*100:>6.0f}% "
              f"{r['pct_tradeable']:>9.0f}% {verdict:>8}")

        if checks:
            print(f"{'':>10} Failures: {', '.join(checks)}")

    # ─── Detailed Per-Pair Stats ──────────────────────────────────────

    print(f"\n{'='*70}")
    print("DETAILED STATS")
    print(f"{'='*70}\n")

    for r in sorted(results, key=lambda x: x["reversion_rate"], reverse=True):
        print(f"--- {r['symbol']} ({r['sessions']} sessions) ---")
        print(f"  Range:        median={r['range_median']:.1f}p  "
              f"P25={r['range_p25']:.1f}p  P75={r['range_p75']:.1f}p  CV={r['range_cv']:.2f}")
        print(f"  Spread:       median={r['spread_median']:.1f}p  "
              f"round-trip={r['spread_rt']:.1f}p  "
              f"RT/range={r['spread_to_range']*100:.1f}%")
        print(f"  Containment:  {r['containment_rate']*100:.0f}% "
              f"of sessions stayed within formation range")
        print(f"  Touches:      {r['touches_avg']:.1f} avg per session  "
              f"({r['total_touches']} total)")
        print(f"  Reversion:    {r['reversion_rate']*100:.0f}% "
              f"of touches reverted to midpoint")
        print(f"  Tradeable:    {r['pct_tradeable']:.0f}% "
              f"of sessions had 15-35 pip range")

        # Net expectancy estimate
        if r["reversion_rate"] > 0 and r["range_median"] > 0:
            avg_win = r["range_median"] * 0.4  # conservative: 40% of range
            avg_loss = r["range_median"] * 0.4 + 5  # range + 5 pip buffer
            spread_cost = r["spread_rt"]
            net_exp = (r["reversion_rate"] * (avg_win - spread_cost) -
                       (1 - r["reversion_rate"]) * (avg_loss + spread_cost))
            print(f"  Est. expectancy: {net_exp:+.1f} pips/trade "
                  f"(WR={r['reversion_rate']*100:.0f}%, "
                  f"win={avg_win:.0f}p, loss={avg_loss:.0f}p, "
                  f"spread={spread_cost:.1f}p RT)")
        print()

    # ─── Go/No-Go ─────────────────────────────────────────────────────

    passing = [r for r in results if
               r["range_median"] >= 10 and
               r["range_cv"] <= MAX_CV and
               r["spread_to_range"] <= MAX_SPREAD_RATIO and
               r["containment_rate"] >= MIN_CONTAINMENT_RATE and
               r["reversion_rate"] >= MIN_REVERSION_RATE]

    print(f"{'='*70}")
    if len(passing) >= 2:
        print(f"GO: {len(passing)} pairs passed all thresholds: "
              f"{', '.join(r['symbol'] for r in passing)}")
        print("Proceed to backtest engine build.")
    elif len(passing) == 1:
        print(f"MARGINAL: Only 1 pair passed: {passing[0]['symbol']}")
        print("Single-pair strategy is fragile. Consider relaxing thresholds or adding pairs.")
    else:
        print("NO-GO: No pairs passed all thresholds.")
        print("The Asian range scalper edge may not exist with current spread/range conditions.")
    print(f"{'='*70}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
