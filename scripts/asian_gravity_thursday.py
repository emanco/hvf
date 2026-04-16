"""Deep dive on Thursday Asian Gravity — all parameter combos."""
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

# Thursday sessions only
thu_sessions = {d: s for d, s in sessions.items() if s["wd"] == 3}
print("Thursday sessions: {}".format(len(thu_sessions)))
print("Date range: {} to {}".format(min(thu_sessions), max(thu_sessions)))
print()

# Show all Thursday session profiles
print("=== ALL THURSDAY SESSIONS ===")
print("{:<12} {:>6} {:>8} {:>10}".format("Date", "Range", "Open", "Status"))
print("-" * 40)
for d in sorted(thu_sessions):
    s = thu_sessions[d]
    so = s["open"]
    rng = s["range"]
    trading = [b for b in s["bars"] if b["h"] >= 2]

    # Max drift below open
    max_drift_down = 0
    max_drift_up = 0
    for b in trading:
        drift_down = (so - b["lo"]) / pip
        drift_up = (b["hi"] - so) / pip
        max_drift_down = max(max_drift_down, drift_down)
        max_drift_up = max(max_drift_up, drift_up)

    print("{} {:>5.0f}p  {:.5f}  drift: -{:.0f}p/+{:.0f}p".format(
        d, rng, so, max_drift_down, max_drift_up))
print()


def simulate(trigger, target, stop, max_range):
    trades = []
    for d in sorted(thu_sessions):
        s = thu_sessions[d]
        if s["range"] > max_range or s["range"] < 1:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot = None
        done = False
        entry_time = ""
        for b in trading:
            if done:
                continue
            if ot:
                ep, tp, sl_p = ot
                if b["lo"] <= sl_p:
                    trades.append({"d": d, "pnl": (sl_p - ep) / pip - spread, "x": "SL",
                                   "et": entry_time, "rng": s["range"]})
                    done = True
                    continue
                if b["hi"] >= tp:
                    trades.append({"d": d, "pnl": (tp - ep) / pip - spread, "x": "TP",
                                   "et": entry_time, "rng": s["range"]})
                    done = True
                    continue
            else:
                if b["lo"] <= so - trigger * pip:
                    ep = so - trigger * pip
                    ot = (ep, ep + target * pip, ep - stop * pip)
                    entry_time = "{:02d}:{:02d}".format(b["h"], b["m"])
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            trades.append({"d": d, "pnl": (last["cl"] - ot[0]) / pip - spread, "x": "TIME",
                           "et": entry_time, "rng": s["range"]})
    return trades


# Exhaustive sweep for Thursday
print("=== THURSDAY PARAMETER SWEEP ===")
print("{:<40} {:>4} {:>5} {:>7} {:>7} {:>7}".format("Config", "N", "WR", "PF", "Exp", "Tot"))
print("-" * 75)

results = []
for trigger in [2, 3, 4, 5, 7, 10]:
    for target in [2, 3, 4, 5]:
        for stop in [3, 4, 5, 6, 8, 10, 15]:
            for max_range in [10, 12, 15, 20, 25, 30, 50]:
                trades = simulate(trigger, target, stop, max_range)
                if len(trades) < 3:
                    continue
                pnls = [t["pnl"] for t in trades]
                w = sum(1 for p in pnls if p > 0)
                wr = w / len(trades) * 100
                gp = sum(p for p in pnls if p > 0)
                gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
                pf = gp / gl
                results.append({
                    "n": len(trades), "wr": wr, "pf": pf,
                    "exp": np.mean(pnls), "tot": sum(pnls),
                    "trig": trigger, "tgt": target, "sl": stop, "mr": max_range,
                    "trades": trades,
                })

results.sort(key=lambda x: (-x["wr"], -x["tot"], -x["pf"]))

seen = set()
ct = 0
for r in results:
    if ct >= 30:
        break
    lab = "T{}/T{}/S{} rng<{}".format(r["trig"], r["tgt"], r["sl"], r["mr"])
    if lab in seen:
        continue
    seen.add(lab)
    f = " ***" if r["wr"] >= 80 and r["n"] >= 5 else " **" if r["wr"] >= 80 else " *" if r["wr"] >= 70 else ""
    print("{:<40} {:>4} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.1f}p{}".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"], f))
    ct += 1

# Detail the best configs
print("\n=== TRADE-BY-TRADE DETAIL FOR TOP CONFIGS ===")
top_configs = [
    (3, 2, 6, 20, "T3/T2/S6 rng<20"),
    (3, 2, 6, 25, "T3/T2/S6 rng<25"),
    (3, 3, 6, 25, "T3/T3/S6 rng<25"),
    (4, 2, 6, 25, "T4/T2/S6 rng<25"),
    (7, 2, 5, 25, "T7/T2/S5 rng<25"),
    (2, 2, 6, 20, "T2/T2/S6 rng<20"),
]

for trigger, target, stop, max_range, label in top_configs:
    trades = simulate(trigger, target, stop, max_range)
    if not trades:
        continue
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001

    print("\n--- {} ({} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.1f}p) ---".format(
        label, len(trades), w / len(trades) * 100, gp / gl, sum(pnls)))
    for t in trades:
        marker = " <--" if t["pnl"] > 0 else ""
        print("  {} rng={:>4.0f}p  entry={} {:>4}  pnl={:>+5.1f}p{}".format(
            t["d"], t["rng"], t["et"], t["x"], t["pnl"], marker))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

best_configs_chart = [
    (3, 2, 6, 25, "T3/T2/S6 rng<25"),
    (3, 3, 6, 25, "T3/T3/S6 rng<25"),
    (2, 2, 6, 20, "T2/T2/S6 rng<20"),
    (7, 2, 5, 25, "T7/T2/S5 rng<25"),
]

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("EURGBP Asian Gravity - THURSDAY Deep Dive (M5, 8 months)", fontsize=13, fontweight="bold")

for idx, (trigger, target, stop, max_range, label) in enumerate(best_configs_chart):
    ax = axes[idx // 2][idx % 2]
    trades = simulate(trigger, target, stop, max_range)
    if not trades:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center")
        ax.set_title(label)
        continue

    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [str(t["d"])[5:] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(pnls) * 100
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(range(len(eq)), eq, color=color, linewidth=2)
    ax.fill_between(range(len(eq)), 0, eq, alpha=0.1, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)

    for j, t in enumerate(trades):
        if t["x"] == "TP":
            c, m = "#4CAF50", "^"
        elif t["x"] == "SL":
            c, m = "#F44336", "v"
        else:
            c, m = "#FFC107", "o"
        ax.scatter(j, eq[j], color=c, s=60, zorder=5, marker=m, edgecolors="white", linewidth=0.5)

    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, fontsize=7, rotation=45)
    ax.set_title("{} | {} trades".format(label, len(trades)), fontsize=10, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=9)

    stats = "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p".format(wr, gp / gl, sum(pnls))
    ax.text(0.02, 0.95, stats, transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.2)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_thursday.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart saved: {}".format(outpath))

mt5.shutdown()
