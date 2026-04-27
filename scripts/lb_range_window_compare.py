"""Compare LB range qualifier windows over 8 years of GBPUSD.

Tests multiple [min, max] windows and reports trades/WR/PF/total/DD for each.
Uses the same simulation logic as the live LB strategy (entry on Asian range
breakout with spread, TP at 1× range, SL at opposite extreme).
"""
import os
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "backtests", "data", "GBPUSD_H1.csv")
CHARTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "backtests", "charts")

PIP = 0.0001
SPREAD = 1.0
TP_MULT = 1.0
DAYS_MASK = [0, 1]
EXIT_HOUR = 13


def load_sessions():
    df = pd.read_csv(DATA)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    sessions = defaultdict(lambda: {"bars": []})
    for _, row in df.iterrows():
        ts = row["time"]
        if ts.weekday() not in DAYS_MASK:
            continue
        if ts.hour >= EXIT_HOUR:
            continue
        sd = ts.date()
        sessions[sd]["bars"].append({
            "h": ts.hour, "o": row["open"], "hi": row["high"],
            "lo": row["low"], "cl": row["close"], "ts": ts,
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda x: x["ts"])
        formation = [b for b in s["bars"] if b["h"] < 7]
        if formation:
            s["asian_high"] = max(b["hi"] for b in formation)
            s["asian_low"] = min(b["lo"] for b in formation)
            s["bid_range_pips"] = (s["asian_high"] - s["asian_low"]) / PIP
        else:
            s["bid_range_pips"] = 0
        s["wd"] = sd.weekday()
    return sessions


def simulate(sessions, min_r, max_r):
    trades = []
    qualified = 0
    for sd in sorted(sessions):
        s = sessions[sd]
        rng_pips = s["bid_range_pips"]
        if rng_pips == 0:
            continue
        if rng_pips < min_r or rng_pips > max_r:
            continue
        qualified += 1
        ah = s["asian_high"]
        al = s["asian_low"]
        rng = ah - al
        trading = [b for b in s["bars"] if 8 <= b["h"] < EXIT_HOUR]
        if not trading:
            continue
        ot = None; done = False
        for b in trading:
            if done: continue
            if ot:
                d_dir, ep, tp, sl_p = ot
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": sd, "pnl": (sl_p - ep) / PIP - SPREAD, "x": "SL"}); done = True; continue
                    if b["hi"] >= tp:
                        trades.append({"d": sd, "pnl": (tp - ep) / PIP - SPREAD, "x": "TP"}); done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": sd, "pnl": (ep - sl_p) / PIP - SPREAD, "x": "SL"}); done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": sd, "pnl": (ep - tp) / PIP - SPREAD, "x": "TP"}); done = True; continue
            else:
                if b["hi"] > ah + SPREAD * PIP:
                    ep = ah + SPREAD * PIP
                    ot = ("L", ep, ep + TP_MULT * rng, al - SPREAD * PIP)
                elif b["lo"] < al - SPREAD * PIP:
                    ep = al - SPREAD * PIP
                    ot = ("S", ep, ep - TP_MULT * rng, ah + SPREAD * PIP)
        if ot and not done:
            d_dir, ep, tp, sl_p = ot
            last = trading[-1]
            pnl = (last["cl"] - ep) / PIP - SPREAD if d_dir == "L" else (ep - last["cl"]) / PIP - SPREAD
            trades.append({"d": sd, "pnl": pnl, "x": "TIME"})
    return trades, qualified


def stats(trades):
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "exp": 0, "tot": 0, "dd": 0}
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    return {"n": len(trades), "wr": w / len(trades) * 100,
            "pf": gp / gl, "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd}


print("Loading GBPUSD H1 sessions (Mon/Tue only)...")
sessions = load_sessions()
print(f"  {len(sessions)} Mon/Tue sessions, {min(sessions)} → {max(sessions)}")

# Range distribution context
ranges = sorted([s["bid_range_pips"] for s in sessions.values() if s["bid_range_pips"] > 0])
arr = np.array(ranges)
print(f"  Range distribution: p10={np.percentile(arr,10):.1f}  p25={np.percentile(arr,25):.1f}  "
      f"median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}")

# Test windows
windows = [
    ("Current 12-20p",    12,  20),
    ("Slightly wider 15-30",  15, 30),
    ("Centered 20-40",    20,  40),
    ("Centered+ 25-45",   25,  45),
    ("Wide 30-50",        30,  50),
    ("Below median 12-30", 12, 30),
    ("Loose min only 12+", 12, 999),
    ("Higher floor 20+",   20, 999),
    ("Strict tight 12-15", 12, 15),
    ("Quiet only 8-15",    8,  15),
]

print()
print("=" * 100)
print(f"{'Window':<22} {'Qual':>5} {'Q%':>5} {'N':>4} {'WR':>5} {'PF':>6} {'Exp':>7} {'Tot':>9} {'DD':>6}")
print("-" * 100)
total = len(sessions)
for label, mn, mx in windows:
    trades, q = simulate(sessions, mn, mx)
    s = stats(trades)
    qpct = q / total * 100
    if s["n"] == 0:
        print(f"{label:<22} {q:>5} {qpct:>4.0f}%  no trades")
        continue
    print(f"{label:<22} {q:>5} {qpct:>4.0f}% {s['n']:>4} {s['wr']:>4.0f}% {s['pf']:>6.2f} {s['exp']:>+7.2f} {s['tot']:>+9.0f}p {s['dd']:>5.0f}p")
