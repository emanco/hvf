"""Compare QL fixed 7p trigger vs dynamic ADR-based trigger.

Loads local EURGBP_M5.csv, simulates both versions on the same sessions,
prints stats side-by-side and saves an equity-curve chart.
"""
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict, deque
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "backtests", "data", "EURGBP_M5.csv")
CHARTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "backtests", "charts")

PIP = 0.0001
SPREAD = 1.0           # 1.0p typical EURGBP demo spread (matches existing backtest)
TARGET = 5
STOP = 18
DAYS_MASK = [0, 1, 2, 3, 4]   # Mon-Fri (current QL config)
EXIT_HOUR = 5
MAX_RANGE = 20         # max_range_pips filter (=20 in current config but 999 in live; using 20 to match historical backtest)

# ADR config
ADR_LOOKBACK = 10      # last 10 trading days
ADR_PCT = 0.40         # trigger = 40% of asian-session ADR
ADR_MIN = 5
ADR_MAX = 12
FIXED_TRIGGER = 7      # current setting

# Capture window: 22:00 UTC of day N → Asian-DR window is 22:00 day N to 05:00 day N+1
# Trading window: 00:00–05:00 UTC of day N+1


def load_sessions():
    df = pd.read_csv(DATA)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    sessions = {}
    # Group by "session date" = the trading-day part of the window (i.e. the day after the 22:00 capture)
    for _, row in df.iterrows():
        ts = row["time"]
        h = ts.hour
        if h >= 22:
            # Capture-night bars: belong to NEXT day's session
            sd = (ts + pd.Timedelta(days=1)).date()
        elif h < 6:
            sd = ts.date()
        else:
            continue
        if sd not in sessions:
            sessions[sd] = {"wd": None, "open": None, "bars": []}
        sessions[sd]["bars"].append({
            "h": h, "m": ts.minute,
            "o": row["open"], "hi": row["high"], "lo": row["low"], "cl": row["close"],
            "ts": ts,
        })
    # Compute open + asian-session range per session
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda x: x["ts"])
        # Capture price = open of bar at 22:00 UTC the day before
        cap_bars = [b for b in s["bars"] if b["h"] >= 22]
        if cap_bars:
            s["open"] = cap_bars[0]["o"]
        # Asian-session range = max(hi) - min(lo) across whole window 22:00 prev → 05:00 today
        all_window = [b for b in s["bars"] if b["h"] >= 22 or b["h"] < EXIT_HOUR]
        if all_window:
            hi = max(b["hi"] for b in all_window)
            lo = min(b["lo"] for b in all_window)
            s["asian_range_pips"] = (hi - lo) / PIP
        else:
            s["asian_range_pips"] = 0
        # Weekday of the trading day
        s["wd"] = sd.weekday()
    return sessions


def compute_adr(sessions, target_date, lookback=ADR_LOOKBACK):
    """Average asian-session range over the last N completed sessions before target_date."""
    prior = sorted([d for d in sessions if d < target_date])
    if len(prior) < lookback:
        return None
    recent = prior[-lookback:]
    ranges = [sessions[d]["asian_range_pips"] for d in recent if sessions[d]["asian_range_pips"] > 0]
    if not ranges:
        return None
    return sum(ranges) / len(ranges)


def trigger_for_session(sessions, sd, mode):
    if mode == "fixed":
        return FIXED_TRIGGER
    elif mode == "adr":
        adr = compute_adr(sessions, sd)
        if adr is None:
            return FIXED_TRIGGER
        t = adr * ADR_PCT
        return max(ADR_MIN, min(ADR_MAX, t))
    raise ValueError(mode)


