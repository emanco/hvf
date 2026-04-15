"""Thursday SHORT with breakeven move and earlier exit variants."""
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


def simulate(trigger, target, stop, max_range, exit_hour, be_move):
    """
    be_move: if True, once trade reaches +1 pip profit (price drops 1 pip
    below entry), move SL to breakeven (entry price). Time exit losses
    become 0 instead of negative.
    """
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
        be_activated = False
        current_sl = 0

        for b in trading:
            if done:
                continue

            # Force exit at exit_hour
            if b["h"] >= exit_hour and ot:
                ep = ot[0]
                pnl = (ep - b["cl"]) / pip - spread
                if be_activated and pnl < 0:
                    pnl = -spread  # breakeven = lose only spread
                trades.append({"d": d, "pnl": pnl, "x": "TIME", "et": et, "rng": s["range"]})
                done = True
                continue

            if ot:
                ep, tp, sl_p = ot[0], ot[1], current_sl

                # Check breakeven move: if price has dropped 1 pip below entry
                if be_move and not be_activated:
                    if b["lo"] <= ep - 1 * pip:
                        be_activated = True
                        current_sl = ep + spread * pip  # breakeven + spread

                # SL check
                if b["hi"] >= current_sl:
                    if be_activated:
                        pnl = -spread  # breakeven
                        trades.append({"d": d, "pnl": pnl, "x": "BE", "et": et, "rng": s["range"]})
                    else:
                        pnl = (ep - current_sl) / pip - spread
                        trades.append({"d": d, "pnl": pnl, "x": "SL", "et": et, "rng": s["range"]})
                    done = True
                    continue

                # TP check
                if b["lo"] <= tp:
                    pnl = (ep - tp) / pip - spread
                    trades.append({"d": d, "pnl": pnl, "x": "TP", "et": et, "rng": s["range"]})
                    done = True
                    continue
            else:
                if b["hi"] >= so + trigger * pip:
                    ep = so + trigger * pip
                    sl_price = ep + stop * pip
                    current_sl = sl_price
                    ot = (ep, ep - target * pip, sl_price)
                    et = "{:02d}:{:02d}".format(b["h"], b["m"])
                    be_activated = False

        if ot and not done:
            ep = ot[0]
            last = trading[-1] if trading else s["bars"][-1]
            pnl = (ep - last["cl"]) / pip - spread
            if be_activated and pnl < 0:
                pnl = -spread
            trades.append({"d": d, "pnl": pnl, "x": "TIME", "et": et, "rng": s["range"]})
    return trades


# Test variants
configs = [
    ("Baseline: exit@6, no BE", 5, 2, 8, 20, 6, False),
    ("Exit@5:30, no BE", 5, 2, 8, 20, 5.5, False),
    ("Exit@5, no BE", 5, 2, 8, 20, 5, False),
    ("Exit@6, with BE move", 5, 2, 8, 20, 6, True),
    ("Exit@5:30, with BE move", 5, 2, 8, 20, 5.5, True),
    ("Exit@5, with BE move", 5, 2, 8, 20, 5, True),
]

# We need half-hour exit, so adjust: exit_hour 5.5 means exit at 05:30
# Fix: use minutes-based check instead. Let me handle in the simulate by
# treating exit_hour as float: 5.5 = 05:30

# Actually the current code checks b["h"] >= exit_hour which works for
# integers. For 5.5, b["h"]=5 and b["m"]=30 would need: h + m/60 >= 5.5
# Let me fix this properly.

