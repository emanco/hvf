"""Day-by-day comparison of Asian Gravity across all weekdays and triggers."""
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
    sessions[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

for s in sessions.values():
    form = [b for b in s["bars"] if b["h"] < 2]
    if form:
        s["open"] = s["bars"][0]["o"]
        s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip
    else:
        s["range"] = 999

first_d = min(sessions)
last_d = max(sessions)


def simulate(trigger, target, stop, max_range, days):
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if s["wd"] not in days or s["range"] > max_range or s["range"] < 1:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot = None
        done = False
        for b in trading:
            if done:
                continue
            if ot:
                ep, tp, sl_p = ot
                if b["lo"] <= sl_p:
                    trades.append({"d": d, "pnl": (sl_p - ep) / pip - spread, "x": "SL"})
                    done = True
                    continue
                if b["hi"] >= tp:
                    trades.append({"d": d, "pnl": (tp - ep) / pip - spread, "x": "TP"})
                    done = True
                    continue
            else:
                if b["lo"] <= so - trigger * pip:
                    ep = so - trigger * pip
                    ot = (ep, ep + target * pip, ep - stop * pip)
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            trades.append({"d": d, "pnl": (last["cl"] - ot[0]) / pip - spread, "x": "TIME"})
    return trades


def calc_stats(trades):
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "tot": 0, "exp": 0}
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    return {"n": len(trades), "wr": w / len(trades) * 100, "pf": gp / gl,
            "tot": sum(pnls), "exp": np.mean(pnls)}


# Run per-day analysis for multiple trigger levels and range filters
day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
triggers = [2, 3, 4, 5, 7]
max_ranges = [15, 20, 25]
target = 2
stop = 6

# Collect all data for CSV output (for charting)
import json
all_data = []

print("Data: {} to {}, {} sessions".format(first_d, last_d, len(sessions)))
print()

for mr in max_ranges:
    print("=" * 80)
    print("  Range filter < {} pips  |  Target={}p  Stop={}p".format(mr, target, stop))
    print("=" * 80)
    print()

    for trig in triggers:
        print("  Trigger = {} pips:".format(trig))
        print("  {:<6} {:>5} {:>5} {:>7} {:>7} {:>7}".format(
            "Day", "N", "WR", "PF", "Exp", "Total"))
        print("  " + "-" * 45)

        for day_idx in range(5):
            trades = simulate(trig, target, stop, mr, [day_idx])
            s = calc_stats(trades)
            if s["n"] == 0:
                print("  {:<6} {:>5}".format(day_names[day_idx], 0))
            else:
                flag = " ***" if s["wr"] >= 80 and s["n"] >= 5 else " **" if s["wr"] >= 70 else ""
                print("  {:<6} {:>5} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.1f}p{}".format(
                    day_names[day_idx], s["n"], s["wr"], s["pf"], s["exp"], s["tot"], flag))

            all_data.append({
                "trigger": trig, "max_range": mr, "day": day_names[day_idx],
                "day_idx": day_idx, "n": s["n"], "wr": s["wr"],
                "pf": s["pf"], "tot": s["tot"], "exp": s["exp"],
            })

        # Also show "All days"
        trades_all = simulate(trig, target, stop, mr, [0, 1, 2, 3, 4])
        sa = calc_stats(trades_all)
        if sa["n"] > 0:
            print("  {:<6} {:>5} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.1f}p".format(
                "ALL", sa["n"], sa["wr"], sa["pf"], sa["exp"], sa["tot"]))
        print()

# Save data for charting
import tempfile
with open(os.path.join(tempfile.gettempdir(), "asian_gravity_daily.json"), "w") as f:
    json.dump(all_data, f)
print("Data saved to /tmp/asian_gravity_daily.json")

# Generate chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(3, 3, figsize=(18, 14))
fig.suptitle(
    "EURGBP Asian Gravity - Day-by-Day Comparison (M5, {} to {})\n"
    "LONG only, Target=2p, Stop=6p".format(first_d, last_d),
    fontsize=13, fontweight="bold")

colors = ["#F44336", "#FF9800", "#4CAF50", "#2196F3", "#9C27B0"]  # Mon-Fri
bar_width = 0.15

for col, mr in enumerate(max_ranges):
    mr_data = [d for d in all_data if d["max_range"] == mr]

    # WR chart
    ax = axes[0][col]
    for i, trig in enumerate(triggers):
        trig_data = [d for d in mr_data if d["trigger"] == trig]
        x = np.arange(5) + i * bar_width
        wrs = [next((d["wr"] for d in trig_data if d["day_idx"] == di), 0) for di in range(5)]
        ax.bar(x, wrs, bar_width, label="T{}".format(trig), alpha=0.8)
    ax.set_title("Win Rate (rng<{})".format(mr), fontsize=10, fontweight="bold")
    ax.set_ylabel("WR %")
    ax.set_xticks(np.arange(5) + bar_width * 2)
    ax.set_xticklabels(day_names)
    ax.axhline(y=80, color="red", linestyle="--", alpha=0.5, linewidth=1)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.2)
    ax.set_ylim(0, 105)

    # PF chart
    ax = axes[1][col]
    for i, trig in enumerate(triggers):
        trig_data = [d for d in mr_data if d["trigger"] == trig]
        x = np.arange(5) + i * bar_width
        pfs = [min(next((d["pf"] for d in trig_data if d["day_idx"] == di), 0), 10) for di in range(5)]
        ax.bar(x, pfs, bar_width, label="T{}".format(trig), alpha=0.8)
    ax.set_title("Profit Factor (rng<{})".format(mr), fontsize=10, fontweight="bold")
    ax.set_ylabel("PF")
    ax.set_xticks(np.arange(5) + bar_width * 2)
    ax.set_xticklabels(day_names)
    ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.5, linewidth=1)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.2)

    # Total pips chart
    ax = axes[2][col]
    for i, trig in enumerate(triggers):
        trig_data = [d for d in mr_data if d["trigger"] == trig]
        x = np.arange(5) + i * bar_width
        tots = [next((d["tot"] for d in trig_data if d["day_idx"] == di), 0) for di in range(5)]
        c = ["#4CAF50" if t > 0 else "#F44336" for t in tots]
        ax.bar(x, tots, bar_width, label="T{}".format(trig), alpha=0.8)
    ax.set_title("Total Pips (rng<{})".format(mr), fontsize=10, fontweight="bold")
    ax.set_ylabel("Pips")
    ax.set_xticks(np.arange(5) + bar_width * 2)
    ax.set_xticklabels(day_names)
    ax.axhline(y=0, color="gray", linestyle="-", alpha=0.5, linewidth=1)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.2)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_daily_compare.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("Chart saved: {}".format(outpath))

mt5.shutdown()
