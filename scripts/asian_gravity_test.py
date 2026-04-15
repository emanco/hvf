"""
Asian Session Gravity Strategy — Feasibility Test

Tests whether price returns to the session open after drifting away.
Hypothesis: during Asian hours, EURGBP (and similar "both asleep" pairs)
oscillate around the opening price because there's no flow to push them.

Measures:
1. After price moves X pips from session open, how often does it return within Y pips?
2. How long does the return take?
3. How far does price drift before returning (max adverse excursion)?
4. What's the net expectancy at various target/stop combinations?

Usage:
    python scripts/asian_gravity_test.py
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# --- Configuration --------------------------------------------------------

PAIRS = ["EURGBP", "USDCHF", "EURUSD", "AUDNZD"]
TIMEFRAME = mt5.TIMEFRAME_M15
LOOKBACK_DAYS = 365

SESSION_START_H = 0   # 00:00 UTC
SESSION_END_H = 6     # 06:00 UTC

# Test various trigger/target combinations
TRIGGER_PIPS = [3, 5, 7, 10]   # how far from open before entering
TARGET_PIPS = [3, 5]            # how close to open = "returned"
STOP_PIPS = [8, 10, 15]        # stop beyond the trigger point

PIP_VALUES = {
    "EURUSD": 0.0001, "NZDUSD": 0.0001, "EURGBP": 0.0001,
    "USDCHF": 0.0001, "EURAUD": 0.0001, "AUDNZD": 0.0001,
    "GBPJPY": 0.01,
}


# --- MT5 Setup ------------------------------------------------------------

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


def fetch_data(symbol: str, days: int) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=days)
    rates = mt5.copy_rates_range(symbol, TIMEFRAME, from_date, now)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


# --- Analysis -------------------------------------------------------------

def analyze_gravity(symbol: str, df: pd.DataFrame, pip_val: float) -> dict:
    """Analyze session-open gravity for a pair."""

    df["date"] = df.index.date
    results = {}

    # Collect sessions
    sessions = []
    for date, group in df.groupby("date"):
        asian = group[(group.index.hour >= SESSION_START_H) &
                      (group.index.hour < SESSION_END_H)]
        if len(asian) < 10 or asian.index[0].weekday() >= 5:
            continue

        session_open = asian.iloc[0]["open"]
        avg_spread_pips = asian["spread"].mean() / 10.0 if "spread" in asian.columns else 0

        # Track bar-by-bar price relative to open
        bars = []
        for ts, bar in asian.iterrows():
            bars.append({
                "time": ts,
                "high_pips": (bar["high"] - session_open) / pip_val,
                "low_pips": (bar["low"] - session_open) / pip_val,
                "close_pips": (bar["close"] - session_open) / pip_val,
            })

        sessions.append({
            "date": date,
            "session_open": session_open,
            "bars": bars,
            "avg_spread_pips": avg_spread_pips,
            "session_range_pips": (asian["high"].max() - asian["low"].min()) / pip_val,
        })

    if not sessions:
        return None

    # Session range stats
    ranges = [s["session_range_pips"] for s in sessions]
    spreads = [s["avg_spread_pips"] for s in sessions if s["avg_spread_pips"] > 0]

    results["symbol"] = symbol
    results["sessions"] = len(sessions)
    results["range_median"] = np.median(ranges)
    results["range_p25"] = np.percentile(ranges, 25)
    results["range_p75"] = np.percentile(ranges, 75)
    results["spread_median"] = np.median(spreads) if spreads else 0

    # Test each trigger/target/stop combination
    combos = []
    for trigger in TRIGGER_PIPS:
        for target in TARGET_PIPS:
            for stop in STOP_PIPS:
                combo = simulate_gravity_trades(sessions, trigger, target, stop, pip_val)
                combo["trigger"] = trigger
                combo["target"] = target
                combo["stop"] = stop
                combos.append(combo)

    results["combos"] = combos

    # Also measure raw return-to-open rate (no stop/target, just: does it come back?)
    results["return_rates"] = {}
    for trigger in TRIGGER_PIPS:
        rate = measure_return_rate(sessions, trigger, pip_val)
        results["return_rates"][trigger] = rate

    return results


def measure_return_rate(sessions: list, trigger_pips: float, pip_val: float) -> dict:
    """After price moves trigger_pips from open, how often does it return within 2 pips of open?"""
    events = 0
    returns = 0
    return_times = []  # minutes to return

    for session in sessions:
        bars = session["bars"]
        triggered_up = False
        triggered_down = False
        trigger_bar_idx = None

        for i, bar in enumerate(bars):
            # Check if price moved trigger_pips above open
            if not triggered_up and bar["high_pips"] >= trigger_pips:
                triggered_up = True
                trigger_bar_idx = i
                events += 1
                # Check remaining bars for return to within 2 pips of open
                for j in range(i + 1, len(bars)):
                    if bars[j]["low_pips"] <= 2:
                        returns += 1
                        return_times.append((j - i) * 15)  # M15 bars = 15 min each
                        break
                triggered_up = False  # allow another trigger later

            # Check if price moved trigger_pips below open
            if not triggered_down and bar["low_pips"] <= -trigger_pips:
                triggered_down = True
                trigger_bar_idx = i
                events += 1
                for j in range(i + 1, len(bars)):
                    if bars[j]["high_pips"] >= -2:
                        returns += 1
                        return_times.append((j - i) * 15)
                        break
                triggered_down = False

    return {
        "events": events,
        "returns": returns,
        "rate": returns / events if events > 0 else 0,
        "median_time_min": np.median(return_times) if return_times else 0,
    }


def simulate_gravity_trades(sessions: list, trigger_pips: float,
                            target_pips: float, stop_pips: float,
                            pip_val: float) -> dict:
    """Simulate gravity trades across all sessions.

    Entry: when price moves trigger_pips from open, enter toward the open.
    TP: price returns within target_pips of open.
    SL: price moves stop_pips beyond the trigger point.
    Time exit: session end (06:00 UTC).
    """
    trades = []

    for session in sessions:
        bars = session["bars"]
        spread = session["avg_spread_pips"]
        session_trades = 0
        max_trades_per_session = 4
        cooldown_bars = 2  # 30 min cooldown between trades

        last_trade_bar = -999

        for i, bar in enumerate(bars):
            if session_trades >= max_trades_per_session:
                break
            if (i - last_trade_bar) < cooldown_bars:
                continue

            # Check for SHORT trigger (price went too high, expect return down)
            if bar["high_pips"] >= trigger_pips:
                entry_pips = trigger_pips  # enter at trigger level
                tp_level = target_pips     # return to near open
                sl_level = trigger_pips + stop_pips  # stop beyond

                # Walk remaining bars
                result = _resolve_trade(
                    bars[i+1:], direction="SHORT",
                    entry_pips=entry_pips, tp_pips=tp_level,
                    sl_pips=sl_level, spread=spread,
                )
                trades.append(result)
                session_trades += 1
                last_trade_bar = i

            # Check for LONG trigger (price went too low, expect return up)
            if bar["low_pips"] <= -trigger_pips:
                entry_pips = -trigger_pips
                tp_level = -target_pips
                sl_level = -(trigger_pips + stop_pips)

                result = _resolve_trade(
                    bars[i+1:], direction="LONG",
                    entry_pips=entry_pips, tp_pips=tp_level,
                    sl_pips=sl_level, spread=spread,
                )
                trades.append(result)
                session_trades += 1
                last_trade_bar = i

    if not trades:
        return {"trades": 0, "wins": 0, "wr": 0, "pf": 0, "exp": 0, "avg_win": 0, "avg_loss": 0}

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    gross_profit = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0.001

    return {
        "trades": len(trades),
        "wins": len(wins),
        "wr": len(wins) / len(trades) if trades else 0,
        "pf": gross_profit / gross_loss,
        "exp": np.mean([t["pnl"] for t in trades]),
        "avg_win": np.mean([t["pnl"] for t in wins]) if wins else 0,
        "avg_loss": np.mean([t["pnl"] for t in losses]) if losses else 0,
    }


def _resolve_trade(remaining_bars: list, direction: str,
                    entry_pips: float, tp_pips: float, sl_pips: float,
                    spread: float) -> dict:
    """Resolve a single trade against remaining session bars."""

    for bar in remaining_bars:
        if direction == "LONG":
            # TP: high reaches tp level (closer to open)
            if bar["high_pips"] >= tp_pips:
                pnl = abs(entry_pips - tp_pips) - spread
                return {"pnl": pnl, "exit": "TP"}
            # SL: low breaches sl level (further from open)
            if bar["low_pips"] <= sl_pips:
                pnl = -(abs(entry_pips - sl_pips) + spread)
                return {"pnl": pnl, "exit": "SL"}
        else:  # SHORT
            # TP: low reaches tp level (closer to open)
            if bar["low_pips"] <= tp_pips:
                pnl = abs(entry_pips - tp_pips) - spread
                return {"pnl": pnl, "exit": "TP"}
            # SL: high breaches sl level (further from open)
            if bar["high_pips"] >= sl_pips:
                pnl = -(abs(entry_pips - sl_pips) + spread)
                return {"pnl": pnl, "exit": "SL"}

    # Time exit: close at session end, compute P&L from last bar close
    if remaining_bars:
        last_close = remaining_bars[-1]["close_pips"]
        if direction == "LONG":
            pnl = (last_close - entry_pips) - spread
        else:
            pnl = (entry_pips - last_close) - spread
        return {"pnl": pnl, "exit": "TIME"}

    return {"pnl": -spread, "exit": "TIME"}


# --- Main -----------------------------------------------------------------

def main():
    init_mt5()

    print(f"\n{'='*70}")
    print("Asian Session Gravity Strategy — Feasibility Test")
    print(f"Session: {SESSION_START_H:02d}:00-{SESSION_END_H:02d}:00 UTC")
    print(f"Lookback: {LOOKBACK_DAYS} days")
    print(f"{'='*70}")

    for symbol in PAIRS:
        print(f"\nFetching {symbol}...")
        df = fetch_data(symbol, LOOKBACK_DAYS)
        if df.empty:
            print(f"  No data available")
            continue

        pip_val = PIP_VALUES.get(symbol, 0.0001)
        print(f"  {len(df)} M15 bars ({df.index[0].date()} to {df.index[-1].date()})")

        results = analyze_gravity(symbol, df, pip_val)
        if not results:
            print(f"  No valid sessions")
            continue

        # --- Print Results --------------------------------------------

        print(f"\n{'-'*70}")
        print(f"  {symbol} — {results['sessions']} sessions")
        print(f"{'-'*70}")
        print(f"  Session range: median={results['range_median']:.1f}p  "
              f"P25={results['range_p25']:.1f}p  P75={results['range_p75']:.1f}p")
        print(f"  Spread: {results['spread_median']:.1f} pips")

        # Return-to-open rates
        print(f"\n  Return-to-open rates (within 2 pips of open):")
        print(f"  {'Drift':>6}  {'Events':>7}  {'Returns':>8}  {'Rate':>6}  {'Med Time':>9}")
        for trigger, data in sorted(results["return_rates"].items()):
            print(f"  {trigger:>5}p  {data['events']:>7}  {data['returns']:>8}  "
                  f"{data['rate']*100:>5.0f}%  {data['median_time_min']:>7.0f}m")

        # Best trade combos
        print(f"\n  Trade simulations (sorted by expectancy):")
        print(f"  {'Trigger':>7} {'Target':>7} {'Stop':>5} {'Trades':>7} "
              f"{'WR':>5} {'PF':>5} {'Exp':>7} {'AvgW':>6} {'AvgL':>7}")

        best_combos = sorted(results["combos"], key=lambda x: x["exp"], reverse=True)
        for c in best_combos[:15]:  # top 15
            if c["trades"] == 0:
                continue
            print(f"  {c['trigger']:>6}p {c['target']:>6}p {c['stop']:>4}p "
                  f"{c['trades']:>7} {c['wr']*100:>4.0f}% {c['pf']:>5.2f} "
                  f"{c['exp']:>+6.1f}p {c['avg_win']:>5.1f}p {c['avg_loss']:>+6.1f}p")

        # Highlight the best combo
        if best_combos and best_combos[0]["exp"] > 0:
            b = best_combos[0]
            print(f"\n  ** BEST: trigger={b['trigger']}p target={b['target']}p "
                  f"stop={b['stop']}p -> WR={b['wr']*100:.0f}% PF={b['pf']:.2f} "
                  f"Exp={b['exp']:+.1f}p/trade ({b['trades']} trades)")
        else:
            print(f"\n  ** No profitable combination found.")

    mt5.shutdown()
    print(f"\n{'='*70}")
    print("Done.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
