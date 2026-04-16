"""Quantum London EURGBP — equity curves at different risk levels."""
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
pip = 0.0001; spread = 1.0; stop = 18; pip_usd = 12.7

# Build sessions with 22:00 UTC daily open
sessions = {}; current = None
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
trigger = 8; target = 5
trades = []
for d in sorted(sessions):
    s = sessions[d]
    if s["wd"] not in [0,1,2,3]: continue
    do = s["open"]
    trading = [b for b in s["bars"] if b["h"] < 5]
    if not trading: continue
    ot = None; done = False
    for b in trading:
        if done: continue
        if ot:
            dr, ep, tp, sl = ot
            if dr == "L":
                if b["lo"] <= sl: trades.append({"d":d,"pnl":(sl-ep)/pip-spread,"x":"SL"}); done=True; continue
                if b["hi"] >= tp: trades.append({"d":d,"pnl":(tp-ep)/pip-spread,"x":"TP"}); done=True; continue
            else:
                if b["hi"] >= sl: trades.append({"d":d,"pnl":(ep-sl)/pip-spread,"x":"SL"}); done=True; continue
                if b["lo"] <= tp: trades.append({"d":d,"pnl":(ep-tp)/pip-spread,"x":"TP"}); done=True; continue
        else:
            if b["lo"] <= do - trigger*pip:
                ep = do - trigger*pip; ot = ("L", ep, ep+target*pip, ep-stop*pip)
            elif b["hi"] >= do + trigger*pip:
                ep = do + trigger*pip; ot = ("S", ep, ep-target*pip, ep+stop*pip)
    if ot and not done:
        dr, ep, tp, sl = ot; last = trading[-1]
        if dr == "L": pnl = (last["cl"]-ep)/pip-spread
        else: pnl = (ep-last["cl"])/pip-spread
        trades.append({"d":d,"pnl":pnl,"x":"TIME"})

pnls = [t["pnl"] for t in trades]
dates = [t["d"] for t in trades]

# Chart: equity in $ at different risk levels
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

risk_levels = [1, 2, 3, 5, 8, 10]
colors = ["#90CAF9", "#42A5F5", "#1E88E5", "#1565C0", "#0D47A1", "#000000"]

fig, axes = plt.subplots(2, 1, figsize=(18, 12), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("EURGBP Quantum London — Equity at Different Risk Levels\n"
             "T8/T5/S18, Mon-Thu, Daily Open 22:00 UTC  |  119 trades, 95% WR",
             fontsize=14, fontweight="bold")

ax = axes[0]
starting = 10000

for risk, color in zip(risk_levels, colors):
    lots = (starting * risk / 100) / (stop * pip_usd)
    equity = [starting]
    for p in pnls:
        # Recalculate lots based on current equity (compounding)
        current_lots = (equity[-1] * risk / 100) / (stop * pip_usd)
        pnl_usd = p * current_lots * pip_usd
        equity.append(equity[-1] + pnl_usd)

    final = equity[-1]
    total_return = (final - starting) / starting * 100
    max_dd_usd = 0
    peak = starting
    for e in equity:
        if e > peak: peak = e
        dd = peak - e
        if dd > max_dd_usd: max_dd_usd = dd
    max_dd_pct = max_dd_usd / starting * 100

    ax.plot(dates, equity[1:], color=color, linewidth=2 if risk <= 5 else 1.5,
            label="{}% risk: {:,.0f} ({:+.0f}%)  DD={:,.0f} ({:.1f}%)".format(
                risk, final, total_return, max_dd_usd, max_dd_pct))

ax.axhline(y=starting, color="gray", linestyle="--", alpha=0.3)
ax.set_ylabel("Account Equity ($)", fontsize=11)
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.15)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

# Bottom: monthly $ returns at 5% risk
ax2 = axes[1]
lots_5 = (starting * 5 / 100) / (stop * pip_usd)
monthly = {}
for t in trades:
    m = t["d"].strftime("%Y-%m") if hasattr(t["d"], "strftime") else str(t["d"])[:7]
    monthly[m] = monthly.get(m, 0) + t["pnl"] * lots_5 * pip_usd

months = sorted(monthly.keys())
vals = [monthly[m] for m in months]
colors_bar = ["#4CAF50" if v > 0 else "#F44336" for v in vals]
ax2.bar(range(len(months)), vals, color=colors_bar, alpha=0.8)
ax2.set_xticks(range(len(months)))
ax2.set_xticklabels(months, fontsize=8, rotation=45)
ax2.set_ylabel("Monthly $ P&L (5% risk)", fontsize=10)
ax2.axhline(y=0, color="gray", linewidth=0.5)
ax2.grid(True, alpha=0.15)
ax2.set_title("Monthly Returns at 5% Risk", fontsize=10, fontweight="bold")

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "quantum_london_risk_levels.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("Chart: {}".format(outpath))

# Print monthly detail at 5%
print("\nMonthly at 5% risk ($10k start, compounding):")
equity_5 = 10000
for m in months:
    month_pnl = sum(t["pnl"] for t in trades if (t["d"].strftime("%Y-%m") if hasattr(t["d"], "strftime") else str(t["d"])[:7]) == m)
    month_trades = sum(1 for t in trades if (t["d"].strftime("%Y-%m") if hasattr(t["d"], "strftime") else str(t["d"])[:7]) == m)
    lots = (equity_5 * 5 / 100) / (stop * pip_usd)
    usd = month_pnl * lots * pip_usd
    equity_5 += usd
    print("  {}: {:>2} trades {:>+6.0f}p  ${:>+8,.0f}  equity=${:>10,.0f}".format(
        m, month_trades, month_pnl, usd, equity_5))

mt5.shutdown()
