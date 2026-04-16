"""London Breakout GBPUSD — Refine to reduce drawdowns."""
import sys, os
from datetime import datetime, timedelta, timezone
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
print("GBPUSD H1: {} to {}, {} bars".format(first.date(), last.date(), len(rates)))

# Build sessions with extra context
sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5:
        continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"bars": [], "weekday": ts.weekday()}
    sessions[bd]["bars"].append({
        "h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4], "vol": r[5],
    })


def simulate(max_range, min_range, tp_mult, exit_hour, spread,
             days=None, direction=None, max_asian_bars_trend=None):
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

        # Optional: check if Asian session was trending (close near high or low)
        if max_asian_bars_trend is not None:
            asian_open = asian[0]["o"]
            asian_close = asian[-1]["cl"]
            asian_mid = (a_high + a_low) / 2
            # If close is in top 25% of range = uptrend, bottom 25% = downtrend
            asian_pos = (asian_close - a_low) / (a_high - a_low) if a_high != a_low else 0.5

        london = [b for b in s["bars"] if 8 <= b["h"] < exit_hour]
        if not london:
            continue

        tp_dist = a_range * tp_mult * pip
        sp = spread * pip
        traded = False

        for b in london:
            if traded:
                break

            # LONG breakout
            if direction != "SHORT" and b["hi"] > a_high + sp:
                if max_asian_bars_trend is not None and asian_pos > 0.75:
                    pass  # skip: Asian already trended up, breakout may be exhaustion
                else:
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
                            hit = "TP"; pnl = (tp - entry)/pip - spread; break
                    if hit is None:
                        last_cl = remaining[-1]["cl"] if remaining else b["cl"]
                        pnl = (last_cl - entry)/pip - spread; hit = "TIME"
                    trades.append({"d": d, "dir": "LONG", "pnl": pnl, "x": hit,
                                   "rng": a_range, "wd": s["weekday"]})
                    traded = True

            # SHORT breakout
            if not traded and direction != "LONG" and b["lo"] < a_low - sp:
                if max_asian_bars_trend is not None and asian_pos < 0.25:
                    pass  # skip: Asian already trended down
                else:
                    entry = a_low - sp
                    sl = a_high + sp
                    tp = entry - tp_dist
                    risk = (sl - entry) / pip
                    remaining = [bb for bb in london if bb["h"] >= b["h"]]
                    hit = None
                    for rb in remaining:
                        if rb["hi"] >= sl:
                            hit = "SL"; pnl = -risk - spread; break
                        if rb["lo"] <= tp:
                            hit = "TP"; pnl = (entry - tp)/pip - spread; break
                    if hit is None:
                        last_cl = remaining[-1]["cl"] if remaining else b["cl"]
                        pnl = (entry - last_cl)/pip - spread; hit = "TIME"
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
    return {"n": len(trades), "wr": w/len(trades)*100, "pf": gp/gl,
            "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd}


# Test the baseline first
baseline = simulate(20, 15, 1.0, 17, 1.0)
bs = stats(baseline)
print("\nBaseline (rng 15-20, TP=1.0x, exit@17): {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
    bs["n"], bs["wr"], bs["pf"], bs["tot"], bs["dd"]))

# Day of week analysis
print("\nDay of week breakdown (baseline):")
for wd in range(5):
    day_trades = [t for t in baseline if t["wd"] == wd]
    if day_trades:
        ds = stats(day_trades)
        dn = ["Mon","Tue","Wed","Thu","Fri"][wd]
        print("  {}: {:>3} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p".format(
            dn, ds["n"], ds["wr"], ds["pf"], ds["tot"]))

# Direction breakdown
print("\nDirection breakdown:")
for d in ["LONG", "SHORT"]:
    dt = [t for t in baseline if t["dir"] == d]
    if dt:
        ds = stats(dt)
        print("  {}: {:>3} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p".format(
            d, ds["n"], ds["wr"], ds["pf"], ds["tot"]))

# Test refinements
print("\n" + "=" * 80)
print("  REFINEMENT TESTS")
print("=" * 80)
print("\n{:<55} {:>4} {:>5} {:>7} {:>7} {:>7} {:>6}".format(
    "Config", "N", "WR", "PF", "Exp", "Tot", "DD"))
print("-" * 95)