def simulate_v2(trigger, target, stop, max_range, exit_hour_decimal, be_move):
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
        be_activated = False
        current_sl = 0

        for b in trading:
            if done:
                continue

            bar_time = b["h"] + b["m"] / 60.0

            # Force exit
            if bar_time >= exit_hour_decimal and ot:
                ep = ot[0]
                pnl = (ep - b["cl"]) / pip - spread
                if be_activated and pnl < 0:
                    pnl = -spread
                trades.append({"d": d, "pnl": pnl, "x": "TIME", "et": et, "rng": s["range"], "be": be_activated})
                done = True
                continue

            if ot:
                ep, tp = ot[0], ot[1]

                # BE move check
                if be_move and not be_activated:
                    if b["lo"] <= ep - 1 * pip:
                        be_activated = True
                        current_sl = ep  # move to breakeven (entry)

                # SL check
                if b["hi"] >= current_sl:
                    if be_activated:
                        pnl = -spread
                        trades.append({"d": d, "pnl": pnl, "x": "BE", "et": et, "rng": s["range"], "be": True})
                    else:
                        pnl = (ep - current_sl) / pip - spread
                        trades.append({"d": d, "pnl": pnl, "x": "SL", "et": et, "rng": s["range"], "be": False})
                    done = True
                    continue

                # TP check
                if b["lo"] <= tp:
                    pnl = (ep - tp) / pip - spread
                    trades.append({"d": d, "pnl": pnl, "x": "TP", "et": et, "rng": s["range"], "be": be_activated})
                    done = True
                    continue
            else:
                if bar_time < exit_hour_decimal - 0.5:  # don't enter in last 30 min
                    if b["hi"] >= so + trigger * pip:
                        ep = so + trigger * pip
                        current_sl = ep + stop * pip
                        ot = (ep, ep - target * pip, current_sl)
                        et = "{:02d}:{:02d}".format(b["h"], b["m"])
                        be_activated = False

        if ot and not done:
            ep = ot[0]
            last = trading[-1] if trading else s["bars"][-1]
            pnl = (ep - last["cl"]) / pip - spread
            if be_activated and pnl < 0:
                pnl = -spread
            trades.append({"d": d, "pnl": pnl, "x": "TIME", "et": et, "rng": s["range"], "be": be_activated})
    return trades


configs = [
    ("Baseline: exit@06:00, no BE", 5, 2, 8, 20, 6.0, False),
    ("Exit@05:30, no BE", 5, 2, 8, 20, 5.5, False),
    ("Exit@05:00, no BE", 5, 2, 8, 20, 5.0, False),
    ("Exit@06:00, BE move", 5, 2, 8, 20, 6.0, True),
    ("Exit@05:30, BE move", 5, 2, 8, 20, 5.5, True),
    ("Exit@05:00, BE move", 5, 2, 8, 20, 5.0, True),
]

print("Thursday SHORT T5/T2/S8 rng<20 — Optimization Variants\n")
print("{:<35} {:>4} {:>5} {:>7} {:>7} {:>7}".format("Config", "N", "WR", "PF", "Exp", "Tot"))
print("-" * 70)

all_results = []
for label, trig, tgt, sl, mr, exit_h, be in configs:
    trades = simulate_v2(trig, tgt, sl, mr, exit_h, be)
    if not trades:
        print("{:<35} {:>4}".format(label, 0))
        continue
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    wr = w / len(trades) * 100
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("{:<35} {:>4} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.1f}p".format(
        label, len(trades), wr, gp / gl, np.mean(pnls), sum(pnls)))
    all_results.append((label, trades))

# Detail the best ones
for label, trades in all_results:
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    print("\n--- {} ({} trades, WR={:.0f}%) ---".format(label, len(trades), w/len(trades)*100))
    for t in trades:
        be_tag = " [BE]" if t.get("be") else ""
        marker = " WIN" if t["pnl"] > 0 else ""
        print("  {} rng={:>3.0f}p entry={} {:>4} pnl={:>+5.1f}p{}{}".format(
            t["d"], t["rng"], t["et"], t["x"], t["pnl"], be_tag, marker))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

n = len(all_results)
fig, axes = plt.subplots(3, 2, figsize=(16, 16))
fig.suptitle("EURGBP Thursday SHORT T5/T2/S8 rng<20 — Optimization Variants\n(M5, 8 months)",
             fontsize=13, fontweight="bold")

for idx, (label, trades) in enumerate(all_results):
    ax = axes[idx // 2][idx % 2]
    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [str(t["d"])[5:] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(pnls) * 100
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(range(len(eq)), eq, color=color, linewidth=2)
    ax.fill_between(range(len(eq)), 0, eq, alpha=0.1, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

    for j, t in enumerate(trades):
        if t["x"] == "TP":
            c, m = "#4CAF50", "^"
        elif t["x"] == "SL":
            c, m = "#F44336", "v"
        elif t["x"] == "BE":
            c, m = "#9C27B0", "D"
        else:
            c, m = "#FFC107", "o"
        ax.scatter(j, eq[j], color=c, s=60, zorder=5, marker=m, edgecolors="white", linewidth=0.5)

    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, fontsize=6, rotation=45, ha="right")
    ax.set_title(label, fontsize=10, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=9)

    stats = "WR={:.0f}%  PF={:.2f}  Tot={:+.1f}p  DD={:.1f}p".format(wr, gp/gl, sum(pnls), dd)
    ax.text(0.02, 0.95, stats, transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_thu_optimized.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart saved: {}".format(outpath))

mt5.shutdown()
