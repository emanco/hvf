"""
Asian Gravity Strategy v2 - Optimized for high WR + tight stops

Key levers:
1. Tighter stops (3-6 pips) - reduce loss magnitude on the 12%
2. Smaller trigger/target combos - more surgical entries
3. ADX filter - skip trending nights
4. ATR filter - skip volatile nights
5. Time-of-session filter - only trade in the quietest hours
6. Higher lot sizing analysis at 88% WR

Usage:
    python scripts/asian_gravity_v2.py
"""

import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

PAIRS = ["EURGBP", "EURUSD"]
TIMEFRAME = mt5.TIMEFRAME_M15
LOOKBACK_DAYS = 365

SESSION_START_H = 0
SESSION_END_H = 6

PIP_VALUES = {"EURUSD": 0.0001, "EURGBP": 0.0001}

# Tighter parameter grid
TRIGGER_PIPS = [3, 4, 5]
TARGET_PIPS = [2, 3, 4, 5]
STOP_PIPS = [3, 4, 5, 6, 8]

# Filter thresholds to test
ADX_THRESHOLDS = [None, 20, 25, 30]  # None = no filter


def init_mt5():
    if not mt5.initialize():
        sys.exit(1)
    login = int(os.getenv("MT5_LOGIN", "0"))
    mt5.login(login, os.getenv("MT5_PASSWORD", ""), os.getenv("MT5_SERVER", ""))
    print(f"Connected: account {login}")


def fetch_data(symbol, days):
    now = datetime.now(timezone.utc)
    rates = mt5.copy_rates_range(symbol, TIMEFRAME, now - timedelta(days=days), now)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


def compute_session_adx(pre_session_bars: pd.DataFrame, period: int = 14) -> float:
    """Compute ADX from pre-session bars (simple approximation)."""
    if len(pre_session_bars) < period + 1:
        return 0

    highs = pre_session_bars["high"].values
    lows = pre_session_bars["low"].values
    closes = pre_session_bars["close"].values

    # True Range
    tr = np.maximum(highs[1:] - lows[1:],
                    np.maximum(abs(highs[1:] - closes[:-1]),
                               abs(lows[1:] - closes[:-1])))

    # +DM, -DM
    plus_dm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                       np.maximum(highs[1:] - highs[:-1], 0), 0)
    minus_dm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                        np.maximum(lows[:-1] - lows[1:], 0), 0)

    if len(tr) < period:
        return 0

    # Smoothed averages (Wilder's smoothing)
    atr = np.mean(tr[:period])
    plus_di_sum = np.mean(plus_dm[:period])
    minus_di_sum = np.mean(minus_dm[:period])

    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
        plus_di_sum = (plus_di_sum * (period - 1) + plus_dm[i]) / period
        minus_di_sum = (minus_di_sum * (period - 1) + minus_dm[i]) / period

    if atr == 0:
        return 0
    plus_di = 100 * plus_di_sum / atr
    minus_di = 100 * minus_di_sum / atr
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0
    dx = 100 * abs(plus_di - minus_di) / di_sum
    return dx


def build_sessions(df: pd.DataFrame, symbol: str, pip_val: float) -> list:
    """Extract Asian sessions with pre-session context for filtering."""
    sessions = []
    df["date"] = df.index.date

    for date, group in df.groupby("date"):
        asian = group[(group.index.hour >= SESSION_START_H) &
                      (group.index.hour < SESSION_END_H)]
        if len(asian) < 10 or asian.index[0].weekday() >= 5:
            continue

        # Pre-session bars (previous 4 hours) for ADX calculation
        session_start = asian.index[0]
        pre_start = session_start - timedelta(hours=6)
        pre_session = df[(df.index >= pre_start) & (df.index < session_start)]

        adx = compute_session_adx(pre_session)

        # Session ATR (average bar range during session)
        bar_ranges = (asian["high"] - asian["low"]) / pip_val
        session_atr = bar_ranges.mean()

        session_open = asian.iloc[0]["open"]
        avg_spread = asian["spread"].mean() / 10.0 if "spread" in asian.columns else 0
        session_range = (asian["high"].max() - asian["low"].min()) / pip_val

        # Bar-by-bar data relative to open
        bars = []
        for ts, bar in asian.iterrows():
            bars.append({
                "hour": ts.hour,
                "high_pips": (bar["high"] - session_open) / pip_val,
                "low_pips": (bar["low"] - session_open) / pip_val,
                "close_pips": (bar["close"] - session_open) / pip_val,
            })

        sessions.append({
            "date": date,
            "bars": bars,
            "spread": avg_spread,
            "range": session_range,
            "adx": adx,
            "atr": session_atr,
        })

    return sessions


