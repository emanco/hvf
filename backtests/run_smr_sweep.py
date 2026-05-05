"""SMR parameter sweep — EURGBP M5 over 8 months.

Sweeps trigger/target around the 40/10/40 baseline to check whether the
chosen params sit on a robust plateau or a lucky spike.

Three views:
  1. Trigger × Target heatmap (stop = trigger, FF-canonical asymmetric)
  2. Trigger × Stop heatmap  (target = 10, fixed)
  3. PF curve across trigger for several R:R configs
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

CSV_PATH = Path(__file__).parent / "data/EURGBP_M5.csv"
OUT_PATH = Path(__file__).parent / "charts/smr_sweep.png"


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


def simulate(sessions, trigger, target, stop):
    trades = []
    for sd in sorted(sessions):
        s = sessions[sd]
        if s["open"] is None or s["wd"] in [4, 5]:
            continue
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
                elif b["hi"] >= so + trigger * PIP:
                    ep = so + trigger * PIP
                    ot = ("S", ep, ep - target * PIP, ep + stop * PIP, i)
            else:
                d_dir, ep, tp, sl_p, entry_idx = ot
                if i <= entry_idx:
                    continue
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append((sl_p - ep) / PIP - SPREAD); done = True
                    elif b["hi"] >= tp:
                        trades.append((tp - ep) / PIP - SPREAD); done = True
                else:
                    if b["hi"] >= sl_p:
                        trades.append((ep - sl_p) / PIP - SPREAD); done = True
                    elif b["lo"] <= tp:
                        trades.append((ep - tp) / PIP - SPREAD); done = True
        if ot and not done:
            d_dir, ep, *_ = ot
            last = trading[-1]
            pnl = (last["cl"] - ep) / PIP - SPREAD if d_dir == "L" else (ep - last["cl"]) / PIP - SPREAD
            trades.append(pnl)
    return trades


def stats(trades):
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "tot": 0, "dd": 0}
    pnls = np.array(trades)
    wins = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = (np.maximum.accumulate(eq) - eq).max() if len(eq) > 1 else 0
    return {"n": len(pnls), "wr": wins / len(pnls) * 100,
            "pf": gp / gl, "tot": pnls.sum(), "dd": dd}


def main():
    df = pd.read_csv(CSV_PATH)
    sessions = build_sessions(df.to_dict("records"))

    triggers = [25, 30, 35, 40, 45, 50]
    targets = [5, 7.5, 10, 12.5, 15, 20]
    stops = [25, 30, 35, 40, 45, 50]

    # Grid 1: trigger × target, stop = trigger (FF asymmetric default)
    pf_grid_tt = np.zeros((len(triggers), len(targets)))
    tot_grid_tt = np.zeros((len(triggers), len(targets)))
    n_grid_tt = np.zeros((len(triggers), len(targets)), dtype=int)
    for i, trig in enumerate(triggers):
        for j, tgt in enumerate(targets):
            r = stats(simulate(sessions, trig, tgt, trig))
            pf_grid_tt[i, j] = r["pf"]
            tot_grid_tt[i, j] = r["tot"]
            n_grid_tt[i, j] = r["n"]

    # Grid 2: trigger × stop, target = 10 (stop sensitivity)
    pf_grid_ts = np.zeros((len(triggers), len(stops)))
    tot_grid_ts = np.zeros((len(triggers), len(stops)))
    for i, trig in enumerate(triggers):
        for j, stp in enumerate(stops):
            r = stats(simulate(sessions, trig, 10, stp))
            pf_grid_ts[i, j] = r["pf"]
            tot_grid_ts[i, j] = r["tot"]

    # Print top 10 configs by PF (with N >= 15 to filter noise)
    print("\nTop 10 configs by PF (trigger × target, stop=trigger, N>=15)")
    print("-" * 70)
    rows = []
    for i, trig in enumerate(triggers):
        for j, tgt in enumerate(targets):
            r = stats(simulate(sessions, trig, tgt, trig))
            if r["n"] >= 15:
                rows.append((trig, tgt, r))
    rows.sort(key=lambda x: -x[2]["pf"])
    print(f"{'Trig':>5} {'Tgt':>5} {'Stop':>5} {'N':>4} {'WR':>5} {'PF':>6} {'Tot':>8} {'DD':>5}")
    for trig, tgt, r in rows[:10]:
        print(f"{trig:>5} {tgt:>5} {trig:>5} {r['n']:>4} {r['wr']:>4.0f}% {r['pf']:>6.2f} "
              f"{r['tot']:>+7.1f}p {r['dd']:>4.0f}p")

    # Find baseline 40/10/40
    base_i = triggers.index(40)
    base_j = targets.index(10)
    base_pf = pf_grid_tt[base_i, base_j]
    base_tot = tot_grid_tt[base_i, base_j]
    base_n = n_grid_tt[base_i, base_j]
    print(f"\nBaseline 40/10/40: N={base_n} PF={base_pf:.2f} Tot={base_tot:+.1f}p")

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    # Heatmap 1: trigger × target (stop=trigger)
    ax = axes[0]
    im = ax.imshow(pf_grid_tt, cmap="RdYlGn", aspect="auto",
                   vmin=0.5, vmax=2.5, origin="lower")
    ax.set_xticks(range(len(targets))); ax.set_xticklabels(targets)
    ax.set_yticks(range(len(triggers))); ax.set_yticklabels(triggers)
    ax.set_xlabel("Target pips")
    ax.set_ylabel("Trigger pips (= Stop pips)")
    ax.set_title(f"PF — Trigger × Target (stop=trigger)\nEURGBP M5, 8 months, baseline 40/10/40 PF={base_pf:.2f}")
    for i in range(len(triggers)):
        for j in range(len(targets)):
            ax.text(j, i, f"{pf_grid_tt[i,j]:.2f}\nn={n_grid_tt[i,j]}",
                    ha="center", va="center", fontsize=8,
                    color="white" if pf_grid_tt[i,j] < 1.0 or pf_grid_tt[i,j] > 2.0 else "black")
    # Mark baseline
    ax.add_patch(plt.Rectangle((base_j-0.5, base_i-0.5), 1, 1,
                               fill=False, edgecolor="blue", lw=3))
    plt.colorbar(im, ax=ax, label="Profit Factor")

    # Heatmap 2: trigger × stop (target=10)
    ax = axes[1]
    im = ax.imshow(pf_grid_ts, cmap="RdYlGn", aspect="auto",
                   vmin=0.5, vmax=2.5, origin="lower")
    ax.set_xticks(range(len(stops))); ax.set_xticklabels(stops)
    ax.set_yticks(range(len(triggers))); ax.set_yticklabels(triggers)
    ax.set_xlabel("Stop pips")
    ax.set_ylabel("Trigger pips")
    ax.set_title("PF — Trigger × Stop (target=10)\nEURGBP M5, 8 months")
    for i in range(len(triggers)):
        for j in range(len(stops)):
            ax.text(j, i, f"{pf_grid_ts[i,j]:.2f}",
                    ha="center", va="center", fontsize=8,
                    color="white" if pf_grid_ts[i,j] < 1.0 or pf_grid_ts[i,j] > 2.0 else "black")
    # Mark baseline (40 trig, 40 stop)
    base_i2 = triggers.index(40)
    base_j2 = stops.index(40)
    ax.add_patch(plt.Rectangle((base_j2-0.5, base_i2-0.5), 1, 1,
                               fill=False, edgecolor="blue", lw=3))
    plt.colorbar(im, ax=ax, label="Profit Factor")

    plt.tight_layout()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PATH, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
