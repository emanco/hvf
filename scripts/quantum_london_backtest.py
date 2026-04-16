"""Quantum London / Asian Mean Reversion backtest — EURGBP + EURCHF.
Tests recommended params: trigger 8, target 5, stop 18, Mon-Thu, both dirs.
Also tests original community params and variations."""
import sys, os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

PAIRS = {
    "EURGBP": {"pip": 0.0001, "spread": 1.0},
    "EURCHF": {"pip": 0.0001, "spread": 1.5},  # wider spread on EURCHF
}


def fetch_m5(symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 50000)
    if rates is None or len(rates) == 0:
        return None
    return rates


def build_sessions(rates, pip):
    sessions = {}
    for r in rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        if ts.weekday() >= 5 or ts.hour >= 6:
            continue
        bd = ts.date()
        if bd not in sessions:
            sessions[bd] = {"wd": ts.weekday(), "bars": []}
        sessions[bd]["bars"].append({
            "h": ts.hour, "m": ts.minute,
            "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
        })

    for s in sessions.values():
        if s["bars"]:
            s["open"] = s["bars"][0]["o"]
            form = [b for b in s["bars"] if b["h"] < 2]
            if form:
                s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip
            else:
                s["range"] = 0
    return sessions


def simulate(sessions, trigger, target, stop, spread, days, max_range,
             direction="BOTH", exit_hour=5):
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if s["wd"] not in days:
            continue
        if max_range and s["range"] > max_range:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2 and b["h"] < exit_hour]
        if not trading:
            continue

        ot = None
        done = False
        pip = 0.0001  # will be overridden per pair but all our pairs are 0.0001

        for b in trading:
            if done:
                continue
            if ot:
                d_dir, ep, tp, sl_p = ot
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": d, "pnl": (sl_p - ep) / pip - spread, "x": "SL", "dir": "LONG"})
                        done = True; continue
                    if b["hi"] >= tp:
                        trades.append({"d": d, "pnl": (tp - ep) / pip - spread, "x": "TP", "dir": "LONG"})
                        done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": d, "pnl": (ep - sl_p) / pip - spread, "x": "SL", "dir": "SHORT"})
                        done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": d, "pnl": (ep - tp) / pip - spread, "x": "TP", "dir": "SHORT"})
                        done = True; continue
            else:
                # LONG: price dropped below open by trigger pips
                if direction in ("BOTH", "LONG") and b["lo"] <= so - trigger * pip:
                    ep = so - trigger * pip
                    ot = ("L", ep, ep + target * pip, ep - stop * pip)

                # SHORT: price rose above open by trigger pips
                elif direction in ("BOTH", "SHORT") and b["hi"] >= so + trigger * pip:
                    ep = so + trigger * pip
                    ot = ("S", ep, ep - target * pip, ep + stop * pip)

        if ot and not done:
            d_dir, ep, tp, sl_p = ot
            last = trading[-1]
            if d_dir == "L":
                pnl = (last["cl"] - ep) / pip - spread
            else:
                pnl = (ep - last["cl"]) / pip - spread
            trades.append({"d": d, "pnl": pnl, "x": "TIME", "dir": "LONG" if d_dir == "L" else "SHORT"})

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
    c = 0; mc = 0
    for p in pnls:
        if p <= 0: c += 1; mc = max(mc, c)
        else: c = 0
    return {"n": len(trades), "wr": w / len(trades) * 100, "pf": gp / gl,
            "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd, "cl": mc}


# Parameter grid
configs = [
    # label, trigger, target, stop, days, max_range, direction, exit_hour
    ("Recommended: T8/T5/S18 MonThu Both ex@5", 8, 5, 18, [0,1,2,3], 20, "BOTH", 5),
    ("Current: T5/T2/S8 Thu SHORT ex@6", 5, 2, 8, [3], 20, "SHORT", 6),
    ("Wide: T10/T7/S20 MonThu Both ex@5", 10, 7, 20, [0,1,2,3], 20, "BOTH", 5),
    ("Tight: T5/T3/S10 MonThu Both ex@5", 5, 3, 10, [0,1,2,3], 20, "BOTH", 5),
    ("Community: T8/T5/S18 AllWeek Both ex@5", 8, 5, 18, [0,1,2,3,4], 20, "BOTH", 5),
    ("NoFilter: T8/T5/S18 MonThu Both ex@5 rng99", 8, 5, 18, [0,1,2,3], 99, "BOTH", 5),
    ("Longer: T8/T5/S18 MonThu Both ex@6", 8, 5, 18, [0,1,2,3], 20, "BOTH", 6),
    ("T7/T4/S15 MonThu Both ex@5", 7, 4, 15, [0,1,2,3], 20, "BOTH", 5),
    ("T6/T4/S12 MonThu Both ex@5", 6, 4, 12, [0,1,2,3], 20, "BOTH", 5),
    ("T10/T5/S18 MonThu Both ex@5", 10, 5, 18, [0,1,2,3], 20, "BOTH", 5),
    ("T8/T5/S18 MonWed Both ex@5", 8, 5, 18, [0,1,2], 20, "BOTH", 5),
    ("T8/T5/S18 TuThu Both ex@5", 8, 5, 18, [1,2,3], 20, "BOTH", 5),
]

for symbol, cfg in PAIRS.items():
    pip = cfg["pip"]
    spread = cfg["spread"]
    rates = fetch_m5(symbol)
    if rates is None:
        print("{}: No M5 data".format(symbol))
        continue

    first = datetime.fromtimestamp(rates[0][0], tz=timezone.utc).date()
    last = datetime.fromtimestamp(rates[-1][0], tz=timezone.utc).date()
    sessions = build_sessions(rates, pip)

    print("\n" + "=" * 80)
    print("  {} — Quantum London Backtest (M5, {} to {})".format(symbol, first, last))
    print("  Spread: {} pips".format(spread))
    print("=" * 80)
    print("\n{:<50} {:>4} {:>5} {:>7} {:>7} {:>7} {:>5} {:>4}".format(
        "Config", "N", "WR", "PF", "Exp", "Tot", "DD", "CL"))
    print("-" * 95)

    best = None
    all_results = []
    for label, trig, tgt, sl, days, mr, dirn, ex_h in configs:
        trades = simulate(sessions, trig, tgt, sl, spread, days, mr, dirn, ex_h)
        if not trades:
            continue
        s = stats(trades)
        f = " ***" if s["pf"] > 1.3 and s["n"] >= 10 else " **" if s["pf"] > 1.0 else ""
        print("{:<50} {:>4} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.0f}p {:>4.0f}p {:>3}{}".format(
            label, s["n"], s["wr"], s["pf"], s["exp"], s["tot"], s["dd"], s["cl"], f))
        all_results.append((label, s, trades))
        if best is None or s["pf"] > best[1]["pf"]:
            best = (label, s, trades)

    # Detail the recommended config
    rec_trades = simulate(sessions, 8, 5, 18, spread, [0,1,2,3], 20, "BOTH", 5)
    if rec_trades:
        print("\n--- Recommended config detail ({}) ---".format(symbol))
        for t in rec_trades:
            marker = " WIN" if t["pnl"] > 0 else ""
            print("  {} {:>5} {:>4} {:>+5.1f}p{}".format(t["d"], t["dir"], t["x"], t["pnl"], marker))

        # Direction breakdown
        for dr in ["LONG", "SHORT"]:
            dt = [t for t in rec_trades if t["dir"] == dr]
            if dt:
                dw = sum(1 for t in dt if t["pnl"] > 0)
                print("  {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
                    dr, len(dt), dw / len(dt) * 100, sum(t["pnl"] for t in dt)))

        # Sizing
        s = stats(rec_trades)
        pip_usd = 12.7 if symbol == "EURGBP" else 10.0
        for risk in [1.0, 2.0]:
            lots = (10000 * risk / 100) / (18 * pip_usd)
            t_usd = s["tot"] * lots * pip_usd
            d_usd = s["dd"] * lots * pip_usd
            months = (last - first).days / 30
            print("  {}% risk ($10k): lots={:.2f}, Total=${:+,.0f}, Monthly=${:+,.0f}, DD=${:,.0f}".format(
                risk, lots, t_usd, t_usd / months if months > 0 else 0, d_usd))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(16, 12))
