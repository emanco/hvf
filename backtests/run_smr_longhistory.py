"""SMR longhistory backtest — pulls deeper M5 from IC Markets via MT5.

Run on VPS (or any machine with MT5 + .env credentials). Tries to pull
~5 years of M5 EURGBP data, then runs the same SMR simulation as
run_smr_chart.py on it. Saves chart locally next to the script.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from dotenv import load_dotenv
load_dotenv(r"C:/hvf_trader/.env")
import MetaTrader5 as mt5

PIP = 0.0001
SPREAD = 1.0
BROKER_OFFSET_HOURS = 3
EXIT_HOUR_UTC = 21
TRIGGER = 40
TARGET = 12.5
STOP = 40
SYMBOL = "EURGBP"
BARS_TO_PULL = 500_000  # MT5 will return whatever's available

OUT_DIR = Path("C:/hvf_trader/backtests/charts")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "smr_eurgbp_40_125_40_longhistory.png"


def to_utc(broker_unix):
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def build_sessions(bars):
    sessions = {}
    for r in bars:
        utc_t = to_utc(int(r[0]))
        h = utc_t.hour
        if h >= 22:
            sd = utc_t.date()
        elif h < EXIT_HOUR_UTC:
            sd = utc_t.date() - timedelta(days=1)
        else:
            continue
        s = sessions.setdefault(sd, {"wd": sd.weekday(), "bars": []})
        s["bars"].append({
            "h_utc": h, "utc_t": utc_t,
            "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
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
    if not mt5.initialize(
        path=os.getenv("MT5_PATH"),
        login=int(os.getenv("MT5_LOGIN")),
        password=os.getenv("MT5_PASSWORD"),
        server=os.getenv("MT5_SERVER"),
    ):
        print("MT5 init failed:", mt5.last_error())
        sys.exit(1)

    if not mt5.symbol_select(SYMBOL, True):
        print(f"symbol_select({SYMBOL}) failed:", mt5.last_error())

    # copy_rates_range gives deeper history than copy_rates_from_pos.
    # Pull last 6 years (broker-time range).
    end = datetime.now(timezone.utc) + timedelta(hours=BROKER_OFFSET_HOURS)
    start = end - timedelta(days=365 * 6)
    bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, start, end)
    if bars is None or len(bars) == 0:
        print("copy_rates_range empty, falling back to copy_rates_from_pos. Err:", mt5.last_error())
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 200_000)
    if bars is None or len(bars) == 0:
        print("No bars returned. Last error:", mt5.last_error())
        sys.exit(1)
    print(f"Pulled {len(bars)} M5 bars for {SYMBOL}")
    print(f"  First: {to_utc(bars[0][0])}")
    print(f"  Last:  {to_utc(bars[-1][0])}")

    sessions = build_sessions(bars)
    period = f"{to_utc(bars[0][0]).date()} to {to_utc(bars[-1][0]).date()}"
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

    print(f"\nPeriod: {period}")
    print(f"Sessions valid: {n_sessions}, fired: {fired} ({fired/n_sessions*100:.0f}%)")
    print(f"Trades: {len(trades)} | WR: {wr:.0f}% | PF: {pf:.2f} | "
          f"Tot: {pnls.sum():+.1f}p | MaxDD: {max_dd:.1f}p")
    print(f"Outcomes: TP={tps} SL={sls} TIME={tms}")

    # Yearly breakdown
    print("\nYearly:")
    by_year = {}
    for t in trades:
        y = t["d"].year
        by_year.setdefault(y, []).append(t["pnl"])
    for y, pl in sorted(by_year.items()):
        wins_y = sum(1 for p in pl if p > 0)
        gp_y = sum(p for p in pl if p > 0)
        gl_y = abs(sum(p for p in pl if p <= 0)) or 0.001
        print(f"  {y}: N={len(pl):>3}  WR={wins_y/len(pl)*100:.0f}%  "
              f"PF={gp_y/gl_y:.2f}  Tot={sum(pl):+.1f}p")

    import pandas as pd
    dates = [pd.Timestamp(t["d"]) for t in trades]

    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    ax.plot(dates, eq, lw=1.4, color="#1f77b4", label="Cumulative pips")
    ax.fill_between(dates, eq, peak, alpha=0.15, color="red", label="Drawdown")
    ax.axhline(0, color="black", lw=0.5, alpha=0.4)
    ax.set_title(
        f"SMR EURGBP 40/12.5/40 BOTH — {period} (IC Markets MT5)\n"
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
    plt.savefig(OUT_PATH, dpi=110, bbox_inches="tight")
    print(f"\nSaved chart: {OUT_PATH}")
    mt5.shutdown()


if __name__ == "__main__":
    main()
