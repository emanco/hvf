"""Compare Quantum London (FF mean-reversion) on EURCHF vs EURGBP.

Tests both our 40/12.5/40 IC Markets tuning AND the FF canonical 30/7.5/30
on each pair, with days [6,0,1,2,3] (Sun-Thu captures).

EURCHF data is M15 (bars are 15min), pre-converted to UTC datetime strings.
EURGBP data is M5 broker-time (UTC+3) Unix timestamps.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
PIP = 0.0001
SPREAD = 1.0  # 1p entry-side cost
EXIT_HOUR_UTC = 21
CAPTURE_HOUR_UTC = 22
DAYS = [6, 0, 1, 2, 3]  # Sun-Thu captures


def load_eurgbp_m5():
    df = pd.read_csv(ROOT / "data/EURGBP_M5.csv")
    df["utc_t"] = df["time"].apply(
        lambda t: datetime.fromtimestamp(t, tz=timezone.utc) - timedelta(hours=3)
    )
    return df


def load_eurchf_m15():
    df = pd.read_csv(ROOT / "data/EURCHF_M15.csv")
    df["utc_t"] = pd.to_datetime(df["time"], utc=True)
    return df


def build_sessions(df):
    """Group bars into sessions keyed by capture date."""
    sessions = {}
    for _, r in df.iterrows():
        utc_t = r["utc_t"]
        if isinstance(utc_t, pd.Timestamp):
            utc_t = utc_t.to_pydatetime()
        h = utc_t.hour
        if h >= CAPTURE_HOUR_UTC:
            sd = utc_t.date()
        elif h < EXIT_HOUR_UTC:
            sd = utc_t.date() - timedelta(days=1)
        else:
            continue
        if sd not in sessions:
            sessions[sd] = {"wd": sd.weekday(), "bars": []}
        sessions[sd]["bars"].append({
            "h_utc": h, "utc_t": utc_t,
            "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"],
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda b: b["utc_t"])
        cap = [b for b in s["bars"] if b["h_utc"] >= CAPTURE_HOUR_UTC]
        s["open"] = cap[0]["o"] if cap else None
    return sessions


def simulate(sessions, trigger, target, stop):
    trades = []
    fired = total = 0
    for sd in sorted(sessions):
        s = sessions[sd]
        if s["open"] is None or s["wd"] not in DAYS:
            continue
        total += 1
        so = s["open"]
        trading = [b for b in s["bars"] if b["utc_t"].date() > sd or b["h_utc"] >= CAPTURE_HOUR_UTC]
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


def stats(trades):
    if not trades:
        return None
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    wins = (pnls > 0).sum()
    gp = pnls[pnls > 0].sum() if wins else 0
    gl = abs(pnls[pnls <= 0].sum()) if (pnls <= 0).sum() else 0.001
    eq = np.cumsum(pnls)
    dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0
    return {"n": n, "wr": wins/n*100, "pf": gp/gl, "tot": pnls.sum(),
            "dd": dd, "eq": eq, "mar": pnls.sum()/dd if dd > 0 else 0,
            "tps": sum(1 for t in trades if t["x"] == "TP"),
            "sls": sum(1 for t in trades if t["x"] == "SL"),
            "tms": sum(1 for t in trades if t["x"] == "TIME"),
            "dates": [pd.Timestamp(t["d"]) for t in trades]}


def main():
    print("Loading data...")
    eurchf = load_eurchf_m15()
    eurgbp = load_eurgbp_m5()
    print(f"  EURCHF M15: {len(eurchf)} bars, {eurchf['utc_t'].iloc[0]} → {eurchf['utc_t'].iloc[-1]}")
    print(f"  EURGBP M5:  {len(eurgbp)} bars, {eurgbp['utc_t'].iloc[0]} → {eurgbp['utc_t'].iloc[-1]}\n")

    print("Building sessions...")
    s_eurchf = build_sessions(eurchf)
    s_eurgbp = build_sessions(eurgbp)
    valid_chf = sum(1 for s in s_eurchf.values() if s["open"] is not None and s["wd"] in DAYS)
    valid_gbp = sum(1 for s in s_eurgbp.values() if s["open"] is not None and s["wd"] in DAYS)
    print(f"  EURCHF: {valid_chf} valid sessions")
    print(f"  EURGBP: {valid_gbp} valid sessions\n")

    variants = [
        ("FF canonical 30/7.5/30",  30, 7.5, 30),
        ("Our IC tuning 40/12.5/40", 40, 12.5, 40),
        ("Tighter 25/7.5/25",        25, 7.5, 25),
        ("FF wider 35/10/35",        35, 10,   35),
        ("Aggressive 20/5/20",       20, 5,    20),
    ]

    results = {}
    for pair_name, sessions, n_sessions in [
        ("EURCHF", s_eurchf, valid_chf),
        ("EURGBP", s_eurgbp, valid_gbp),
    ]:
        print(f"=== {pair_name} ({n_sessions} sessions) ===")
        print(f"{'Variant':<28} {'Fired':>6} {'Rate':>5} {'N':>4} {'WR':>5} {'PF':>5} {'Tot':>9} {'DD':>6} {'MAR':>5}  Outcomes")
        print("-" * 110)
        for label, trig, tgt, stp in variants:
            trades, fired, total = simulate(sessions, trig, tgt, stp)
            r = stats(trades)
            if r:
                rate = fired / max(1, total) * 100
                print(f"{label:<28} {fired:>6d} {rate:>4.0f}% {r['n']:>4d} "
                      f"{r['wr']:>4.0f}% {r['pf']:>5.2f} {r['tot']:>+8.1f}p "
                      f"{r['dd']:>5.0f}p {r['mar']:>5.2f}  | TP={r['tps']} SL={r['sls']} TIME={r['tms']}")
                results[(pair_name, label)] = r
        print()

    # ─── Plot equity curves for top variants per pair ──────────────────
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, pair_name in zip(axes, ["EURCHF", "EURGBP"]):
        for label, _, _, _ in variants:
            r = results.get((pair_name, label))
            if r is None or r["n"] == 0: continue
            ax.plot(r["dates"], r["eq"],
                    label=f"{label}  N={r['n']} PF={r['pf']:.2f} Tot={r['tot']:+.0f}p",
                    lw=1.4)
        ax.axhline(0, color="black", lw=0.5)
        ax.set_title(f"{pair_name} — QL/SMR variants")
        ax.set_ylabel("Cumulative pips" if pair_name == "EURCHF" else "")
        ax.set_xlabel("Date")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=0.3)
        plt.setp(ax.get_xticklabels(), rotation=30)
    plt.suptitle("Quantum London / FF Simple Mean Reversion — pair × params comparison",
                 fontsize=12)
    plt.tight_layout()
    OUT = ROOT / "charts/ql_eurchf_vs_eurgbp.png"
    plt.savefig(OUT, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