configs = [
    ("Baseline: rng 15-20 TP=1.0x ex@17", 20, 15, 1.0, 17, 1.0, None, None, None),
    # Tighter range
    ("Tight range: rng 15-18", 18, 15, 1.0, 17, 1.0, None, None, None),
    ("Tight range: rng 16-20", 20, 16, 1.0, 17, 1.0, None, None, None),
    # TP variations
    ("TP=0.8x", 20, 15, 0.8, 17, 1.0, None, None, None),
    ("TP=1.2x", 20, 15, 1.2, 17, 1.0, None, None, None),
    # Earlier exit
    ("Exit@15", 20, 15, 1.0, 15, 1.0, None, None, None),
    ("Exit@13", 20, 15, 1.0, 13, 1.0, None, None, None),
    # Day filters
    ("Tue-Thu only", 20, 15, 1.0, 17, 1.0, [1,2,3], None, None),
    ("Mon-Wed only", 20, 15, 1.0, 17, 1.0, [0,1,2], None, None),
    ("Tue-Fri only", 20, 15, 1.0, 17, 1.0, [1,2,3,4], None, None),
    # Direction only
    ("SHORT only", 20, 15, 1.0, 17, 1.0, None, "SHORT", None),
    ("LONG only", 20, 15, 1.0, 17, 1.0, None, "LONG", None),
    # Asian trend filter (skip if Asian was already trending in breakout direction)
    ("Asian trend filter", 20, 15, 1.0, 17, 1.0, None, None, True),
    # Wider spread assumption
    ("Spread=1.5", 20, 15, 1.0, 17, 1.5, None, None, None),
    # Combined best
    ("Tue-Thu + SHORT", 20, 15, 1.0, 17, 1.0, [1,2,3], "SHORT", None),
    ("Tue-Thu + trend filter", 20, 15, 1.0, 17, 1.0, [1,2,3], None, True),
    ("SHORT + trend filter", 20, 15, 1.0, 17, 1.0, None, "SHORT", True),
    # TP=0.8 + tighter combos
    ("TP=0.8x + Tue-Thu", 20, 15, 0.8, 17, 1.0, [1,2,3], None, None),
    ("TP=0.8x + trend filter", 20, 15, 0.8, 17, 1.0, None, None, True),
    ("rng 15-18 + exit@15", 18, 15, 1.0, 15, 1.0, None, None, None),
    ("rng 15-18 + Tue-Thu", 18, 15, 1.0, 17, 1.0, [1,2,3], None, None),
]

results = []
for label, mr, mnr, tp, ex, sp, days, dirn, trend_f in configs:
    trades = simulate(mr, mnr, tp, ex, sp, days, dirn, trend_f)
    if len(trades) < 20:
        continue
    s = stats(trades)
    results.append((label, s, trades))
    f = " ***" if s["pf"] > 1.3 else " **" if s["pf"] > 1.0 else ""
    print("{:<55} {:>4} {:>4.0f}% {:>7.2f} {:>+6.1f}p {:>+6.0f}p {:>5.0f}p{}".format(
        label, s["n"], s["wr"], s["pf"], s["exp"], s["tot"], s["dd"], f))

# Chart top 6 variants
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

results.sort(key=lambda x: -x[1]["pf"])
chart_configs = results[:6]

fig, axes = plt.subplots(3, 2, figsize=(16, 16))
fig.suptitle("GBPUSD London Breakout — Refinement Variants (H1, 8 years)",
             fontsize=13, fontweight="bold")

for idx, (label, s, trades) in enumerate(chart_configs):
    ax = axes[idx // 2][idx % 2]
    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [t["d"] for t in trades]

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(dates, eq, color=color, linewidth=1.2)
    ax.fill_between(dates, 0, eq, alpha=0.08, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
    for j, t in enumerate(trades):
        if t["x"] == "TP": c = "#4CAF50"
        elif t["x"] == "SL": c = "#F44336"
        else: c = "#FFC107"
        ax.scatter(dates[j], eq[j], color=c, s=5, zorder=5)

    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title(label, fontsize=9, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=8)
    ax.text(0.02, 0.95,
            "WR={:.0f}% PF={:.2f} Tot={:+.0f}p DD={:.0f}p N={}".format(
                s["wr"], s["pf"], s["tot"], s["dd"], s["n"]),
            transform=ax.transAxes, fontsize=8, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "london_breakout_gbpusd_refined.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
