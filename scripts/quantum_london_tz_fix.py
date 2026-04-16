"""Quantum London backtest with CORRECT timezone — daily open at 22:00 UTC (00:00 GMT+2)."""
import sys, os
from datetime import datetime, timedelta, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

PAIRS = {
    "EURGBP": {"pip": 0.0001, "spread": 1.0},
    "EURCHF": {"pip": 0.0001, "spread": 1.5},
}

def fetch_m5(symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 50000)
    if rates is None or len(rates) == 0:
        return None
    return rates


def build_sessions_gmt2(rates, pip):
    """Build sessions with daily open at 22:00 UTC (00:00 GMT+2).

    A 'session' runs from 22:00 UTC to 05:00 UTC next day.
    The daily open is the 22:00 UTC bar open price.
    Trading window: 00:00-05:00 UTC (after 2h of drift from open).
    """
    sessions = {}
    current_session = None
    current_date = None

    for r in rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        h = ts.hour

        # Session starts at 22:00 UTC
        if h == 22 and ts.minute == 0:
            # New session
            current_date = ts.date()
            current_session = {
                "open_date": current_date,
                "daily_open": r[1],  # bar open at 22:00 UTC = daily open GMT+2
                "bars": [],
                "wd": ts.weekday(),
            }
            sessions[current_date] = current_session

        # Collect bars from 22:00 to 05:00 next day
        if current_session is not None:
            if h >= 22 or h < 6:
                current_session["bars"].append({
                    "h": h, "m": ts.minute,
                    "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
                    "utc_hour": h,
                })
            elif h >= 6:
                current_session = None  # session ended

    # Compute formation range (22:00-00:00 = first 2 hours)
    for s in sessions.values():
        form = [b for b in s["bars"] if b["utc_hour"] >= 22]
        if form:
            s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip
        else:
            s["range"] = 0

    return sessions


