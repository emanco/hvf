"""Plot top 3 London Breakout configs with yearly breakdown."""
import sys, os
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

rates = mt5.copy_rates_from_pos("GBPUSD", mt5.TIMEFRAME_H1, 0, 50000)
pip = 0.0001

sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5:
        continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"bars": [], "wd": ts.weekday()}
    sessions[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

first_d = min(sessions)
last_d = max(sessions)


def simulate(mr, mnr, tp, ex, sp, days):
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if days and s["wd"] not in days:
            continue
        asian = [b for b in s["bars"] if b["h"] < 7]
        if len(asian) < 3:
            continue
        ah = max(b["hi"] for b in asian)
        al = min(b["lo"] for b in asian)
        ar = (ah - al) / pip
        if ar > mr or ar < mnr:
            continue
        lon = [b for b in s["bars"] if 8 <= b["h"] < ex]
        if not lon:
            continue
        td = ar * tp * pip
        sp2 = sp * pip
        traded = False
        for b in lon:
            if traded:
                break
            if b["hi"] > ah + sp2:
                e = ah + sp2; sl = al - sp2; t2 = e + td; rk = (e - sl) / pip
                rem = [bb for bb in lon if bb["h"] >= b["h"]]
                hit = None
                for rb in rem:
                    if rb["lo"] <= sl:
                        hit = "SL"; pnl = -rk - sp; break
                    if rb["hi"] >= t2:
                        hit = "TP"; pnl = (t2 - e) / pip - sp; break
                if not hit:
                    lc = rem[-1]["cl"]
                    pnl = (lc - e) / pip - sp; hit = "TIME"
                trades.append({"d": d, "dir": "L", "pnl": pnl, "x": hit})
                traded = True
            if not traded and b["lo"] < al - sp2:
                e = al - sp2; sl = ah + sp2; t2 = e - td; rk = (sl - e) / pip
                rem = [bb for bb in lon if bb["h"] >= b["h"]]
                hit = None
                for rb in rem:
                    if rb["hi"] >= sl:
                        hit = "SL"; pnl = -rk - sp; break
                    if rb["lo"] <= t2:
                        hit = "TP"; pnl = (e - t2) / pip - sp; break
                if not hit:
                    lc = rem[-1]["cl"]
                    pnl = (e - lc) / pip - sp; hit = "TIME"
                trades.append({"d": d, "dir": "S", "pnl": pnl, "x": hit})
                traded = True
    return trades


configs = [
    ("rng 12-18, TP=1.0x, ex@13, Mon-Tue", 18, 12, 1.0, 13, 1.0, [0, 1]),
    ("rng 15-18, TP=1.2x, ex@13, Mon-Wed", 18, 15, 1.2, 13, 1.0, [0, 1, 2]),
    ("rng 12-20, TP=1.0x, ex@13, Mon-Tue", 20, 12, 1.0, 13, 1.0, [0, 1]),
]

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

fig, axes = plt.subplots(3, 1, figsize=(16, 18))
fig.suptitle("GBPUSD London Breakout — Top 3 Configs (H1, {} to {})".format(
    first_d, last_d), fontsize=14, fontweight="bold")

for idx, (label, mr, mnr, tp, ex, sp, days) in enumerate(configs):
    trades = simulate(mr, mnr, tp, ex, sp, days)
    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [t["d"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(pnls) * 100
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    pf = gp / gl
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    consec = 0; mc = 0
    for p in pnls:
        if p <= 0: consec += 1; mc = max(mc, consec)
        else: consec = 0

    # Yearly
    yearly = {}
    for t in trades:
        yr = t["d"].year
        if yr not in yearly:
            yearly[yr] = {"n": 0, "w": 0, "pnl": 0}
        yearly[yr]["n"] += 1
        yearly[yr]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            yearly[yr]["w"] += 1
    pos_years = sum(1 for v in yearly.values() if v["pnl"] > 0)

    # Print detail
    print("\n{}".format("=" * 70))
    print("  {}".format(label))
    print("  {} trades | WR={:.0f}% | PF={:.2f} | Tot={:+.0f}p | DD={:.0f}p | MaxConsecL={}".format(
        len(trades), wr, pf, sum(pnls), dd, mc))
    print("  Positive years: {}/{}".format(pos_years, len(yearly)))
    for yr in sorted(yearly):
        y = yearly[yr]
        ywr = y["w"] / y["n"] * 100 if y["n"] else 0
        print("    {}: {:>3}T WR={:.0f}% PnL={:+.0f}p".format(yr, y["n"], ywr, y["pnl"]))

    # Sizing
    pip_usd = 10.0
    avg_loss = abs(np.mean([p for p in pnls if p < 0])) if [p for p in pnls if p < 0] else 20
    for risk in [1.0, 2.0]:
        lots = (10000 * risk / 100) / (avg_loss * pip_usd)
        t_usd = sum(pnls) * lots * pip_usd
        d_usd = dd * lots * pip_usd
        yrs = (last_d - first_d).days / 365
        print("    {}% risk ($10k): lots={:.2f}, Total=${:+,.0f}, Annual=${:+,.0f}/yr, DD=${:,.0f}".format(
            risk, lots, t_usd, t_usd / yrs, d_usd))

    # Direction
    for dn, dc in [("LONG", "L"), ("SHORT", "S")]:
        dt = [t for t in trades if t["dir"] == dc]
        if dt:
            dw = sum(1 for t in dt if t["pnl"] > 0)
            print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
                dn, len(dt), dw / len(dt) * 100, sum(t["pnl"] for t in dt)))

    # Chart
    ax = axes[idx]
    color = "#2196F3"
    ax.plot(dates, eq, color=color, linewidth=1.8, zorder=3)
    ax.fill_between(dates, 0, eq, alpha=0.1, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

    for j, t in enumerate(trades):
        if t["x"] == "TP":
            c, m = "#4CAF50", "^"
        elif t["x"] == "SL":
            c, m = "#F44336", "v"
        else:
            c, m = "#FFC107", "o"
        ax.scatter(dates[j], eq[j], color=c, s=15, zorder=5, marker=m,
                   edgecolors="white", linewidth=0.3)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title("{} | {} trades".format(label, len(trades)),
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)

    stats_text = (
        "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p  ConsL={}\n"
        "Positive years: {}/{}".format(
            wr, pf, sum(pnls), dd, mc, pos_years, len(yearly)))
    ax.text(0.02, 0.95, stats_text, transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#E3F2FD",
                      edgecolor="#2196F3", alpha=0.95))

    legend_elements = [
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#4CAF50", markersize=8, label="TP"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#F44336", markersize=8, label="SL"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#FFC107", markersize=8, label="Time"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "london_breakout_gbpusd_top3.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
