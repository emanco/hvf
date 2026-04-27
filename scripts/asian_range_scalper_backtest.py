"""Asian Range Scalper backtest — first pass.

Strategy spec (from ASIAN_RANGE_SCALPER_DESIGN.md):
- Pairs: EURGBP + USDCHF
- Range formation: 00:00-02:00 UTC (M5 bars)
- Trading: 02:00-06:00 UTC, force exit at 06:30 UTC
- Range width filter: 15-35 pips
- Entry: price comes within 2p of range extreme, then M5 bar closes back
  inside by 3p (proximity + rejection confirmation)
- TP: opposite extreme − 3p
- SL: range extreme ± max(5p, 0.3 × range_width)
- Max 1 LONG + 1 SHORT per session (re-entry rule simplified out)
- Skip Sunday nights

Simplifications vs design (acknowledged):
- No ADX(14) M15 filter (>25 = skip)
- No ATR compression filter
- No news filter (would reduce trades but improve quality — conservative test)
- No re-entry logic (one trade per direction max)
- No range-touch-both-sides validation
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

PIP = {"EURGBP": 0.0001, "USDCHF": 0.0001}
SPREAD_PIPS = {"EURGBP": 1.3, "USDCHF": 1.0}  # round-trip costs / 2 for per-side

MIN_RANGE = 15
MAX_RANGE = 35
PROXIMITY_PIPS = 2
REJECTION_PIPS = 3
TP_BUFFER = 3   # TP set inside opposite extreme by this many pips


def load_m5(symbol):
    path = os.path.join(DATA_DIR, "{}_M5.csv".format(symbol))
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def build_sessions(df, pip):
    """Group M5 bars by trading-date sessions (00:00-06:30 UTC)."""
    sessions = defaultdict(lambda: {"bars": []})
    for _, r in df.iterrows():
        ts = r["time"]
        h = ts.hour
        m = ts.minute
        if h >= 7:  # outside session
            continue
        sd = ts.date()
        sessions[sd]["bars"].append({
            "h": h, "m": m, "ts": ts,
            "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"],
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda x: x["ts"])
        s["wd"] = sd.weekday()
        formation = [b for b in s["bars"] if b["h"] < 2]
        if formation:
            s["range_high"] = max(b["hi"] for b in formation)
            s["range_low"] = min(b["lo"] for b in formation)
            s["range_pips"] = (s["range_high"] - s["range_low"]) / pip
        else:
            s["range_pips"] = 0
    return sessions


def simulate(symbol):
    pip = PIP[symbol]
    spread = SPREAD_PIPS[symbol]  # entry-side spread cost
    df = load_m5(symbol)
    if df is None:
        return None, None
    sessions = build_sessions(df, pip)

    trades = []
    sessions_qualified = 0
    sessions_total = 0

    for sd in sorted(sessions):
        s = sessions[sd]
        sessions_total += 1
        if s["wd"] == 6:  # Sunday — skip per design
            continue
        if s["range_pips"] < MIN_RANGE or s["range_pips"] > MAX_RANGE:
            continue
        sessions_qualified += 1

        rh = s["range_high"]
        rl = s["range_low"]
        rng = rh - rl
        sl_offset = max(5 * pip, 0.3 * rng)
        long_tp = rh - TP_BUFFER * pip
        short_tp = rl + TP_BUFFER * pip
        long_sl = rl - sl_offset
        short_sl = rh + sl_offset

        trading = [b for b in s["bars"] if 2 <= b["h"] < 7]
        if not trading:
            continue

        # State machine: per-direction
        # Phases: 'idle' → 'proximity_hit' → 'open' → 'done'
        long_state = "idle"
        long_entry = None
        short_state = "idle"
        short_entry = None
        forced = False

        for b in trading:
            # Force exit at 06:30 — close any open positions at this bar's close
            if (b["h"] == 6 and b["m"] >= 30) or b["h"] >= 7:
                for d_dir, state, entry, tp_, sl_ in [
                    ("L", long_state, long_entry, long_tp, long_sl),
                    ("S", short_state, short_entry, short_tp, short_sl),
                ]:
                    if state == "open" and entry is not None:
                        last_close = b["cl"]
                        if d_dir == "L":
                            pnl = (last_close - entry) / pip - spread
                        else:
                            pnl = (entry - last_close) / pip - spread
                        trades.append({"d": sd, "sym": symbol, "pnl": pnl,
                                       "x": "TIME", "dir": d_dir})
                if d_dir == "L":
                    long_state = "done"
                short_state = "done"
                long_state = "done"
                forced = True
                break

            # Manage open positions
            if long_state == "open":
                if b["lo"] <= long_sl:
                    trades.append({"d": sd, "sym": symbol,
                                   "pnl": (long_sl - long_entry) / pip - spread,
                                   "x": "SL", "dir": "L"})
                    long_state = "done"
                elif b["hi"] >= long_tp:
                    trades.append({"d": sd, "sym": symbol,
                                   "pnl": (long_tp - long_entry) / pip - spread,
                                   "x": "TP", "dir": "L"})
                    long_state = "done"
            if short_state == "open":
                if b["hi"] >= short_sl:
                    trades.append({"d": sd, "sym": symbol,
                                   "pnl": (short_entry - short_sl) / pip - spread,
                                   "x": "SL", "dir": "S"})
                    short_state = "done"
                elif b["lo"] <= short_tp:
                    trades.append({"d": sd, "sym": symbol,
                                   "pnl": (short_entry - short_tp) / pip - spread,
                                   "x": "TP", "dir": "S"})
                    short_state = "done"

            # Look for entries
            # LONG: bar low touches within 2p of range_low, then bar close >= rl + 3p
            if long_state == "idle":
                if b["lo"] <= rl + PROXIMITY_PIPS * pip:
                    long_state = "proximity_hit"
            if long_state == "proximity_hit":
                if b["cl"] >= rl + REJECTION_PIPS * pip and b["lo"] <= rl + PROXIMITY_PIPS * pip:
                    long_entry = b["cl"]
                    long_state = "open"

            # SHORT: bar high touches within 2p of range_high, then bar close <= rh - 3p
            if short_state == "idle":
                if b["hi"] >= rh - PROXIMITY_PIPS * pip:
                    short_state = "proximity_hit"
            if short_state == "proximity_hit":
                if b["cl"] <= rh - REJECTION_PIPS * pip and b["hi"] >= rh - PROXIMITY_PIPS * pip:
                    short_entry = b["cl"]
                    short_state = "open"

    return trades, (sessions_qualified, sessions_total)


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


print("Asian Range Scalper Backtest — First Pass")
print("=" * 88)
print()

all_trades = []
combined_results = []
for symbol in ("EURGBP", "USDCHF"):
    print(f"Loading {symbol} M5...")
    trades, qual = simulate(symbol)
    if trades is None:
        print(f"  No data")
        continue
    s = stats(trades, symbol)
    sq, st = qual
    print(f"  {symbol}: {st} sessions, {sq} qualified ({sq/st*100:.0f}%)")
    if s:
        print(f"  → n={s['n']} WR={s['wr']:.0f}% PF={s['pf']:.2f} Exp={s['exp']:+.2f} Tot={s['tot']:+.0f}p DD={s['dd']:.0f}p MaxCL={s['cl']}")
    all_trades.extend(trades)
    combined_results.append(s)
    print()

if all_trades:
    s_combined = stats(all_trades, "COMBINED")
    print("=" * 88)
    print("COMBINED (EURGBP + USDCHF):")
    print(f"  n={s_combined['n']} WR={s_combined['wr']:.0f}% PF={s_combined['pf']:.2f} "
          f"Exp={s_combined['exp']:+.2f}p Tot={s_combined['tot']:+.0f}p "
          f"DD={s_combined['dd']:.0f}p MaxCL={s_combined['cl']}")

    # Yearly breakdown
    yearly = defaultdict(list)
    for t in all_trades:
        yearly[t["d"].year].append(t["pnl"])
    print()
    print("Yearly:")
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
    ax.set_title(f"Asian Range Scalper — EURGBP+USDCHF (n={s_combined['n']}, "
                 f"PF={s_combined['pf']:.2f}, Tot={s_combined['tot']:+.0f}p)")
    ax.set_ylabel("Cumulative pips")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = os.path.join(CHARTS, "asian_range_scalper_bt.png")
    fig.savefig(out, dpi=110)
    print(f"\nChart: {out}")