def simulate(sessions, trigger, target, stop, adx_max=None,
             max_trades=4, cooldown=2, trading_start_h=1):
    """Run trade simulation with filters."""
    trades = []

    for session in sessions:
        # ADX filter
        if adx_max is not None and session["adx"] > adx_max:
            continue

        bars = session["bars"]
        spread = session["spread"]
        session_trades = 0
        last_trade_bar = -999

        for i, bar in enumerate(bars):
            if session_trades >= max_trades:
                break
            if (i - last_trade_bar) < cooldown:
                continue
            # Only trade after trading_start_h
            if bar["hour"] < trading_start_h:
                continue

            # SHORT trigger (price drifted up)
            if bar["high_pips"] >= trigger:
                result = resolve(bars[i+1:], "SHORT", trigger,
                                 target, trigger + stop, spread)
                trades.append(result)
                session_trades += 1
                last_trade_bar = i

            # LONG trigger (price drifted down)
            if bar["low_pips"] <= -trigger:
                result = resolve(bars[i+1:], "LONG", -trigger,
                                 -target, -(trigger + stop), spread)
                trades.append(result)
                session_trades += 1
                last_trade_bar = i

    return summarize(trades)


def resolve(remaining, direction, entry, tp_level, sl_level, spread):
    for bar in remaining:
        if direction == "LONG":
            if bar["high_pips"] >= tp_level:
                return {"pnl": abs(entry - tp_level) - spread, "exit": "TP"}
            if bar["low_pips"] <= sl_level:
                return {"pnl": -(abs(entry - sl_level) + spread), "exit": "SL"}
        else:
            if bar["low_pips"] <= tp_level:
                return {"pnl": abs(entry - tp_level) - spread, "exit": "TP"}
            if bar["high_pips"] >= sl_level:
                return {"pnl": -(abs(entry - sl_level) + spread), "exit": "SL"}
    # Time exit
    if remaining:
        last = remaining[-1]["close_pips"]
        if direction == "LONG":
            pnl = (last - entry) - spread
        else:
            pnl = (entry - last) - spread
        return {"pnl": pnl, "exit": "TIME"}
    return {"pnl": -spread, "exit": "TIME"}


def summarize(trades):
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "exp": 0, "aw": 0, "al": 0,
                "total": 0, "max_dd": 0, "tp_pct": 0, "sl_pct": 0, "time_pct": 0}
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins) if wins else 0
    gl = abs(sum(t["pnl"] for t in losses)) if losses else 0.001

    # Max drawdown in pips
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    tp_count = sum(1 for t in trades if t["exit"] == "TP")
    sl_count = sum(1 for t in trades if t["exit"] == "SL")
    time_count = sum(1 for t in trades if t["exit"] == "TIME")

    return {
        "n": len(trades),
        "wr": len(wins) / len(trades),
        "pf": gp / gl,
        "exp": np.mean([t["pnl"] for t in trades]),
        "aw": np.mean([t["pnl"] for t in wins]) if wins else 0,
        "al": np.mean([t["pnl"] for t in losses]) if losses else 0,
        "total": sum(t["pnl"] for t in trades),
        "max_dd": max_dd,
        "tp_pct": tp_count / len(trades) * 100,
        "sl_pct": sl_count / len(trades) * 100,
        "time_pct": time_count / len(trades) * 100,
    }


