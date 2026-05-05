"""Quantum London / Asian Mean Reversion — exhaustive parameter grid on IC Markets EURGBP M5.

Goal: find a parameter combination with positive expectancy on IC Markets data
(after recent live results showed PF 0.5-0.8). Mirrors the methodology in
scripts/ql_trigger_compare.py so results are apples-to-apples vs the prior
Dukascopy result (PF 21.85 — suspect, not used here).

Data: /tmp/eurgbp_m5_icm.csv (50k M5 bars, pulled via mt5.copy_rates_from_pos
from the IC Markets demo account on the VPS). NOTE: IC Markets MT5 returns
broker time (UTC+3); we subtract 3h to convert to real UTC before window
filtering. (The capture/trade windows are defined in real UTC.)

Sessions: capture at 22:00 UTC, trading 00:00-05:00 UTC, force-exit at 05:00.
Mon-Fri trading day = Sun-Thu capture night.

Spread cost: 1p on entry side (matches existing backtest).
"""
import os
import csv
import json
import itertools
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

DATA = "/tmp/eurgbp_m5_icm.csv"
OUT_FULL = "/tmp/ql_icm_grid_full.csv"
OUT_TOP = "/tmp/ql_icm_grid_top.txt"

PIP = 0.0001
SPREAD = 1.0  # 1p on entry side (matches existing backtest in ql_trigger_compare.py)
EXIT_HOUR = 5  # 05:00 UTC force exit
DAYS_MASK = [0, 1, 2, 3, 4]  # Mon-Fri trading days
BROKER_OFFSET_HOURS = 3  # IC Markets server is UTC+3 — convert to real UTC

# ------- Parameter grid -------
TRIGGERS = [5, 6, 7, 8, 9, 10, 12]
TARGETS = [3, 5, 7, 10, "open"]
STOPS = [8, 12, 15, 18, 25]
DIRECTIONS = ["BOTH", "LONG", "SHORT"]
RANGE_FILTERS = [999, 30, 20, 15]
CONFIRMATIONS = [False, True]  # Y/N: require next M5 bar to close back inside trigger band