fig.suptitle("Quantum London / Asian Mean Reversion\nRecommended: T8/T5/S18, Mon-Thu, Both dirs, exit@05:00",
             fontsize=13, fontweight="bold")

for idx, (symbol, cfg) in enumerate(PAIRS.items()):
    ax = axes[idx]
    rates = fetch_m5(symbol)
    if rates is None:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.set_title(symbol)
        continue

    pip = cfg["pip"]; spread = cfg["spread"]
    sessions = build_sessions(rates, pip)
    trades = simulate(sessions, 8, 5, 18, spread, [0,1,2,3], 20, "BOTH", 5)
    if not trades:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center")
        ax.set_title(symbol)
        continue

    pnls = [t["pnl"] for t in trades]
    eq = np.cumsum(pnls)
    dates = [t["d"] for t in trades]
    s = stats(trades)

    color = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(dates, eq, color=color, linewidth=2)
    ax.fill_between(dates, 0, eq, alpha=0.1, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

    for j, t in enumerate(trades):
        if t["x"] == "TP": c, m = "#4CAF50", "^"
        elif t["x"] == "SL": c, m = "#F44336", "v"
        else: c, m = "#FFC107", "o"
        ax.scatter(dates[j], eq[j], color=c, s=20, zorder=5, marker=m,
                   edgecolors="white", linewidth=0.3)

    ax.set_title("{} — {} trades | spread={}p".format(symbol, len(trades), spread),
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=10)
    ax.text(0.02, 0.95,
            "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p  ConsL={}".format(
                s["wr"], s["pf"], s["tot"], s["dd"], s["cl"]),
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "quantum_london_backtest.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
