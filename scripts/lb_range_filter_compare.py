"""Compare LB range-filter variants: pure bid-range vs spread-adjusted.

Three variants on the 12-20p qualifying window:
  bid       : raw bid-range (current)
  subtract  : effective range = bid_range - spread (loosens qualifier)
  add       : effective range = bid_range + 2×spread (tightens qualifier; accounts
              for entry+SL spread overhead)

Same simulation logic for all variants — entry on bar high/low > asian_high+spread
(LONG) or < asian_low-spread (SHORT), TP at 1× range from entry, SL at the
opposite Asian extreme, exit at 13:00 UTC if open.
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
SPREAD = 1.0           # matches LONDON_BREAKOUT.spread_pips in config
MIN_RANGE = 12
MAX_RANGE = 20
TP_MULT = 1.0          # TP at 1× Asian range
DAYS_MASK = [0, 1]     # Monday + Tuesday only
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


def qualifier(bid_range, mode):
    if mode == "bid":
        eff = bid_range
    elif mode == "subtract":
        eff = bid_range - SPREAD
    elif mode == "add":
        eff = bid_range + 2 * SPREAD
    else:
        raise ValueError(mode)
    return MIN_RANGE <= eff <= MAX_RANGE


def simulate(sessions, mode):
    trades = []
    qualified = 0
    skipped_below = 0
    skipped_above = 0
    for sd in sorted(sessions):
        s = sessions[sd]
        if s["bid_range_pips"] == 0:
            continue
        # Determine effective range for the qualifier
        bid_range = s["bid_range_pips"]
        if mode == "bid":
            eff = bid_range
        elif mode == "subtract":
            eff = bid_range - SPREAD
        elif mode == "add":
            eff = bid_range + 2 * SPREAD
        if eff < MIN_RANGE:
            skipped_below += 1
            continue
        if eff > MAX_RANGE:
            skipped_above += 1
            continue
        qualified += 1

        ah = s["asian_high"]
        al = s["asian_low"]
        rng = ah - al
        trading = [b for b in s["bars"] if 8 <= b["h"] < EXIT_HOUR]
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
                        trades.append({"d": sd, "pnl": (sl_p - ep) / PIP - SPREAD, "x": "SL", "dir": "LONG"})
                        done = True; continue
                    if b["hi"] >= tp:
                        trades.append({"d": sd, "pnl": (tp - ep) / PIP - SPREAD, "x": "TP", "dir": "LONG"})
                        done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": sd, "pnl": (ep - sl_p) / PIP - SPREAD, "x": "SL", "dir": "SHORT"})
                        done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": sd, "pnl": (ep - tp) / PIP - SPREAD, "x": "TP", "dir": "SHORT"})
                        done = True; continue
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
            trades.append({"d": sd, "pnl": pnl, "x": "TIME", "dir": "LONG" if d_dir == "L" else "SHORT"})
    return trades, qualified, skipped_below, skipped_above


def stats(trades):
    if not trades:
        return None
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    return {"n": len(trades), "wr": w / len(trades) * 100, "pf": gp / gl,
            "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd}


print("Loading GBPUSD H1 sessions (Mon/Tue only)...")
sessions = load_sessions()
print(f"  {len(sessions)} Mon/Tue sessions, {min(sessions)} → {max(sessions)}")

print()
print("=" * 100)
print(f"{'Variant':<28} {'Qual':>5} {'<min':>5} {'>max':>5} {'N':>5} {'WR':>5} {'PF':>6} {'Exp':>7} {'Tot':>9} {'DD':>6}")
print("-" * 100)

for mode, label, desc in [
    ("bid",      "1) Pure bid-range (current)",  "12 ≤ bid_range ≤ 20"),
    ("subtract", "2) Subtract spread",          "12 ≤ bid_range − 1 ≤ 20"),
    ("add",      "3) Add 2×spread",             "12 ≤ bid_range + 2 ≤ 20"),
]:
    trades, q, sb, sa = simulate(sessions, mode)
    s = stats(trades)
    if s is None:
        print(f"{label:<28} {q:>5} {sb:>5} {sa:>5}  no trades")
        continue
    print(f"{label:<28} {q:>5} {sb:>5} {sa:>5} {s['n']:>5} {s['wr']:>4.0f}% {s['pf']:>6.2f} {s['exp']:>+7.2f} {s['tot']:>+9.0f}p {s['dd']:>5.0f}p")

# Show range distribution
ranges = sorted([s["bid_range_pips"] for s in sessions.values() if s["bid_range_pips"] > 0])
arr = np.array(ranges)
print(f"\nGBPUSD Asian range distribution (n={len(arr)}): "
      f"p10={np.percentile(arr,10):.1f}  p25={np.percentile(arr,25):.1f}  "
      f"median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  "
      f"p90={np.percentile(arr,90):.1f}  max={arr.max():.1f}")
