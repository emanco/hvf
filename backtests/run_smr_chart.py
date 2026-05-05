"""SMR backtest with equity curve chart — EURGBP 40/10/40 BOTH.

Reads M5 CSV (broker time UTC+3), runs FF Simple Mean Reversion logic
faithful to the live scanner: 22:00 UTC daily-open capture, ±40p trigger,
10p TP / 40p SL, 21:00 UTC force exit, one trade/session, Mon-Fri.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PIP = 0.0001
SPREAD = 1.0
BROKER_OFFSET_HOURS = 3
EXIT_HOUR_UTC = 21
DAYS_MASK = [0, 1, 2, 3, 4]  # Mon-Fri trading days

TRIGGER = 40
TARGET = 12.5
STOP = 40

CSV_PATH = Path(__file__).parent / "data/EURGBP_M5.csv"
OUT_PATH = Path(__file__).parent / "charts/smr_eurgbp_40_125_40.png"


def to_utc(broker_unix):
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def build_sessions(rows):
    sessions = {}
    for r in rows:
        utc_t = to_utc(int(r["time"]))
        h = utc_t.hour
        if h >= 22:
            session_date = utc_t.date()
        elif h < EXIT_HOUR_UTC:
            session_date = utc_t.date() - timedelta(days=1)
        else:
            continue
        s = sessions.setdefault(session_date, {"wd": session_date.weekday(), "bars": []})
        s["bars"].append({
            "h_utc": h, "utc_t": utc_t,
            "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"],
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda b: b["utc_t"])
        cap = [b for b in s["bars"] if b["h_utc"] >= 22]
        s["open"] = cap[0]["o"] if cap else None
    return sessions


def simulate(sessions, trigger, target, stop):
    trades = []
    fired = total = 0
    for sd in sorted(sessions):
        s = sessions[sd]
        if s["open"] is None or s["wd"] in [4, 5]:
            continue
        total += 1
        so = s["open"]
        trading = [b for b in s["bars"] if b["utc_t"].date() > sd or b["h_utc"] >= 22]
        if not trading:
            continue

        ot = None
        done = False
        for i, b in enumerate(trading):
            if done:
                break
            if ot is None:
                if i == 0:
                    continue
                if b["lo"] <= so - trigger * PIP:
                    ep = so - trigger * PIP
                    ot = ("L", ep, ep + target * PIP, ep - stop * PIP, i)
                    fired += 1
                elif b["hi"] >= so + trigger * PIP:
                    ep = so + trigger * PIP
                    ot = ("S", ep, ep - target * PIP, ep + stop * PIP, i)
                    fired += 1
            else:
                d_dir, ep, tp, sl_p, entry_idx = ot
                if i <= entry_idx:
                    continue
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": sd, "pnl": (sl_p - ep) / PIP - SPREAD, "x": "SL"}); done = True
                    elif b["hi"] >= tp:
                        trades.append({"d": sd, "pnl": (tp - ep) / PIP - SPREAD, "x": "TP"}); done = True
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": sd, "pnl": (ep - sl_p) / PIP - SPREAD, "x": "SL"}); done = True
                    elif b["lo"] <= tp:
                        trades.append({"d": sd, "pnl": (ep - tp) / PIP - SPREAD, "x": "TP"}); done = True

        if ot and not done:
            d_dir, ep, *_ = ot
            last = trading[-1]
            pnl = (last["cl"] - ep) / PIP - SPREAD if d_dir == "L" else (ep - last["cl"]) / PIP - SPREAD
            trades.append({"d": sd, "pnl": pnl, "x": "TIME"})

    return trades, fired, total


def main():
    df = pd.read_csv(CSV_PATH)
    rows = df.to_dict("records")
    sessions = build_sessions(rows)

    period = f"{to_utc(rows[0]['time']).date()} to {to_utc(rows[-1]['time']).date()}"
    n_sessions = sum(1 for s in sessions.values() if s["open"] is not None and s["wd"] not in [4, 5])

    trades, fired, total = simulate(sessions, TRIGGER, TARGET, STOP)
    pnls = np.array([t["pnl"] for t in trades])
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = dd.max() if len(dd) else 0
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(pnls) * 100 if len(pnls) else 0
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    pf = gp / gl
    tps = sum(1 for t in trades if t["x"] == "TP")
    sls = sum(1 for t in trades if t["x"] == "SL")
    tms = sum(1 for t in trades if t["x"] == "TIME")

    print(f"Period: {period}")
    print(f"Sessions valid: {n_sessions}, fired: {fired}, fire-rate: {fired/n_sessions*100:.0f}%")
    print(f"Trades: {len(trades)} | WR: {wr:.0f}% | PF: {pf:.2f} | Tot: {pnls.sum():+.1f}p | DD: {max_dd:.1f}p")
    print(f"Outcomes: TP={tps} SL={sls} TIME={tms}")

    dates = [pd.Timestamp(t["d"]) for t in trades]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})

    ax = axes[0]
    ax.plot(dates, eq, lw=1.6, color="#1f77b4", label="Cumulative pips")
    ax.fill_between(dates, eq, peak, alpha=0.15, color="red", label="Drawdown")
    ax.axhline(0, color="black", lw=0.5, alpha=0.4)
    ax.set_title(
        f"SMR EURGBP 40/12.5/40 BOTH — {period}\n"
        f"N={len(trades)}  WR={wr:.0f}%  PF={pf:.2f}  Total={pnls.sum():+.1f}p  "
        f"MaxDD={max_dd:.1f}p  TP={tps} SL={sls} TIME={tms}"
    )
    ax.set_ylabel("Cumulative pips (after 1p spread/trade)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    ax = axes[1]
    colors = ["#2ca02c" if p > 0 else "#d62728" for p in pnls]
    ax.bar(dates, pnls, color=colors, width=2.0, alpha=0.85)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("Per-trade PnL (p)")
    ax.set_xlabel("Date")
    ax.grid(alpha=0.3)

    plt.tight_layout()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PATH, dpi=110, bbox_inches="tight")
    print(f"Saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