def load_sessions(path):
    df = pd.read_csv(path)
    # Convert broker UTC+3 → real UTC by subtracting 3h
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True) - pd.Timedelta(hours=BROKER_OFFSET_HOURS)
    sessions = {}
    for _, row in df.iterrows():
        ts = row["time"]
        h = ts.hour
        if h >= 22:
            sd = (ts + pd.Timedelta(days=1)).date()
        elif h < 6:
            sd = ts.date()
        else:
            continue
        if sd not in sessions:
            sessions[sd] = {"wd": None, "open": None, "bars": []}
        sessions[sd]["bars"].append({
            "h": h, "m": ts.minute,
            "o": row["open"], "hi": row["high"], "lo": row["low"], "cl": row["close"],
            "ts": ts,
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda x: x["ts"])
        cap_bars = [b for b in s["bars"] if b["h"] >= 22]
        if cap_bars:
            s["open"] = cap_bars[0]["o"]
        all_window = [b for b in s["bars"] if b["h"] >= 22 or b["h"] < EXIT_HOUR]
        if all_window:
            hi = max(b["hi"] for b in all_window)
            lo = min(b["lo"] for b in all_window)
            s["asian_range_pips"] = (hi - lo) / PIP
        else:
            s["asian_range_pips"] = 0
        s["wd"] = sd.weekday()
    return sessions


def simulate(sessions, trigger, target, stop, direction, max_range, confirmation):
    """Mirrors ql_trigger_compare.simulate logic exactly:
      - check SL first, then TP per bar (conservative)
      - force-close at last trading bar close if no exit
      - SPREAD deducted on entry
    Adds: direction filter, range filter, optional confirmation, target='open' (=trigger).
    """
    trades = []
    target_pips = trigger if target == "open" else target

    for sd in sorted(sessions):
        s = sessions[sd]
        if s["open"] is None:
            continue
        if s["wd"] not in DAYS_MASK:
            continue
        if s["asian_range_pips"] > max_range:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if 0 <= b["h"] < EXIT_HOUR]
        if not trading:
            continue

        ot = None  # open trade tuple
        done = False
        pending_dir = None  # for confirmation: which side just triggered, awaiting next bar close

        for b in trading:
            if done:
                continue

            # If we have a pending confirmation request, check this bar's close:
            if pending_dir is not None and ot is None:
                # Confirmation: next bar's close must be back inside the trigger band
                # (i.e. closer to so than the trigger level, mean-reversion confirmation).
                if pending_dir == "L":
                    # We triggered LONG (price went BELOW so - trig). Confirm: close > so - trig
                    if b["cl"] > so - trigger * PIP:
                        ep = so - trigger * PIP
                        sl_p = ep - stop * PIP
                        tp = ep + target_pips * PIP
                        ot = ("L", ep, tp, sl_p)
                    pending_dir = None
                else:
                    if b["cl"] < so + trigger * PIP:
                        ep = so + trigger * PIP
                        sl_p = ep + stop * PIP
                        tp = ep - target_pips * PIP
                        ot = ("S", ep, tp, sl_p)
                    pending_dir = None
                # Don't also check trigger on this bar — we just resolved a pending one.
                continue

            if ot:
                d_dir, ep, tp, sl_p = ot
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": sd, "pnl": (sl_p - ep) / PIP - SPREAD, "x": "SL", "dir": "LONG"})
                        done = True; continue
                    if b["hi"] >= tp:
                        trades.append({"d": sd, "pnl": (tp - ep) / PIP - SPREAD, "x": "TP", "dir": "LONG"})
                        done = True; continue
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": sd, "pnl": (ep - sl_p) / PIP - SPREAD, "x": "SL", "dir": "SHORT"})
                        done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": sd, "pnl": (ep - tp) / PIP - SPREAD, "x": "TP", "dir": "SHORT"})
                        done = True; continue
            else:
                # Detect trigger
                hit_long = b["lo"] <= so - trigger * PIP
                hit_short = b["hi"] >= so + trigger * PIP
                if direction == "LONG":
                    hit_short = False
                elif direction == "SHORT":
                    hit_long = False

                if hit_long:
                    if confirmation:
                        pending_dir = "L"
                    else:
                        ep = so - trigger * PIP
                        sl_p = ep - stop * PIP
                        tp = ep + target_pips * PIP
                        ot = ("L", ep, tp, sl_p)
                elif hit_short:
                    if confirmation:
                        pending_dir = "S"
                    else:
                        ep = so + trigger * PIP
                        sl_p = ep + stop * PIP
                        tp = ep - target_pips * PIP
                        ot = ("S", ep, tp, sl_p)

        if ot and not done:
            d_dir, ep, tp, sl_p = ot
            last = trading[-1]
            pnl = (last["cl"] - ep) / PIP - SPREAD if d_dir == "L" else (ep - last["cl"]) / PIP - SPREAD
            trades.append({"d": sd, "pnl": pnl, "x": "TIME", "dir": "LONG" if d_dir == "L" else "SHORT"})
    return trades


def stats(trades):
    if not trades:
        return None
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    w = int((pnls > 0).sum())
    gp = float(pnls[pnls > 0].sum())
    gl = float(abs(pnls[pnls <= 0].sum()))
    pf = gp / gl if gl > 0 else float("inf")
    eq = np.cumsum(pnls)
    dd = float((np.maximum.accumulate(eq) - eq).max()) if n > 1 else 0.0
    return {
        "n": n,
        "wr": w / n * 100,
        "pf": pf,
        "tot": float(pnls.sum()),
        "exp": float(pnls.mean()),
        "dd": dd,
    }


