"""Thursday Asian Gravity — LONG vs SHORT comparison across all params."""
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
print("Thursday sessions: {}, {} to {}".format(len(thu), min(thu), max(thu)))


def simulate(trigger, target, stop, max_range, direction):
    """direction: 'LONG' or 'SHORT'"""
    trades = []
    for d in sorted(thu):
        s = thu[d]
        if s["range"] > max_range or s["range"] < 1:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot = None
        done = False
        et = ""
        for b in trading:
            if done:
                continue
            if ot:
                di, ep, tp, sl_p = ot
                if di == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": d, "pnl": (sl_p - ep) / pip - spread, "x": "SL", "et": et, "rng": s["range"]})
                        done = True; continue
                    if b["hi"] >= tp:
                        trades.append({"d": d, "pnl": (tp - ep) / pip - spread, "x": "TP", "et": et, "rng": s["range"]})
                        done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": d, "pnl": (ep - sl_p) / pip - spread, "x": "SL", "et": et, "rng": s["range"]})
                        done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": d, "pnl": (ep - tp) / pip - spread, "x": "TP", "et": et, "rng": s["range"]})
                        done = True; continue
            else:
                if direction == "LONG" and b["lo"] <= so - trigger * pip:
                    ep = so - trigger * pip
                    ot = ("L", ep, ep + target * pip, ep - stop * pip)
                    et = "{:02d}:{:02d}".format(b["h"], b["m"])
                elif direction == "SHORT" and b["hi"] >= so + trigger * pip:
                    ep = so + trigger * pip
                    ot = ("S", ep, ep - target * pip, ep + stop * pip)
                    et = "{:02d}:{:02d}".format(b["h"], b["m"])
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            di, ep, tp, sl_p = ot
            if di == "L":
                pnl = (last["cl"] - ep) / pip - spread
            else:
                pnl = (ep - last["cl"]) / pip - spread
            trades.append({"d": d, "pnl": pnl, "x": "TIME", "et": et, "rng": s["range"]})
    return trades


# Compare LONG vs SHORT across key configs
print("\n{:<45} {:>4} {:>5} {:>7} {:>7} {:>7}".format("Config", "N", "WR", "PF", "Exp", "Tot"))
print("-" * 80)

results = []
for direction in ["LONG", "SHORT"]:
    for trigger in [2, 3, 4, 5, 7]:
        for target in [2, 3, 4, 5]:
            for stop in [4, 5, 6, 8, 10]:
                for mr in [15, 20, 25, 30, 50]:
                    trades = simulate(trigger, target, stop, mr, direction)
                    if len(trades) < 3:
                        continue
                    pnls = [t["pnl"] for t in trades]
                    w = sum(1 for p in pnls if p > 0)
                    wr = w / len(trades) * 100
                    gp = sum(p for p in pnls if p > 0)
                    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
                    eq = np.cumsum(pnls)
                    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
                    results.append({
                        "dir": direction, "trig": trigger, "tgt": target,
                        "sl": stop, "mr": mr, "n": len(trades), "wr": wr,
                        "pf": gp / gl, "exp": np.mean(pnls), "tot": sum(pnls),
                        "dd": dd, "trades": trades,
                    })

results.sort(key=lambda x: (-x["wr"], -x["tot"]))

seen = set()
ct = 0
for r in results:
    if ct >= 40:
        break
    lab = "{} T{}/T{}/S{} rng<{}".format(r["dir"], r["trig"], r["tgt"], r["sl"], r["mr"])
    if lab in seen:
        continue
    seen.add(lab)
    f = " ***" if r["wr"] >= 80 and r["n"] >= 5 else " **" if r["wr"] >= 80 else " *" if r["wr"] >= 70 else ""
    print("{:<45} {:>4} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.1f}p{}".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"], f))
    ct += 1

# Best SHORT configs detail
print("\n=== BEST SHORT CONFIGS (detail) ===")
short_results = [r for r in results if r["dir"] == "SHORT" and r["wr"] >= 60]
short_results.sort(key=lambda x: (-x["wr"], -x["tot"]))
for r in short_results[:5]:
    lab = "SHORT T{}/T{}/S{} rng<{}".format(r["trig"], r["tgt"], r["sl"], r["mr"])
    print("\n--- {} ({} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.1f}p) ---".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"]))
    for t in r["trades"]:
        marker = " <--" if t["pnl"] > 0 else ""
        print("  {} rng={:>4.0f}p entry={} {:>4} pnl={:>+5.1f}p{}".format(
            t["d"], t["rng"], t["et"], t["x"], t["pnl"], marker))

# Best LONG configs detail
print("\n=== BEST LONG CONFIGS (detail) ===")
long_results = [r for r in results if r["dir"] == "LONG" and r["wr"] >= 60]
long_results.sort(key=lambda x: (-x["wr"], -x["tot"]))
for r in long_results[:3]:
    lab = "LONG T{}/T{}/S{} rng<{}".format(r["trig"], r["tgt"], r["sl"], r["mr"])
    print("\n--- {} ({} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.1f}p) ---".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"]))
    for t in r["trades"]:
        marker = " <--" if t["pnl"] > 0 else ""
        print("  {} rng={:>4.0f}p entry={} {:>4} pnl={:>+5.1f}p{}".format(
            t["d"], t["rng"], t["et"], t["x"], t["pnl"], marker))

# Chart: LONG vs SHORT side by side for best configs
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Pick top configs for each direction
chart_configs = []
for direction in ["LONG", "SHORT"]:
    dir_res = [r for r in results if r["dir"] == direction and r["n"] >= 3]
    dir_res.sort(key=lambda x: (-x["wr"], -x["tot"]))
    seen_c = set()
    for r in dir_res[:3]:
        lab = "{} T{}/T{}/S{} rng<{}".format(r["dir"], r["trig"], r["tgt"], r["sl"], r["mr"])
        if lab not in seen_c:
            chart_configs.append(r)
            seen_c.add(lab)

n_charts = min(len(chart_configs), 6)
rows = (n_charts + 1) // 2
fig, axes = plt.subplots(rows, 2, figsize=(14, 5 * rows))
if rows == 1:
    axes = [axes]
fig.suptitle("EURGBP Asian Gravity THURSDAY - LONG vs SHORT (M5, 8 months)",
             fontsize=13, fontweight="bold")

for idx, r in enumerate(chart_configs[:n_charts]):
    ax = axes[idx // 2][idx % 2]
    trades = r["trades"]
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
    lab = "{} T{}/T{}/S{} rng<{} | {}T".format(
        r["dir"], r["trig"], r["tgt"], r["sl"], r["mr"], r["n"])
    ax.set_title(lab, fontsize=10, fontweight="bold",
                 color="#2196F3" if r["dir"] == "LONG" else "#F44336")
    ax.set_ylabel("Pips", fontsize=9)
    stats = "WR={:.0f}% PF={:.2f} Tot={:+.0f}p".format(wr, gp / gl, sum(pnls))
    ax.text(0.02, 0.95, stats, transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.2)

# Hide unused axes
for idx in range(n_charts, rows * 2):
    axes[idx // 2][idx % 2].set_visible(False)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_thu_long_vs_short.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart saved: {}".format(outpath))

mt5.shutdown()
