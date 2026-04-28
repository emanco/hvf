"""Quiet-Hours Mean Reversion (BB + RSI) backtest — first pass.

Concept: trade mean-reversion on cross pairs during 21:00-01:00 GMT (low-liquidity
window). Entry when price closes outside Bollinger Bands(20, 2) AND RSI(14) is
extreme. TP at the BB middle band, fixed SL.

Refs: ForexFactory threads #604951 (Extremely Accurate EA), #641507 (Night Owl).

Pairs: AUDNZD, NZDCAD, AUDCAD, EURCHF.
Timeframe: M15.
Window: 21:00-01:00 UTC.
"""
import os
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backtests", "data")
CHARTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "backtests", "charts")

PAIRS = ["AUDNZD", "NZDCAD", "AUDCAD", "EURCHF"]
PIP = 0.0001  # all are 4-digit
SPREAD_PIPS = {"AUDNZD": 1.5, "NZDCAD": 2.0, "AUDCAD": 1.5, "EURCHF": 1.5}

BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 70
WINDOW_START = 21   # UTC hour
WINDOW_END = 1      # UTC hour (next day, so window is 21:00-25:00 effectively)
SL_PIPS = 12
MAX_HOLD_BARS = 16  # 4 hours at M15 — force-close stale trades


def load(symbol):
    path = os.path.join(DATA_DIR, f"{symbol}_M15.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df


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


def in_window(hour):
    if WINDOW_START <= WINDOW_END:
        return WINDOW_START <= hour < WINDOW_END
    return hour >= WINDOW_START or hour < WINDOW_END


def simulate(symbol):
    df = load(symbol)
    if df is None:
        return None
    df = add_indicators(df).dropna(subset=["bb_mid", "rsi"]).reset_index(drop=True)
    spread = SPREAD_PIPS[symbol]

    trades = []
    open_trade = None  # (direction, entry, tp, sl, entry_idx)

    for i in range(len(df)):
        bar = df.iloc[i]
        # Manage open trade
        if open_trade is not None:
            d_dir, ep, tp, sl, ei = open_trade
            held = i - ei
            if d_dir == "L":
                if bar["low"] <= sl:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (sl - ep) / PIP - spread, "x": "SL", "dir": "L"})
                    open_trade = None
                elif bar["high"] >= tp:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (tp - ep) / PIP - spread, "x": "TP", "dir": "L"})
                    open_trade = None
            else:
                if bar["high"] >= sl:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (ep - sl) / PIP - spread, "x": "SL", "dir": "S"})
                    open_trade = None
                elif bar["low"] <= tp:
                    trades.append({"d": bar["time"].date(), "sym": symbol,
                                   "pnl": (ep - tp) / PIP - spread, "x": "TP", "dir": "S"})
                    open_trade = None
            if open_trade is not None and held >= MAX_HOLD_BARS:
                # Force close at this bar's close
                if d_dir == "L":
                    pnl = (bar["close"] - ep) / PIP - spread
                else:
                    pnl = (ep - bar["close"]) / PIP - spread
                trades.append({"d": bar["time"].date(), "sym": symbol,
                               "pnl": pnl, "x": "TIME", "dir": d_dir})
                open_trade = None

        # Look for new entries (only if no open trade)
        if open_trade is None and in_window(bar["time"].hour):
            # LONG: close below lower BB and RSI < 30
            if bar["close"] < bar["bb_lower"] and bar["rsi"] < RSI_LOWER:
                ep = bar["close"]
                tp = bar["bb_mid"]
                sl = ep - SL_PIPS * PIP
                # Skip if TP-distance < spread (would lock-in loss)
                if (tp - ep) / PIP > spread + 1:
                    open_trade = ("L", ep, tp, sl, i)
            # SHORT: close above upper BB and RSI > 70
            elif bar["close"] > bar["bb_upper"] and bar["rsi"] > RSI_UPPER:
                ep = bar["close"]
                tp = bar["bb_mid"]
                sl = ep + SL_PIPS * PIP
                if (ep - tp) / PIP > spread + 1:
                    open_trade = ("S", ep, tp, sl, i)

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
    c = 0; mc = 0
    for p in pnls:
        if p <= 0: c += 1; mc = max(mc, c)
        else: c = 0
    return {"label": label, "n": len(trades), "wr": w / len(trades) * 100,
            "pf": gp / gl, "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd, "cl": mc}


print("Quiet-Hours BB+RSI Backtest (M15, 21:00-01:00 UTC)")
print("=" * 88)
all_trades = []
for sym in PAIRS:
    print(f"\nLoading {sym}...")
    trades = simulate(sym)
    if trades is None:
        print(f"  No data")
        continue
    s = stats(trades, sym)
    if s:
        print(f"  {sym}: n={s['n']} WR={s['wr']:.0f}% PF={s['pf']:.2f} Exp={s['exp']:+.2f} Tot={s['tot']:+.0f}p DD={s['dd']:.0f}p MaxCL={s['cl']}")
    all_trades.extend(trades)

if all_trades:
    s_combined = stats(all_trades, "COMBINED")
    print("\n" + "=" * 88)
    print("COMBINED:")
    print(f"  n={s_combined['n']} WR={s_combined['wr']:.0f}% PF={s_combined['pf']:.2f} "
          f"Exp={s_combined['exp']:+.2f}p Tot={s_combined['tot']:+.0f}p "
          f"DD={s_combined['dd']:.0f}p MaxCL={s_combined['cl']}")

    yearly = defaultdict(list)
    for t in all_trades:
        yearly[t["d"].year].append(t["pnl"])
    print("\nYearly (combined):")
    for y in sorted(yearly):
        arr = yearly[y]
        w = sum(1 for p in arr if p > 0)
        wr = w / len(arr) * 100
        print(f"  {y}: n={len(arr):3d}  WR={wr:.0f}%  Tot={sum(arr):+.0f}p")

    # Equity curve
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sorted_trades = sorted(all_trades, key=lambda x: x["d"])
    dates = [t["d"] for t in sorted_trades]
    eq = np.cumsum([t["pnl"] for t in sorted_trades])
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(dates, eq, color="tab:blue", linewidth=1.4)
    ax.axhline(0, color="k", linewidth=0.5)
    ax.fill_between(dates, eq, 0, where=eq >= 0, alpha=0.15, color="tab:green")
    ax.fill_between(dates, eq, 0, where=eq < 0, alpha=0.15, color="tab:red")
    ax.set_title(f"Quiet-Hours BB+RSI — {'+'.join(PAIRS)} M15 (n={s_combined['n']}, "
                 f"PF={s_combined['pf']:.2f}, Tot={s_combined['tot']:+.0f}p)")
    ax.set_ylabel("Cumulative pips")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = os.path.join(CHARTS, "quiet_hours_bbrsi_bt.png")
    fig.savefig(out, dpi=110)
    print(f"\nChart: {out}")