def simulate(sessions, mode):
    trades = []
    for sd in sorted(sessions):
        s = sessions[sd]
        if s["open"] is None:
            continue
        if s["wd"] not in DAYS_MASK:
            continue
        if s["asian_range_pips"] > MAX_RANGE:
            continue
        trig = trigger_for_session(sessions, sd, mode)
        so = s["open"]
        # Trading bars 00:00–EXIT_HOUR UTC on session date
        trading = [b for b in s["bars"] if 0 <= b["h"] < EXIT_HOUR]
        if not trading:
            continue
        ot = None
        done = False
        for b in trading:
            if done:
                continue
            if ot:
                d_dir, ep, tp, sl_p = ot
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": sd, "pnl": (sl_p - ep) / PIP - SPREAD, "x": "SL", "dir": "LONG", "trig": trig})
                        done = True; continue
                    if b["hi"] >= tp:
                        trades.append({"d": sd, "pnl": (tp - ep) / PIP - SPREAD, "x": "TP", "dir": "LONG", "trig": trig})
                        done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": sd, "pnl": (ep - sl_p) / PIP - SPREAD, "x": "SL", "dir": "SHORT", "trig": trig})
                        done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": sd, "pnl": (ep - tp) / PIP - SPREAD, "x": "TP", "dir": "SHORT", "trig": trig})
                        done = True; continue
            else:
                if b["lo"] <= so - trig * PIP:
                    ep = so - trig * PIP
                    ot = ("L", ep, ep + TARGET * PIP, ep - STOP * PIP)
                elif b["hi"] >= so + trig * PIP:
                    ep = so + trig * PIP
                    ot = ("S", ep, ep - TARGET * PIP, ep + STOP * PIP)
        if ot and not done:
            d_dir, ep, tp, sl_p = ot
            last = trading[-1]
            pnl = (last["cl"] - ep) / PIP - SPREAD if d_dir == "L" else (ep - last["cl"]) / PIP - SPREAD
            trades.append({"d": sd, "pnl": pnl, "x": "TIME", "dir": "LONG" if d_dir == "L" else "SHORT", "trig": trig})
    return trades


def stats(trades, label):
    if not trades:
        return f"{label}: no trades"
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
    return {
        "label": label, "n": len(trades), "wr": w / len(trades) * 100,
        "pf": gp / gl, "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd, "cl": mc,
        "trigs": [t["trig"] for t in trades],
    }


print("Loading EURGBP M5 sessions...")
sessions = load_sessions()
print(f"  {len(sessions)} sessions, {min(sessions)} → {max(sessions)}")

print("\nRunning fixed 7p simulation...")
trades_fixed = simulate(sessions, "fixed")
s_fixed = stats(trades_fixed, "Fixed 7p")

print("Running ADR-based simulation (40% of 10-day Asian ADR, clamped 5-12p)...")
trades_adr = simulate(sessions, "adr")
s_adr = stats(trades_adr, "ADR adaptive")

print("\n" + "=" * 90)
print(f"{'Variant':<22} {'N':>5} {'WR':>5} {'PF':>6} {'Exp':>7} {'Tot':>9} {'DD':>7} {'CL':>4}")
print("-" * 90)
for s in (s_fixed, s_adr):
    print(f"{s['label']:<22} {s['n']:>5} {s['wr']:>4.0f}% {s['pf']:>6.2f} {s['exp']:>+7.2f} {s['tot']:>+9.0f}p {s['dd']:>6.0f}p {s['cl']:>4d}")

# Trigger distribution stats
if s_adr["trigs"]:
    arr = np.array(s_adr["trigs"])
    print(f"\nADR trigger distribution: min={arr.min():.1f} median={np.median(arr):.1f} mean={arr.mean():.1f} max={arr.max():.1f}p")

# Equity curves
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(13, 6))
for trades, label, color in [(trades_fixed, "Fixed 7p", "tab:blue"),
                              (trades_adr, "ADR adaptive", "tab:orange")]:
    if not trades:
        continue
    ts = sorted(trades, key=lambda x: x["d"])
    dates = [t["d"] for t in ts]
    eq = np.cumsum([t["pnl"] for t in ts])
    ax.plot(dates, eq, label=f"{label} (n={len(ts)}, PF={s_fixed['pf'] if 'Fixed' in label else s_adr['pf']:.2f}, Tot={sum(t['pnl'] for t in ts):.0f}p)",
            color=color, linewidth=1.5)

ax.axhline(0, color="k", linewidth=0.5)
ax.set_title("Quantum London — fixed 7p vs ADR-adaptive trigger (EURGBP M5)")
ax.set_ylabel("Cumulative pips")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
out = os.path.join(CHARTS, "ql_trigger_compare.png")
fig.savefig(out, dpi=110)
print(f"\nChart: {out}")
