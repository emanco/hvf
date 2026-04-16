"""Large standalone chart for EURGBP Quantum London GMT+2."""
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

# Build sessions with 22:00 UTC daily open
sessions = {}
current = None
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    h = ts.hour
    if h == 22 and ts.minute == 0:
        current = {"date": ts.date(), "open": r[1], "bars": [], "wd": ts.weekday()}
        sessions[ts.date()] = current
    if current and (h >= 22 or h < 6):
        current["bars"].append({"h": h, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})
    elif current and h >= 6:
        current = None

# Simulate T8/T5/S18 Mon-Thu Both ex@5
trigger = 8; target = 5; stop = 18
trades = []
for d in sorted(sessions):
    s = sessions[d]
    if s["wd"] not in [0, 1, 2, 3]: continue
    daily_open = s["open"]
    trading = [b for b in s["bars"] if b["h"] < 5]
    if not trading: continue
    ot = None; done = False
    for b in trading:
        if done: continue
        if ot:
            dr, ep, tp, sl = ot
            if dr == "L":
                if b["lo"] <= sl: trades.append({"d": d, "pnl": (sl-ep)/pip-spread, "x": "SL", "dir": "LONG"}); done=True; continue
                if b["hi"] >= tp: trades.append({"d": d, "pnl": (tp-ep)/pip-spread, "x": "TP", "dir": "LONG"}); done=True; continue
            else:
                if b["hi"] >= sl: trades.append({"d": d, "pnl": (ep-sl)/pip-spread, "x": "SL", "dir": "SHORT"}); done=True; continue
                if b["lo"] <= tp: trades.append({"d": d, "pnl": (ep-tp)/pip-spread, "x": "TP", "dir": "SHORT"}); done=True; continue
        else:
            if b["lo"] <= daily_open - trigger*pip:
                ep = daily_open - trigger*pip
                ot = ("L", ep, ep+target*pip, ep-stop*pip)
            elif b["hi"] >= daily_open + trigger*pip:
                ep = daily_open + trigger*pip
                ot = ("S", ep, ep-target*pip, ep+stop*pip)
    if ot and not done:
        dr, ep, tp, sl = ot
        last = trading[-1]
        if dr == "L": pnl = (last["cl"]-ep)/pip-spread
        else: pnl = (ep-last["cl"])/pip-spread
        trades.append({"d": d, "pnl": pnl, "x": "TIME", "dir": "LONG" if dr == "L" else "SHORT"})

pnls = [t["pnl"] for t in trades]
eq = np.cumsum(pnls)
dates = [t["d"] for t in trades]
wins = sum(1 for p in pnls if p > 0)
wr = wins/len(pnls)*100
gp = sum(p for p in pnls if p > 0)
gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
pf = gp/gl
dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
consec = 0; mc = 0
for p in pnls:
    if p <= 0: consec += 1; mc = max(mc, consec)
    else: consec = 0

# Print stats
tp_n = sum(1 for t in trades if t["x"] == "TP")
sl_n = sum(1 for t in trades if t["x"] == "SL")
time_n = sum(1 for t in trades if t["x"] == "TIME")
print("EURGBP Quantum London (GMT+2 daily open)")
print("T{}/T{}/S{}, Mon-Thu, Both dirs, exit@05:00 UTC".format(trigger, target, stop))
print("Trades: {} (TP:{} SL:{} TIME:{})".format(len(trades), tp_n, sl_n, time_n))
print("WR: {:.0f}% | PF: {:.2f} | Tot: {:+.0f}p | DD: {:.0f}p | MaxConsecL: {}".format(
    wr, pf, sum(pnls), dd, mc))

longs = [t for t in trades if t["dir"] == "LONG"]
shorts = [t for t in trades if t["dir"] == "SHORT"]
lw = sum(1 for t in longs if t["pnl"] > 0)
sw = sum(1 for t in shorts if t["pnl"] > 0)
print("LONG: {}T WR={:.0f}% PnL={:+.0f}p".format(len(longs), lw/len(longs)*100 if longs else 0, sum(t["pnl"] for t in longs)))
print("SHORT: {}T WR={:.0f}% PnL={:+.0f}p".format(len(shorts), sw/len(shorts)*100 if shorts else 0, sum(t["pnl"] for t in shorts)))

pip_usd = 12.7
for risk in [1.0, 2.0, 3.0]:
    lots = (10000 * risk / 100) / (stop * pip_usd)
    t_usd = sum(pnls) * lots * pip_usd
    d_usd = dd * lots * pip_usd
    months = 8
    print("{}% risk ($10k): lots={:.2f}, Total=${:+,.0f}, Monthly=${:+,.0f}, DD=${:,.0f}".format(
        risk, lots, t_usd, t_usd/months, d_usd))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

fig, ax = plt.subplots(figsize=(18, 8))

color = "#2196F3"
ax.plot(dates, eq, color=color, linewidth=2.5, zorder=3)
ax.fill_between(dates, 0, eq, alpha=0.12, color=color)
ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

for j, t in enumerate(trades):
    if t["x"] == "TP": c, m = "#4CAF50", "^"
    elif t["x"] == "SL": c, m = "#F44336", "v"
    else: c, m = "#FFC107", "o"
    ax.scatter(dates[j], eq[j], color=c, s=40, zorder=5, marker=m, edgecolors="white", linewidth=0.5)

ax.set_title(
    "EURGBP Quantum London — Daily Open at 22:00 UTC (00:00 GMT+2)\n"
    "T8/T5/S18, Mon-Thu, Both directions, exit@05:00 UTC  |  M5, 8 months",
    fontsize=14, fontweight="bold")
ax.set_ylabel("Cumulative P&L (pips)", fontsize=11)
ax.set_xlabel("{} trades".format(len(trades)), fontsize=11)

stats_text = (
    "Win Rate: {:.0f}%  ({} wins / {} losses)\n"
    "Profit Factor: {:.2f}\n"
    "Total: {:+.0f} pips\n"
    "Max Drawdown: {:.0f} pips\n"
    "Max Consec Losses: {}\n"
    "Exits: TP={} SL={} TIME={}".format(
        wr, wins, len(trades)-wins, pf, sum(pnls), dd, mc, tp_n, sl_n, time_n)
)
ax.text(0.02, 0.95, stats_text, transform=ax.transAxes, fontsize=10, va="top",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#E3F2FD", edgecolor="#2196F3", alpha=0.95))

legend_elements = [
    Line2D([0], [0], marker="^", color="w", markerfacecolor="#4CAF50", markersize=10, label="TP (+4p)"),
    Line2D([0], [0], marker="v", color="w", markerfacecolor="#F44336", markersize=10, label="SL (-19p)"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#FFC107", markersize=10, label="Time exit"),
]
ax.legend(handles=legend_elements, loc="lower right", fontsize=9)
ax.grid(True, alpha=0.15)

import matplotlib.dates as mdates
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "quantum_london_eurgbp_final.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))
mt5.shutdown()