def main():
    print("Loading IC Markets EURGBP M5 sessions...")
    sessions = load_sessions(DATA)
    sds = sorted(sessions)
    print(f"  {len(sessions)} sessions, {sds[0]} → {sds[-1]}")

    # Recent 90-day cutoff (using last session date)
    last_date = sds[-1]
    cutoff_90 = last_date - timedelta(days=90)
    cutoff_60 = last_date - timedelta(days=60)
    print(f"  Last session: {last_date}  Recent-90 cutoff: {cutoff_90}  Recent-60 cutoff: {cutoff_60}")

    combos = list(itertools.product(TRIGGERS, TARGETS, STOPS, DIRECTIONS, RANGE_FILTERS, CONFIRMATIONS))
    print(f"  Total combos: {len(combos)}")

    rows = []
    for i, (trig, tgt, stp, dr, rf, conf) in enumerate(combos):
        if i % 100 == 0:
            print(f"  [{i}/{len(combos)}]")
        trades = simulate(sessions, trig, tgt, stp, dr, rf, conf)
        s_full = stats(trades)
        trades_90 = [t for t in trades if t["d"] >= cutoff_90]
        s_90 = stats(trades_90)
        trades_60 = [t for t in trades if t["d"] >= cutoff_60]
        s_60 = stats(trades_60)
        if s_full is None:
            continue
        rows.append({
            "trigger": trig,
            "target": tgt if isinstance(tgt, str) else tgt,
            "stop": stp,
            "direction": dr,
            "range_filter": rf,
            "confirmation": "Y" if conf else "N",
            "n": s_full["n"],
            "wr": round(s_full["wr"], 1),
            "pf": round(s_full["pf"], 3),
            "tot": round(s_full["tot"], 1),
            "exp": round(s_full["exp"], 3),
            "dd": round(s_full["dd"], 1),
            "n_90": s_90["n"] if s_90 else 0,
            "pf_90": round(s_90["pf"], 3) if s_90 else 0,
            "tot_90": round(s_90["tot"], 1) if s_90 else 0,
            "wr_90": round(s_90["wr"], 1) if s_90 else 0,
            "n_60": s_60["n"] if s_60 else 0,
            "pf_60": round(s_60["pf"], 3) if s_60 else 0,
            "tot_60": round(s_60["tot"], 1) if s_60 else 0,
            "wr_60": round(s_60["wr"], 1) if s_60 else 0,
        })

    # Save full grid
    with open(OUT_FULL, "w", newline="") as f:
        wri = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wri.writeheader()
        for r in rows:
            wri.writerow(r)
    print(f"\nSaved full grid: {OUT_FULL} ({len(rows)} rows)")

    # ----- Reporting -----
    df = pd.DataFrame(rows)

    out = []
    out.append(f"IC Markets EURGBP M5 — Quantum London grid backtest")
    out.append(f"Sessions: {len(sessions)}  Range: {sds[0]} → {sds[-1]}")
    out.append(f"Recent-90 cutoff: {cutoff_90}   Recent-60 cutoff: {cutoff_60}")
    out.append(f"Combos run: {len(rows)}\n")

    # Min trades filter for ranking — avoid 1-trade combos with PF=inf
    df_meaningful = df[df["n"] >= 30].copy()

    out.append("=" * 110)
    out.append("TOP 10 by PF (full window, min 30 trades)")
    out.append("=" * 110)
    out.append(f"{'trig':>4} {'tgt':>4} {'stp':>4} {'dir':>5} {'rng':>4} {'cf':>2}  {'N':>4} {'WR':>5} {'PF':>5} {'Tot':>7} {'DD':>6}  {'PF90':>5} {'N90':>4} {'Tot90':>7}")
    out.append("-" * 110)
    top_pf = df_meaningful.sort_values("pf", ascending=False).head(10)
    for _, r in top_pf.iterrows():
        out.append(f"{r['trigger']:>4} {str(r['target']):>4} {r['stop']:>4} {r['direction']:>5} {r['range_filter']:>4} {r['confirmation']:>2}  "
                   f"{int(r['n']):>4} {r['wr']:>4.0f}% {r['pf']:>5.2f} {r['tot']:>+7.1f} {r['dd']:>5.1f}p  "
                   f"{r['pf_90']:>5.2f} {int(r['n_90']):>4} {r['tot_90']:>+7.1f}")
    out.append("")

    out.append("=" * 110)
    out.append("TOP 5 by raw total pips (full window, min 30 trades)")
    out.append("=" * 110)
    out.append(f"{'trig':>4} {'tgt':>4} {'stp':>4} {'dir':>5} {'rng':>4} {'cf':>2}  {'N':>4} {'WR':>5} {'PF':>5} {'Tot':>7} {'DD':>6}  {'PF90':>5} {'N90':>4} {'Tot90':>7}")
    out.append("-" * 110)
    top_tot = df_meaningful.sort_values("tot", ascending=False).head(5)
    for _, r in top_tot.iterrows():
        out.append(f"{r['trigger']:>4} {str(r['target']):>4} {r['stop']:>4} {r['direction']:>5} {r['range_filter']:>4} {r['confirmation']:>2}  "
                   f"{int(r['n']):>4} {r['wr']:>4.0f}% {r['pf']:>5.2f} {r['tot']:>+7.1f} {r['dd']:>5.1f}p  "
                   f"{r['pf_90']:>5.2f} {int(r['n_90']):>4} {r['tot_90']:>+7.1f}")
    out.append("")

    # PF >= 1.5 BOTH full and recent-90
    out.append("=" * 110)
    out.append("ROBUST combos: PF >= 1.5 in BOTH full window AND recent-90 days (min 30 full / 8 recent trades)")
    out.append("=" * 110)
    robust = df_meaningful[(df_meaningful["pf"] >= 1.5) & (df_meaningful["pf_90"] >= 1.5) & (df_meaningful["n_90"] >= 8)]
    if robust.empty:
        out.append("  *** NONE *** — no parameter combination produces PF >= 1.5 on both full data AND recent-90 days.")
    else:
        out.append(f"  Found {len(robust)} combo(s):")
        out.append(f"{'trig':>4} {'tgt':>4} {'stp':>4} {'dir':>5} {'rng':>4} {'cf':>2}  {'N':>4} {'WR':>5} {'PF':>5} {'Tot':>7}  {'PF90':>5} {'N90':>4} {'Tot90':>7}")
        for _, r in robust.sort_values("pf", ascending=False).iterrows():
            out.append(f"{r['trigger']:>4} {str(r['target']):>4} {r['stop']:>4} {r['direction']:>5} {r['range_filter']:>4} {r['confirmation']:>2}  "
                       f"{int(r['n']):>4} {r['wr']:>4.0f}% {r['pf']:>5.2f} {r['tot']:>+7.1f}  "
                       f"{r['pf_90']:>5.2f} {int(r['n_90']):>4} {r['tot_90']:>+7.1f}")
    out.append("")

    # Direction asymmetry: pair LONG-only vs SHORT-only vs BOTH for same other params
    out.append("=" * 110)
    out.append("DIRECTION ASYMMETRY: cases where LONG-only or SHORT-only dramatically outperforms BOTH")
    out.append("=" * 110)
    asy = []
    grouped = df.groupby(["trigger", "target", "stop", "range_filter", "confirmation"])
    for key, g in grouped:
        g = g.set_index("direction")
        if "BOTH" in g.index and "LONG" in g.index and "SHORT" in g.index:
            both_pf = g.loc["BOTH", "pf"]
            long_pf = g.loc["LONG", "pf"]
            short_pf = g.loc["SHORT", "pf"]
            both_n = g.loc["BOTH", "n"]
            long_n = g.loc["LONG", "n"]
            short_n = g.loc["SHORT", "n"]
            for side, pf, n in [("LONG", long_pf, long_n), ("SHORT", short_pf, short_n)]:
                if n >= 20 and pf >= 1.5 and pf >= both_pf * 1.5 and both_pf < 1.2:
                    asy.append({
                        "key": key, "side": side, "side_pf": pf, "side_n": n,
                        "both_pf": both_pf, "both_n": both_n,
                    })
    if not asy:
        out.append("  No striking asymmetries found (would have shown a side with PF>=1.5 and >=1.5x BOTH PF, with BOTH PF<1.2).")
    else:
        asy.sort(key=lambda x: x["side_pf"], reverse=True)
        out.append(f"  Found {len(asy)} asymmetric setup(s) (showing top 15):")
        out.append(f"{'trig':>4} {'tgt':>4} {'stp':>4} {'rng':>4} {'cf':>2}  {'side':>5} {'sidePF':>6} {'sideN':>5}  {'bothPF':>6} {'bothN':>5}")
        for a in asy[:15]:
            t, tg, st, rg, cf = a["key"]
            out.append(f"{t:>4} {str(tg):>4} {st:>4} {rg:>4} {cf:>2}  "
                       f"{a['side']:>5} {a['side_pf']:>6.2f} {int(a['side_n']):>5}  "
                       f"{a['both_pf']:>6.2f} {int(a['both_n']):>5}")
    out.append("")

    # Bonus: how does the live-config combo do?
    out.append("=" * 110)
    out.append("CURRENT LIVE CONFIG: trigger=7, target=5, stop=18, BOTH, range_filter=999, confirmation=N")
    out.append("=" * 110)
    cur = df[(df["trigger"] == 7) & (df["target"] == 5) & (df["stop"] == 18) &
             (df["direction"] == "BOTH") & (df["range_filter"] == 999) & (df["confirmation"] == "N")]
    if not cur.empty:
        r = cur.iloc[0]
        out.append(f"  N={int(r['n'])}  WR={r['wr']:.0f}%  PF={r['pf']:.2f}  Tot={r['tot']:+.1f}p  DD={r['dd']:.1f}p")
        out.append(f"  Recent-90: N={int(r['n_90'])}  PF={r['pf_90']:.2f}  Tot={r['tot_90']:+.1f}p  WR={r['wr_90']:.0f}%")
        out.append(f"  Recent-60: N={int(r['n_60'])}  PF={r['pf_60']:.2f}  Tot={r['tot_60']:+.1f}p  WR={r['wr_60']:.0f}%")

    text = "\n".join(out)
    with open(OUT_TOP, "w") as f:
        f.write(text)
    print("\n" + text)
    print(f"\nReport written to: {OUT_TOP}")


if __name__ == "__main__":
    main()
