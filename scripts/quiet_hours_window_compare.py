"""Compare 4 window-handling strategies under a realistic spread model.

The original Quiet-Hours BB+RSI backtest assumed flat 1.3-2.0p spread. Live
sampling shows a 15-22p spike at the NY-rollover hour (21:00 UTC during DST,
22:00 UTC during EST). This script models that spike and compares:

  baseline       : Fixed 22-01 UTC year-round (ignores winter spike)
  dynamic        : Summer 22-01, Winter 23-01 (skip the spike hour each season)
  skip30         : 30-min lag after rollover (Sum 21:30-01:00, Win 22:30-01:00)
  spread_filter  : Window 21-01, runtime spread filter rejects entries > 5p

Strategy: BB(20,2) + RSI(14) mean reversion on M15.
Pairs: AUDNZD, NZDCAD, AUDCAD, EURCHF.
SL: 12p fixed. TP: BB middle band. MaxHold: 16 bars.
"""
import os
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backtests", "data")

PAIRS = ["AUDNZD", "NZDCAD", "AUDCAD", "EURCHF"]
PIP = 0.0001

# Live-measured spreads at non-rollover hours (median from 2026-04-27 sampling)
NORMAL_SPREAD = {"AUDNZD": 1.7, "NZDCAD": 1.5, "AUDCAD": 1.3, "EURCHF": 1.5}
# Live-measured median spread at the rollover hour (21:00 UTC sample)
SPIKE_SPREAD = {"AUDNZD": 21.7, "NZDCAD": 15.3, "AUDCAD": 12.6, "EURCHF": 16.3}

BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 70
SL_PIPS = 12
MAX_HOLD_BARS = 16
SPREAD_FILTER_MAX = 5.0  # Option C threshold


# ── DST detection ──────────────────────────────────────────────────────────
def is_us_dst(dt):
    """US DST: 2nd Sunday of March → 1st Sunday of November."""
    y = dt.year
    march_2nd_sun = pd.Timestamp(f"{y}-03-01") + pd.offsets.Week(weekday=6) * 2
    nov_1st_sun = pd.Timestamp(f"{y}-11-01") + pd.offsets.Week(weekday=6) * 1
    if march_2nd_sun.day == 1:  # if Mar 1 is Sunday, n=2 lands on day 15 — recompute
        march_2nd_sun = pd.Timestamp(f"{y}-03-08")
    if nov_1st_sun.day == 1:
        nov_1st_sun = pd.Timestamp(f"{y}-11-01")
    march_2nd_sun = march_2nd_sun.replace(hour=2)
    nov_1st_sun = nov_1st_sun.replace(hour=2)
    return march_2nd_sun.tz_localize("UTC") <= dt.tz_convert("UTC") < nov_1st_sun.tz_localize("UTC")


def rollover_hour(dt):
    """21 UTC during US DST, 22 UTC otherwise."""
    return 21 if is_us_dst(dt) else 22


# ── Per-mode gating ────────────────────────────────────────────────────────
def in_window(bar_time, mode):
    """True if a new entry is allowed at this bar."""
    h = bar_time.hour
    m = bar_time.minute
    rh = rollover_hour(bar_time)

    if mode == "baseline":
        # Fixed 22-01 year-round (ignores winter spike)
        return h >= 22 or h < 1

    if mode == "dynamic":
        # Skip the entire rollover hour, regardless of season
        if rh == 21:  # summer
            return h >= 22 or h < 1
        else:         # winter rollover at 22 → trade 23-01 only
            return h >= 23 or h < 1

    if mode == "skip30":
        # 30 min lag after rollover. M15 grid → first allowed bar is rh:30
        # Summer: 21:30 onward to 01:00. Winter: 22:30 onward to 01:00.
        if h == rh:
            return m >= 30
        if rh == 21:
            return h >= 22 or h < 1 or (h == 21 and m >= 30)
        else:
            return h >= 23 or h < 1 or (h == 22 and m >= 30)

    if mode == "spread_filter":
        # Wide window (21-01). Spread filter applied separately.
        return h >= 21 or h < 1

    raise ValueError(mode)


def get_spread(bar_time, symbol):
    """Return the spread (in pips) for a given bar's hour and symbol."""
    if bar_time.hour == rollover_hour(bar_time):
        return SPIKE_SPREAD[symbol]
    return NORMAL_SPREAD[symbol]


def passes_spread_filter(bar_time, symbol, mode):
    """Runtime spread filter: only used by 'spread_filter' mode."""
    if mode != "spread_filter":
        return True
    return get_spread(bar_time, symbol) <= SPREAD_FILTER_MAX


