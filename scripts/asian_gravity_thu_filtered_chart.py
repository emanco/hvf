"""Thursday SHORT with formation range filter variants — equity charts."""
import sys, os
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))
rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
pip = 0.0001; spread = 1.0

sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5 or ts.hour >= 6: continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"wd": ts.weekday(), "bars": []}
    sessions[bd]["bars"].append({"h": ts.hour, "m": ts.minute, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

for s in sessions.values():
    form = [b for b in s["bars"] if b["h"] < 2]
    if form:
        s["open"] = s["bars"][0]["o"]
        s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip
    else:
        s["range"] = 999

thu = {d: s for d, s in sessions.items() if s["wd"] == 3}

def simulate(trigger, target, stop, max_range):
    trades = []
    for d in sorted(thu):
        s = thu[d]
        if s["range"] > max_range or s["range"] < 1: continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot = None; done = False; et = ""
        for b in trading:
            if done: continue
            if ot:
                ep, tp, sl_p = ot
                if b["hi"] >= sl_p:
                    trades.append({"d": d, "pnl": (ep-sl_p)/pip-spread, "x": "SL", "et": et, "rng": s["range"]})
                    done = True; continue
                if b["lo"] <= tp:
                    trades.append({"d": d, "pnl": (ep-tp)/pip-spread, "x": "TP", "et": et, "rng": s["range"]})
                    done = True; continue
            else:
                if b["hi"] >= so + trigger*pip:
                    ep = so + trigger*pip
                    ot = (ep, ep-target*pip, ep+stop*pip)
                    et = "{:02d}:{:02d}".format(b["h"], b["m"])
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            trades.append({"d": d, "pnl": (ot[0]-last["cl"])/pip-spread, "x": "TIME", "et": et, "rng": s["range"]})
    return trades

configs = [
    ("Baseline: rng<20", 5, 2, 8, 20),
    ("Filtered: rng<15", 5, 2, 8, 15),
    ("Filtered: rng<12", 5, 2, 8, 12),
    ("Filtered: rng<10", 5, 2, 8, 10),
]

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle("EURGBP Thursday SHORT T5/T2/S8 - Formation Range Filters\n(M5, 8 months)",
             fontsize=14, fontweight="bold")

for idx, (label, trig, tgt, sl, mr) in enumerate(configs):
    ax = axes[idx // 2][idx % 2]
    trades = simulate(trig, tgt, sl, mr)

    if not trades:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center", fontsize=14)
        ax.set_title(label, fontsize=11, fontweight="bold")
        continue

    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [str(t["d"]) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(pnls) * 100
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    pf = gp / gl
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(range(len(eq)), eq, color=color, linewidth=2.5, zorder=3)
    ax.fill_between(range(len(eq)), 0, eq, alpha=0.12, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

    for j, t in enumerate(trades):
        if t["x"] == "TP": c, m = "#4CAF50", "^"
        elif t["x"] == "SL": c, m = "#F44336", "v"
        else: c, m = "#FFC107", "o"
        ax.scatter(j, eq[j], color=c, s=80, zorder=5, marker=m, edgecolors="white", linewidth=0.8)

    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels([d[5:] for d in dates], fontsize=7, rotation=45, ha="right")
    ax.set_title("{} | {} trades".format(label, len(trades)), fontsize=11, fontweight="bold")
    ax.set_ylabel("Cumulative P&L (pips)", fontsize=9)

    # Stats box
    pip_usd = 12.7
    lots = (10000 * 0.02) / (sl * pip_usd)
    usd_total = sum(pnls) * lots * pip_usd
    usd_dd = dd * lots * pip_usd

    stats = (
        "WR={:.0f}%  PF={:.2f}  Tot={:+.1f}p\n"
        "MaxDD={:.1f}p  |  At 2%: ${:+,.0f}".format(
            wr, pf, sum(pnls), dd, usd_total))
    ax.text(0.02, 0.95, stats, transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#E3F2FD", edgecolor="#2196F3", alpha=0.95))

    # Trade detail annotation
    detail = ""
    for t in trades:
        marker = "W" if t["pnl"] > 0 else "L"
        detail += "{} {} {:+.1f}p\n".format(str(t["d"])[5:], marker, t["pnl"])
    ax.text(0.98, 0.95, detail.strip(), transform=ax.transAxes, fontsize=6, va="top", ha="right",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_thu_range_filters.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("Chart saved: {}".format(outpath))

# Print summary table
print("\n{:<25} {:>4} {:>5} {:>7} {:>7} {:>7}".format("Config", "N", "WR", "PF", "Tot", "DD"))
print("-" * 60)
for label, trig, tgt, sl, mr in configs:
    trades = simulate(trig, tgt, sl, mr)
    if not trades: continue
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("{:<25} {:>4} {:>4.0f}% {:>7.2f} {:>+6.1f}p {:>5.1f}p".format(
        label, len(trades), w/len(trades)*100, gp/gl, sum(pnls), dd))

mt5.shutdown()