def simulate(sessions, trigger, target, stop, spread, days, max_range,
             direction="BOTH", exit_hour_utc=5):
    """Trading window: 00:00-05:00 UTC (2h after daily open at 22:00)."""
    pip = 0.0001
    trades = []

    for d in sorted(sessions):
        s = sessions[d]
        if s["wd"] not in days:
            continue
        if max_range and s["range"] > max_range:
            continue

        daily_open = s["daily_open"]
        # Trading bars: 00:00-05:00 UTC (the core Asian session)
        trading = [b for b in s["bars"] if b["utc_hour"] < exit_hour_utc]
        if not trading:
            continue

        ot = None
        done = False

        for b in trading:
            if done:
                continue
            if ot:
                d_dir, ep, tp_p, sl_p = ot
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": d, "pnl": (sl_p-ep)/pip-spread, "x": "SL", "dir": "LONG"})
                        done = True; continue
                    if b["hi"] >= tp_p:
                        trades.append({"d": d, "pnl": (tp_p-ep)/pip-spread, "x": "TP", "dir": "LONG"})
                        done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": d, "pnl": (ep-sl_p)/pip-spread, "x": "SL", "dir": "SHORT"})
                        done = True; continue
                    if b["lo"] <= tp_p:
                        trades.append({"d": d, "pnl": (ep-tp_p)/pip-spread, "x": "TP", "dir": "SHORT"})
                        done = True; continue
            else:
                # LONG: price below daily open by trigger pips
                if direction in ("BOTH", "LONG") and b["lo"] <= daily_open - trigger * pip:
                    ep = daily_open - trigger * pip
                    ot = ("L", ep, ep + target * pip, ep - stop * pip)
                # SHORT: price above daily open by trigger pips
                elif direction in ("BOTH", "SHORT") and b["hi"] >= daily_open + trigger * pip:
                    ep = daily_open + trigger * pip
                    ot = ("S", ep, ep - target * pip, ep + stop * pip)

        if ot and not done:
            d_dir, ep, tp_p, sl_p = ot
            last = trading[-1]
            if d_dir == "L":
                pnl = (last["cl"] - ep) / pip - spread
            else:
                pnl = (ep - last["cl"]) / pip - spread
            trades.append({"d": d, "pnl": pnl, "x": "TIME",
                           "dir": "LONG" if d_dir == "L" else "SHORT"})

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
    return {"n": len(trades), "wr": w/len(trades)*100, "pf": gp/gl,
            "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd, "cl": mc}


configs = [
    # label, trigger, target, stop, days, max_range, direction, exit_hour
    ("GMT+2 T8/T5/S18 MonThu Both ex@5", 8, 5, 18, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T5/T2/S8 Thu SHORT ex@5", 5, 2, 8, [3], 20, "SHORT", 5),
    ("GMT+2 T5/T3/S10 MonThu Both ex@5", 5, 3, 10, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T10/T5/S18 MonThu Both ex@5", 10, 5, 18, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T8/T5/S18 MonThu Both ex@6", 8, 5, 18, [0,1,2,3], 20, "BOTH", 6),
    ("GMT+2 T5/T5/S15 MonThu Both ex@5", 5, 5, 15, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T7/T5/S15 MonThu Both ex@5", 7, 5, 15, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T8/T5/S18 AllWeek Both ex@5", 8, 5, 18, [0,1,2,3,4], 30, "BOTH", 5),
    ("GMT+2 T5/T2/S8 MonThu SHORT ex@5", 5, 2, 8, [0,1,2,3], 20, "SHORT", 5),
    ("GMT+2 T5/T2/S8 MonThu Both ex@5", 5, 2, 8, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T3/T2/S8 MonThu Both ex@5", 3, 2, 8, [0,1,2,3], 20, "BOTH", 5),
    ("GMT+2 T8/T3/S18 MonThu Both ex@5", 8, 3, 18, [0,1,2,3], 20, "BOTH", 5),
]

for symbol, cfg in PAIRS.items():
    pip = cfg["pip"]; spread = cfg["spread"]
    rates = fetch_m5(symbol)
    if rates is None:
        print("{}: No M5 data".format(symbol)); continue

    first_ts = datetime.fromtimestamp(rates[0][0], tz=timezone.utc)
    last_ts = datetime.fromtimestamp(rates[-1][0], tz=timezone.utc)
    sessions = build_sessions_gmt2(rates, pip)

    print("\n" + "=" * 80)
    print("  {} — Quantum London GMT+2 Backtest".format(symbol))
    print("  Daily open = 22:00 UTC (00:00 GMT+2)")
    print("  {} to {}, {} sessions".format(first_ts.date(), last_ts.date(), len(sessions)))
    print("=" * 80)
    print("\n{:<45} {:>4} {:>5} {:>7} {:>7} {:>7} {:>5} {:>4}".format(
        "Config", "N", "WR", "PF", "Exp", "Tot", "DD", "CL"))
    print("-" * 85)

    for label, trig, tgt, sl, days, mr, dirn, ex_h in configs:
        trades = simulate(sessions, trig, tgt, sl, spread, days, mr, dirn, ex_h)
        if not trades:
            continue
        s = stats(trades)
        f = " ***" if s["pf"] > 1.3 and s["n"] >= 10 else " **" if s["pf"] > 1.0 else ""
        print("{:<45} {:>4} {:>4.0f}% {:>7.2f} {:>+6.2f}p {:>+6.0f}p {:>4.0f}p {:>3}{}".format(
            label, s["n"], s["wr"], s["pf"], s["exp"], s["tot"], s["dd"], s["cl"], f))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 1, figsize=(16, 12))
fig.suptitle("Quantum London — CORRECT Timezone (Daily Open = 22:00 UTC / 00:00 GMT+2)\nT8/T5/S18, Mon-Thu, Both dirs, exit@05:00 UTC",
             fontsize=13, fontweight="bold")

for idx, (symbol, cfg) in enumerate(PAIRS.items()):
    ax = axes[idx]
    rates = fetch_m5(symbol)
    if rates is None:
        ax.text(0.5, 0.5, "No data", ha="center", va="center"); continue

    pip = cfg["pip"]; spread = cfg["spread"]
    sessions = build_sessions_gmt2(rates, pip)
    trades = simulate(sessions, 8, 5, 18, spread, [0,1,2,3], 20, "BOTH", 5)
    if not trades:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center"); continue

    pnls = [t["pnl"] for t in trades]; eq = np.cumsum(pnls)
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
        ax.scatter(dates[j], eq[j], color=c, s=20, zorder=5, marker=m, edgecolors="white", linewidth=0.3)

    ax.set_title("{} | {} trades | spread={}p".format(symbol, len(trades), spread),
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=10)
    ax.text(0.02, 0.95,
            "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
                s["wr"], s["pf"], s["tot"], s["dd"]),
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "quantum_london_gmt2.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))
mt5.shutdown()