# ── Indicators + simulation ────────────────────────────────────────────────
def add_indicators(df):
    closes = df["close"]
    df["bb_mid"] = closes.rolling(BB_PERIOD).mean()
    df["bb_std"] = closes.rolling(BB_PERIOD).std()
    df["bb_upper"] = df["bb_mid"] + BB_STD * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - BB_STD * df["bb_std"]
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, 1e-9)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def load(symbol):
    path = os.path.join(DATA_DIR, f"{symbol}_M15.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


def simulate(symbol, mode):
    df = load(symbol)
    if df is None:
        return []
    df = add_indicators(df).dropna(subset=["bb_mid", "rsi"]).reset_index(drop=True)

    trades = []
    open_trade = None  # (dir, entry, tp, sl, entry_idx, entry_spread)

    for i in range(len(df)):
        bar = df.iloc[i]

        # Manage open trade (uses entry-time spread, not exit-bar spread —
        # spread is paid at entry only since TP/SL are price levels)
        if open_trade is not None:
            d, ep, tp, sl, ei, sp = open_trade
            held = i - ei
            closed = False
            if d == "L":
                if bar["low"] <= sl:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (sl - ep) / PIP - sp, "x": "SL"})
                    closed = True
                elif bar["high"] >= tp:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (tp - ep) / PIP - sp, "x": "TP"})
                    closed = True
            else:
                if bar["high"] >= sl:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (ep - sl) / PIP - sp, "x": "SL"})
                    closed = True
                elif bar["low"] <= tp:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (ep - tp) / PIP - sp, "x": "TP"})
                    closed = True
            if not closed and held >= MAX_HOLD_BARS:
                pnl = (bar["close"] - ep) / PIP if d == "L" else (ep - bar["close"]) / PIP
                trades.append({"d": bar["time"].date(), "sym": symbol,
                               "pnl": pnl - sp, "x": "TIME"})
                closed = True
            if closed:
                open_trade = None

        # New entry
        if open_trade is None and in_window(bar["time"], mode) \
                and passes_spread_filter(bar["time"], symbol, mode):
            sp = get_spread(bar["time"], symbol)
            if bar["close"] < bar["bb_lower"] and bar["rsi"] < RSI_LOWER:
                ep = bar["close"]
                tp = bar["bb_mid"]
                if (tp - ep) / PIP > sp + 1:
                    open_trade = ("L", ep, tp, ep - SL_PIPS * PIP, i, sp)
            elif bar["close"] > bar["bb_upper"] and bar["rsi"] > RSI_UPPER:
                ep = bar["close"]
                tp = bar["bb_mid"]
                if (ep - tp) / PIP > sp + 1:
                    open_trade = ("S", ep, tp, ep + SL_PIPS * PIP, i, sp)

    return trades


def stats(trades, label):
    if not trades:
        return None
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    return {"label": label, "n": len(trades), "wr": w / len(trades) * 100,
            "pf": gp / gl, "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd}


# ── Run all modes ───────────────────────────────────────────────────────────
print("Quiet-Hours BB+RSI — Window-Handling Strategy Comparison")
print(f"Spread model: spike={SPIKE_SPREAD} normal={NORMAL_SPREAD}")
print("=" * 100)
print(f"{'Mode':<16} {'N':>5} {'WR':>5} {'PF':>5} {'Exp':>6} {'Total':>9} {'DD':>5} {'Notes'}")
print("-" * 100)

modes = ["baseline", "dynamic", "skip30", "spread_filter"]
notes = {
    "baseline": "22-01 fixed (ignores winter spike — bleeds on EST trades)",
    "dynamic": "Sum 22-01, Win 23-01 (skip whole rollover hour)",
    "skip30": "Sum 21:30-01, Win 22:30-01 (recover most of the hour)",
    "spread_filter": "21-01 + runtime spread<=5p filter (universal)",
}
for mode in modes:
    all_trades = []
    for sym in PAIRS:
        all_trades.extend(simulate(sym, mode))
    s = stats(all_trades, mode)
    if s:
        print(f"{mode:<16} {s['n']:>5d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
              f"{s['exp']:>+5.2f}p {s['tot']:>+8.0f}p {s['dd']:>4.0f}p  {notes[mode]}")

print()
print("Yearly breakdown for spread_filter mode:")
all_trades = []
for sym in PAIRS:
    all_trades.extend(simulate(sym, "spread_filter"))
yearly = defaultdict(list)
for t in all_trades:
    yearly[t["d"].year].append(t["pnl"])
for y in sorted(yearly):
    arr = yearly[y]
    w = sum(1 for p in arr if p > 0)
    print(f"  {y}: n={len(arr):3d}  WR={w/len(arr)*100:.0f}%  Tot={sum(arr):+.0f}p")