def main():
    init_mt5()

    for symbol in PAIRS:
        print(f"\n{'='*80}")
        print(f"  {symbol}")
        print(f"{'='*80}")

        df = fetch_data(symbol, LOOKBACK_DAYS)
        if df.empty:
            print("  No data")
            continue

        pip_val = PIP_VALUES[symbol]
        sessions = build_sessions(df, symbol, pip_val)
        print(f"  {len(sessions)} sessions, {len(df)} M15 bars")

        # Test all combinations with each ADX filter
        for adx_max in ADX_THRESHOLDS:
            adx_label = f"ADX<={adx_max}" if adx_max else "No filter"
            filtered = [s for s in sessions if adx_max is None or s["adx"] <= adx_max]
            skip_pct = (1 - len(filtered) / len(sessions)) * 100 if sessions else 0

            print(f"\n  --- {adx_label} ({len(filtered)} sessions, {skip_pct:.0f}% skipped) ---")
            print(f"  {'Trig':>5} {'Tgt':>4} {'SL':>4} {'Trades':>7} {'WR':>5} "
                  f"{'PF':>5} {'Exp':>7} {'Total':>7} {'MaxDD':>6} "
                  f"{'TP%':>5} {'SL%':>5} {'Time%':>5}")

            best_exp = -999
            best_row = None
            all_results = []

            for trigger in TRIGGER_PIPS:
                for target in TARGET_PIPS:
                    if target > trigger + 2:
                        continue  # target can't be much larger than trigger
                    for stop in STOP_PIPS:
                        r = simulate(filtered, trigger, target, stop, adx_max=None)
                        if r["n"] == 0:
                            continue
                        all_results.append((trigger, target, stop, r))
                        if r["exp"] > best_exp:
                            best_exp = r["exp"]
                            best_row = (trigger, target, stop, r)

            # Show top 10 by expectancy
            all_results.sort(key=lambda x: x[3]["exp"], reverse=True)
            for trig, tgt, sl, r in all_results[:10]:
                marker = " <--" if r["exp"] > 0 else ""
                print(f"  {trig:>4}p {tgt:>3}p {sl:>3}p {r['n']:>7} {r['wr']*100:>4.0f}% "
                      f"{r['pf']:>5.2f} {r['exp']:>+6.1f}p {r['total']:>+6.0f}p "
                      f"{r['max_dd']:>5.0f}p {r['tp_pct']:>4.0f}% {r['sl_pct']:>4.0f}% "
                      f"{r['time_pct']:>4.0f}%{marker}")

            if best_row and best_row[3]["exp"] > 0:
                trig, tgt, sl, r = best_row
                print(f"\n  BEST: {trig}p/{tgt}p/{sl}p -> WR={r['wr']*100:.0f}% "
                      f"PF={r['pf']:.2f} Exp={r['exp']:+.2f}p "
                      f"Total={r['total']:+.0f}p MaxDD={r['max_dd']:.0f}p "
                      f"({r['n']} trades)")

                # Position sizing analysis
                print(f"\n  Position sizing at various risk levels (10k account, {sl}p stop):")
                for risk_pct in [0.5, 1.0, 1.5, 2.0, 3.0]:
                    risk_usd = 10000 * risk_pct / 100
                    lots = risk_usd / (sl * 10)  # $10/pip/lot for standard
                    annual_pnl = r["total"] * lots * 10  # pips * lots * $/pip
                    annual_ret = annual_pnl / 10000 * 100
                    max_dd_usd = r["max_dd"] * lots * 10
                    max_dd_pct = max_dd_usd / 10000 * 100
                    print(f"    {risk_pct}% risk -> {lots:.2f} lots, "
                          f"annual ~${annual_pnl:+,.0f} ({annual_ret:+.0f}%), "
                          f"max DD ~${max_dd_usd:,.0f} ({max_dd_pct:.1f}%)")

    mt5.shutdown()
    print(f"\n{'='*80}")
    print("Done.")


if __name__ == "__main__":
    main()
