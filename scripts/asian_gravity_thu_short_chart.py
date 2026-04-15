"""Large standalone equity chart for Thursday SHORT T5/T2/S8."""
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
pip = 0.0001
spread = 1.0

sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5 or ts.hour >= 6:
        continue
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

# Simulate SHORT T5/T2/S8 rng<20
trigger = 5; target = 2; stop = 8; max_range = 20
trades = []
for d in sorted(thu):
    s = thu[d]
    if s["range"] > max_range or s["range"] < 1:
        continue
    so = s["open"]
    trading = [b for b in s["bars"] if b["h"] >= 2]
    ot = None; done = False; et = ""
    for b in trading:
        if done: continue
        if ot:
            ep, tp, sl_p = ot
            if b["hi"] >= sl_p:
                trades.append({"d": d, "pnl": (ep - sl_p)/pip - spread, "x": "SL", "et": et, "rng": s["range"]})
                done = True; continue
            if b["lo"] <= tp:
                trades.append({"d": d, "pnl": (ep - tp)/pip - spread, "x": "TP", "et": et, "rng": s["range"]})
                done = True; continue
        else:
            if b["hi"] >= so + trigger * pip:
                ep = so + trigger * pip
                ot = (ep, ep - target*pip, ep + stop*pip)
                et = "{:02d}:{:02d}".format(b["h"], b["m"])
    if ot and not done:
        last = trading[-1] if trading else s["bars"][-1]
        trades.append({"d": d, "pnl": (ot[0] - last["cl"])/pip - spread, "x": "TIME", "et": et, "rng": s["range"]})

pnls = [t["pnl"] for t in trades]
eq = np.cumsum(pnls)
wins = sum(1 for p in pnls if p > 0)
wr = wins / len(pnls) * 100
gp = sum(p for p in pnls if p > 0)
gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
pf = gp / gl
total = sum(pnls)
max_dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0

# Position sizing
pip_usd = 12.7
sl_pips = stop
for risk in [2.0]:
    lots = (10000 * risk / 100) / (sl_pips * pip_usd)
    total_usd = total * lots * pip_usd
    dd_usd = max_dd * lots * pip_usd
    ann = 365 / ((max(thu) - min(thu)).days)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(16, 8))

# Main equity line
color = "#2196F3"
ax.plot(range(len(eq)), eq, color=color, linewidth=2.5, zorder=3)
ax.fill_between(range(len(eq)), 0, eq, alpha=0.12, color=color)
ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

# Mark each trade
for j, t in enumerate(trades):
    if t["x"] == "TP":
        c, m, sz = "#4CAF50", "^", 100
    elif t["x"] == "SL":
        c, m, sz = "#F44336", "v", 100
    else:
        c, m, sz = "#FFC107", "o", 70
    ax.scatter(j, eq[j], color=c, s=sz, zorder=5, marker=m, edgecolors="white", linewidth=0.8)

# Date labels
dates = [str(t["d"]) for t in trades]
ax.set_xticks(range(len(dates)))
ax.set_xticklabels(dates, fontsize=8, rotation=45, ha="right")

# Title and labels
ax.set_title(
    "EURGBP Asian Gravity - THURSDAY SHORT\n"
    "T5/T2/S8, range<20p  |  {} to {}  |  M5 bars".format(
        min(thu), max(thu)),
    fontsize=14, fontweight="bold")
ax.set_ylabel("Cumulative P&L (pips)", fontsize=11)
ax.set_xlabel("Trade date ({} trades)".format(len(trades)), fontsize=11)

# Stats box
stats = (
    "Win Rate: {:.0f}%  ({} wins / {} losses)\n"
    "Profit Factor: {:.2f}\n"
    "Total: {:+.1f} pips\n"
    "Max Drawdown: {:.1f} pips\n"
    "Avg: {:+.2f} pips/trade\n"
    "At 2% risk ($10k): ${:+,.0f} | DD: ${:,.0f}".format(
        wr, wins, len(trades) - wins, pf, total, max_dd,
        np.mean(pnls), total_usd, dd_usd)
)
ax.text(0.02, 0.95, stats, transform=ax.transAxes, fontsize=10, va="top",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#E3F2FD", edgecolor="#2196F3", alpha=0.95))

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker="^", color="w", markerfacecolor="#4CAF50", markersize=10, label="TP (+1p)"),
    Line2D([0], [0], marker="v", color="w", markerfacecolor="#F44336", markersize=10, label="SL"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#FFC107", markersize=10, label="Time exit"),
]
ax.legend(handles=legend_elements, loc="lower right", fontsize=9)

ax.grid(True, alpha=0.15)
plt.tight_layout()

outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_thu_short_final.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("Chart saved: {}".format(outpath))

# Also print trade summary
print("\nTrade summary:")
for t in trades:
    marker = " WIN" if t["pnl"] > 0 else ""
    print("  {} rng={:>3.0f}p entry={} {:>4} pnl={:>+5.1f}p{}".format(
        t["d"], t["rng"], t["et"], t["x"], t["pnl"], marker))
print("\nTotal: {:+.1f}p | WR: {:.0f}% | PF: {:.2f}".format(total, wr, pf))

mt5.shutdown()
