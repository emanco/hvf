"""London Breakout GBPUSD — Exhaustive combo search for best PF with low DD."""
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
        sessions[bd] = {"bars": [], "wd": ts.weekday()}
    sessions[bd]["bars"].append({
        "h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
    })


def simulate(max_rng, min_rng, tp_mult, exit_h, spread, days,
             asian_end=7, london_start=8):
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if days and s["wd"] not in days:
            continue
        asian = [b for b in s["bars"] if b["h"] < asian_end]
        if len(asian) < 3:
            continue
        ah = max(b["hi"] for b in asian)
        al = min(b["lo"] for b in asian)
        ar = (ah - al) / pip
        if ar > max_rng or ar < min_rng:
            continue
        london = [b for b in s["bars"] if london_start <= b["h"] < exit_h]
        if not london:
            continue
        tp_d = ar * tp_mult * pip
        sp = spread * pip
        traded = False
        for b in london:
            if traded:
                break
            if b["hi"] > ah + sp:
                e = ah + sp; sl = al - sp; tp = e + tp_d; rk = (e-sl)/pip
                rem = [bb for bb in london if bb["h"] >= b["h"]]
                hit = None
                for rb in rem:
                    if rb["lo"] <= sl: hit="SL"; pnl=-rk-spread; break
                    if rb["hi"] >= tp: hit="TP"; pnl=(tp-e)/pip-spread; break
                if not hit:
                    lc = rem[-1]["cl"] if rem else b["cl"]
                    pnl=(lc-e)/pip-spread; hit="TIME"
                trades.append({"d":d,"dir":"L","pnl":pnl,"x":hit,"rng":ar,"wd":s["wd"]})
                traded=True
            if not traded and b["lo"] < al - sp:
                e = al - sp; sl = ah + sp; tp = e - tp_d; rk = (sl-e)/pip
                rem = [bb for bb in london if bb["h"] >= b["h"]]
                hit = None
                for rb in rem:
                    if rb["hi"] >= sl: hit="SL"; pnl=-rk-spread; break
                    if rb["lo"] <= tp: hit="TP"; pnl=(e-tp)/pip-spread; break
                if not hit:
                    lc = rem[-1]["cl"] if rem else b["cl"]
                    pnl=(e-lc)/pip-spread; hit="TIME"
                trades.append({"d":d,"dir":"S","pnl":pnl,"x":hit,"rng":ar,"wd":s["wd"]})
                traded=True
    return trades


def stats(trades):
    if not trades: return None
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    c=0; mc=0
    for p in pnls:
        if p<=0: c+=1; mc=max(mc,c)
        else: c=0
    # Positive years
    yearly = {}
    for t in trades:
        yr = t["d"].year
        yearly[yr] = yearly.get(yr, 0) + t["pnl"]
    pos_years = sum(1 for v in yearly.values() if v > 0)
    return {"n":len(trades),"wr":w/len(trades)*100,"pf":gp/gl,
            "exp":np.mean(pnls),"tot":sum(pnls),"dd":dd,"cl":mc,
            "py": pos_years, "ty": len(yearly)}


print("GBPUSD London Breakout - Exhaustive Combo Search")
print("{} to {}\n".format(first.date(), last.date()))

results = []
for max_rng in [18, 20, 25, 30]:
    for min_rng in [10, 12, 15, 17]:
        if min_rng >= max_rng: continue
        for tp in [0.8, 1.0, 1.2, 1.5]:
            for ex in [13, 14, 15, 16, 17]:
                for sp in [1.0, 1.5]:
                    for ds, dl in [
                        ([0,1], "MoTu"),
                        ([0,1,2], "MoTuWe"),
                        ([1,2], "TuWe"),
                        ([1], "Tue"),
                        ([0,1,2,3], "MoTuWeTh"),
                        ([1,2,3], "TuWeTh"),
                        (None, "All"),
                    ]:
                        for a_end in [6, 7]:
                            trades = simulate(max_rng, min_rng, tp, ex, sp, ds, a_end)
                            if len(trades) < 30: continue
                            s = stats(trades)
                            if s["pf"] < 1.0: continue
                            results.append({**s, "mr":max_rng, "mnr":min_rng,
                                           "tp":tp, "ex":ex, "sp":sp, "days":dl,
                                           "ae": a_end})

# Sort by PF * sqrt(N) to balance quality and quantity
results.sort(key=lambda x: -x["pf"] * np.sqrt(x["n"]))

print("{:<55} {:>4} {:>5} {:>7} {:>7} {:>7} {:>5} {:>4} {:>5}".format(
    "Config", "N", "WR", "PF", "Exp", "Tot", "DD", "CL", "Yr+"))
print("-" * 100)

seen = set()
ct = 0
for r in results:
    if ct >= 30: break
    lab = "rng {}-{} TP={}x ex@{} {} ae={} sp={}".format(
        r["mnr"], r["mr"], r["tp"], r["ex"], r["days"], r["ae"], r["sp"])
    if lab in seen: continue
    seen.add(lab)
    f = " ***" if r["pf"] > 1.4 and r["dd"] < 120 else " **" if r["pf"] > 1.3 else ""
    print("{:<55} {:>4} {:>4.0f}% {:>7.2f} {:>+6.1f}p {:>+6.0f}p {:>4.0f}p {:>3} {:>3}/{}{}".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"], r["dd"],
        r["cl"], r["py"], r["ty"], f))
    ct += 1

# Chart top 6
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

chart_results = results[:6]
fig, axes = plt.subplots(3, 2, figsize=(16, 16))
fig.suptitle("GBPUSD London Breakout — Top Refined Combos (H1, 8 years)",
             fontsize=13, fontweight="bold")

for idx, r in enumerate(chart_results):
    ax = axes[idx//2][idx%2]
    trades = simulate(r["mr"], r["mnr"], r["tp"], r["ex"], r["sp"],
                      {"MoTu":[0,1],"MoTuWe":[0,1,2],"TuWe":[1,2],"Tue":[1],
                       "MoTuWeTh":[0,1,2,3],"TuWeTh":[1,2,3],"All":None}[r["days"]],
                      r["ae"])
    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [t["d"] for t in trades]

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(dates, eq, color=color, linewidth=1.2)
    ax.fill_between(dates, 0, eq, alpha=0.08, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
    for j, t in enumerate(trades):
        if t["x"]=="TP": c="#4CAF50"
        elif t["x"]=="SL": c="#F44336"
        else: c="#FFC107"
        ax.scatter(dates[j], eq[j], color=c, s=6, zorder=5)

    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    lab = "rng {}-{} TP={}x ex@{} {} | {}T".format(
        r["mnr"], r["mr"], r["tp"], r["ex"], r["days"], r["n"])
    ax.set_title(lab, fontsize=9, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=8)
    ax.text(0.02, 0.95,
            "WR={:.0f}% PF={:.2f} Tot={:+.0f}p DD={:.0f}p".format(
                r["wr"], r["pf"], r["tot"], r["dd"]),
            transform=ax.transAxes, fontsize=8, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "london_breakout_gbpusd_combos.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
