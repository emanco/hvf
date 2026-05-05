"""SMR M1 vs M5 backtest comparison on the overlapping window.

Uses 40/12.5/40 BOTH on EURGBP. Restricts both datasets to the same
date range (M1 cache horizon: 2026-01-28 to today) so we can compare
apples-to-apples.

Goal: see how much within-bar ordering ambiguity at M5 actually affects
the result vs the finer M1 grid.
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

TRIGGER = 40
TARGET = 12.5
STOP = 40

M1_PATH = Path(__file__).parent / "data/EURGBP_M1.csv"
M5_PATH = Path(__file__).parent / "data/EURGBP_M5.csv"
OUT_PATH = Path(__file__).parent / "charts/smr_m1_vs_m5.png"


def to_utc(broker_unix):
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def build_sessions(rows):
    sessions = {}
    for r in rows:
        utc_t = to_utc(int(r["time"]))
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
            "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"],
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda b: b["utc_t"])
        cap = [b for b in s["bars"] if b["h_utc"] >= 22]
        s["open"] = cap[0]["o"] if cap else None
    return sessions


def simulate(sessions, trigger, target, stop, label=""):
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
                    # SL-first convention: more conservative — assume worst-case
                    # within-bar order. This biases against the strategy and is
                    # the right safety for live deployment.
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


def stats(trades):
    if not trades:
        return None
    pnls = np.array([t["pnl"] for t in trades])
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq).max() if len(eq) > 1 else 0
    wins = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    return {
        "n": len(pnls), "wr": wins / len(pnls) * 100,
        "pf": gp / gl, "tot": pnls.sum(), "dd": dd,
        "tp": sum(1 for t in trades if t["x"] == "TP"),
        "sl": sum(1 for t in trades if t["x"] == "SL"),
        "tm": sum(1 for t in trades if t["x"] == "TIME"),
        "eq": eq, "peak": peak, "pnls": pnls,
        "dates": [pd.Timestamp(t["d"]) for t in trades],
    }


def filter_window(rows, start_date, end_date):
    """Restrict CSV rows to a UTC date window."""
    out = []
    for r in rows:
        utc_t = to_utc(int(r["time"]))
        if start_date <= utc_t.date() <= end_date:
            out.append(r)
    return out


def main():
    df_m1 = pd.read_csv(M1_PATH)
    df_m5 = pd.read_csv(M5_PATH)
    rows_m1 = df_m1.to_dict("records")
    rows_m5 = df_m5.to_dict("records")

    # Determine overlap window
    m1_first = to_utc(int(df_m1.iloc[0]["time"])).date()
    m1_last  = to_utc(int(df_m1.iloc[-1]["time"])).date()
    m5_first = to_utc(int(df_m5.iloc[0]["time"])).date()
    m5_last  = to_utc(int(df_m5.iloc[-1]["time"])).date()
    overlap_start = max(m1_first, m5_first)
    overlap_end   = min(m1_last,  m5_last)
    print(f"M1 range: {m1_first} to {m1_last}  ({len(rows_m1)} bars)")
    print(f"M5 range: {m5_first} to {m5_last}  ({len(rows_m5)} bars)")
    print(f"Overlap window: {overlap_start} to {overlap_end}\n")

    rows_m1_w = filter_window(rows_m1, overlap_start, overlap_end)
    rows_m5_w = filter_window(rows_m5, overlap_start, overlap_end)

    s_m1 = build_sessions(rows_m1_w)
    s_m5 = build_sessions(rows_m5_w)

    t_m1, f_m1, tot_m1 = simulate(s_m1, TRIGGER, TARGET, STOP, "M1")
    t_m5, f_m5, tot_m5 = simulate(s_m5, TRIGGER, TARGET, STOP, "M5")

    r_m1 = stats(t_m1)
    r_m5 = stats(t_m5)

    print(f"{'TF':<4} {'Sess':>5} {'Fired':>6} {'N':>4} {'WR':>5} "
          f"{'PF':>5} {'Tot':>8} {'DD':>5}  Outcomes")
    print("-" * 75)
    for label, r, fired, sess in [("M1", r_m1, f_m1, tot_m1), ("M5", r_m5, f_m5, tot_m5)]:
        print(f"{label:<4} {sess:>5d} {fired:>6d} {r['n']:>4d} {r['wr']:>4.0f}% "
              f"{r['pf']:>5.2f} {r['tot']:>+7.1f}p {r['dd']:>4.0f}p  "
              f"TP={r['tp']} SL={r['sl']} TIME={r['tm']}")

    # ─── Plot ───────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    ax.plot(r_m1["dates"], r_m1["eq"], lw=1.6, color="#1f77b4",
            label=f"M1 (N={r_m1['n']}, PF={r_m1['pf']:.2f}, +{r_m1['tot']:.1f}p)")
    ax.plot(r_m5["dates"], r_m5["eq"], lw=1.6, color="#ff7f0e", linestyle="--",
            label=f"M5 (N={r_m5['n']}, PF={r_m5['pf']:.2f}, +{r_m5['tot']:.1f}p)")
    ax.axhline(0, color="black", lw=0.5, alpha=0.4)
    ax.set_title(
        f"SMR EURGBP 40/12.5/40 — M1 vs M5 on {overlap_start} to {overlap_end}\n"
        f"SL-first convention (conservative). Same period, different bar resolution."
    )
    ax.set_ylabel("Cumulative pips (after 1p spread/trade)")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)

    ax = axes[1]
    width = pd.Timedelta(days=0.4)
    ax.bar([d - width / 2 for d in r_m1["dates"]], r_m1["pnls"],
           width=width, color="#1f77b4", alpha=0.7, label="M1")
    ax.bar([d + width / 2 for d in r_m5["dates"]], r_m5["pnls"],
           width=width, color="#ff7f0e", alpha=0.7, label="M5")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("Per-trade PnL (p)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PATH, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
