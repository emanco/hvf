"""London Breakout GBPUSD — Test best combined configs and plot."""
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
first = datetime.fromtimestamp(rates[0][0], tz=timezone.utc)
last = datetime.fromtimestamp(rates[-1][0], tz=timezone.utc)

sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5:
        continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"bars": [], "weekday": ts.weekday()}
    sessions[bd]["bars"].append({
        "h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
    })


def simulate(max_range, min_range, tp_mult, exit_hour, spread, days=None):
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if days and s["weekday"] not in days:
            continue
        asian = [b for b in s["bars"] if b["h"] < 7]
        if len(asian) < 3:
            continue
        a_high = max(b["hi"] for b in asian)
        a_low = min(b["lo"] for b in asian)
        a_range = (a_high - a_low) / pip
        if a_range > max_range or a_range < min_range:
            continue

        london = [b for b in s["bars"] if 8 <= b["h"] < exit_hour]
        if not london:
            continue

        tp_dist = a_range * tp_mult * pip
        sp = spread * pip
        traded = False

        for b in london:
            if traded:
                break
            # LONG
            if b["hi"] > a_high + sp:
                entry = a_high + sp
                sl = a_low - sp
                tp = entry + tp_dist
                risk = (entry - sl) / pip
                remaining = [bb for bb in london if bb["h"] >= b["h"]]
                hit = None
                for rb in remaining:
                    if rb["lo"] <= sl:
                        hit = "SL"; pnl = -risk - spread; break
                    if rb["hi"] >= tp:
                        hit = "TP"; pnl = (tp-entry)/pip - spread; break
                if hit is None:
                    lc = remaining[-1]["cl"] if remaining else b["cl"]
                    pnl = (lc-entry)/pip - spread; hit = "TIME"
                trades.append({"d": d, "dir": "LONG", "pnl": pnl, "x": hit,
                               "rng": a_range, "wd": s["weekday"]})
                traded = True
            # SHORT
            if not traded and b["lo"] < a_low - sp:
                entry = a_low - sp
                sl = a_high + sp
                tp = entry - tp_dist
                risk = (sl-entry) / pip
                remaining = [bb for bb in london if bb["h"] >= b["h"]]
                hit = None
                for rb in remaining:
                    if rb["hi"] >= sl:
                        hit = "SL"; pnl = -risk - spread; break
                    if rb["lo"] <= tp:
                        hit = "TP"; pnl = (entry-tp)/pip - spread; break
                if hit is None:
                    lc = remaining[-1]["cl"] if remaining else b["cl"]
                    pnl = (entry-lc)/pip - spread; hit = "TIME"
                trades.append({"d": d, "dir": "SHORT", "pnl": pnl, "x": hit,
                               "rng": a_range, "wd": s["weekday"]})
                traded = True
    return trades


def stats(trades):
    if not trades:
        return None
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    consec = 0; max_consec = 0
    for p in pnls:
        if p <= 0: consec += 1; max_consec = max(max_consec, consec)
        else: consec = 0
    return {"n": len(trades), "wr": w/len(trades)*100, "pf": gp/gl,
            "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd, "consec": max_consec}


configs = [
    ("Baseline: rng 15-20 ex@17 All", 20, 15, 1.0, 17, 1.0, None),
    ("Mon-Wed ex@17", 20, 15, 1.0, 17, 1.0, [0,1,2]),
    ("Mon-Wed ex@15", 20, 15, 1.0, 15, 1.0, [0,1,2]),
    ("Mon-Tue ex@15", 20, 15, 1.0, 15, 1.0, [0,1]),
    ("Mon-Tue ex@17", 20, 15, 1.0, 17, 1.0, [0,1]),
    ("Tue only ex@17", 20, 15, 1.0, 17, 1.0, [1]),
    ("Tue-Wed ex@15", 20, 15, 1.0, 15, 1.0, [1,2]),
    ("Mon-Wed ex@15 TP=1.2x", 20, 15, 1.2, 15, 1.0, [0,1,2]),
    ("Mon-Wed ex@13", 20, 15, 1.0, 13, 1.0, [0,1,2]),
]

print("GBPUSD London Breakout — Combined Refinements")
print("{} to {}\n".format(first.date(), last.date()))
print("{:<40} {:>4} {:>5} {:>7} {:>7} {:>7} {:>6} {:>6}".format(
    "Config", "N", "WR", "PF", "Exp", "Tot", "DD", "ConsL"))
print("-" * 85)

all_results = []
for label, mr, mnr, tp, ex, sp, days in configs:
    trades = simulate(mr, mnr, tp, ex, sp, days)
    s = stats(trades)
    if not s:
        continue
    f = " ***" if s["pf"] > 1.3 else " **" if s["pf"] > 1.0 else ""
    print("{:<40} {:>4} {:>4.0f}% {:>7.2f} {:>+6.1f}p {:>+6.0f}p {:>5.0f}p {:>5}{}".format(
        label, s["n"], s["wr"], s["pf"], s["exp"], s["tot"], s["dd"], s["consec"], f))
    all_results.append((label, s, trades))

# Yearly breakdown for top configs
for label, s, trades in all_results[:4]:
    print("\n--- {} ---".format(label))
    yearly = {}
    for t in trades:
        yr = t["d"].year
        if yr not in yearly:
            yearly[yr] = {"n": 0, "w": 0, "pnl": 0}
        yearly[yr]["n"] += 1
        yearly[yr]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            yearly[yr]["w"] += 1
    for yr in sorted(yearly):
        y = yearly[yr]
        wr = y["w"]/y["n"]*100 if y["n"] else 0
        print("  {}: {:>3} trades, WR={:.0f}%, PnL={:+.0f}p".format(yr, y["n"], wr, y["pnl"]))

    # Sizing
    pip_usd = 10.0  # GBPUSD ~$10/pip/lot
    for risk in [1.0, 2.0]:
        avg_risk_pips = np.mean([abs(t["pnl"]) for t in trades if t["pnl"] < 0]) if [t for t in trades if t["pnl"] < 0] else 20
        lots = (10000 * risk / 100) / (avg_risk_pips * pip_usd)
        total_usd = s["tot"] * lots * pip_usd
        dd_usd = s["dd"] * lots * pip_usd
        years = (last - first).days / 365
        print("  At {}% risk ($10k): ${:+,.0f} total, ${:+,.0f}/yr, DD ${:,.0f}".format(
            risk, total_usd, total_usd/years, dd_usd))

# Chart top 4
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle("GBPUSD London Breakout — Best Combined Configs (H1, 8 years)",
             fontsize=14, fontweight="bold")

for idx, (label, s, trades) in enumerate(all_results[:4]):
    ax = axes[idx // 2][idx % 2]
    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [t["d"] for t in trades]

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(dates, eq, color=color, linewidth=1.5)
    ax.fill_between(dates, 0, eq, alpha=0.1, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
    for j, t in enumerate(trades):
        if t["x"] == "TP": c = "#4CAF50"
        elif t["x"] == "SL": c = "#F44336"
        else: c = "#FFC107"
        ax.scatter(dates[j], eq[j], color=c, s=8, zorder=5)

    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title("{} | {} trades".format(label, s["n"]), fontsize=10, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=9)
    ax.text(0.02, 0.95,
            "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
                s["wr"], s["pf"], s["tot"], s["dd"]),
            transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "london_breakout_gbpusd_best.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
