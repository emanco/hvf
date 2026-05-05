"""Find the best pair subset for KZ_HUNT under a flat +12p TP exit policy.

Reuses simulate_flat_tp logic from run_kz_flat_tp_compare.py (SL-first within
bar, hold up to 7 days, original spread-comp SL from the trade record).

Steps:
  1. Per-pair stats under +12p flat TP (N, WR, PF, Total, MaxDD, mean MFE).
  2. Greedy drop search: start with all pairs, drop the pair whose removal
     most improves aggregate PF, stop when no further improvement or N<40.
  3. Trivial cuts: PF >= 1.0 individually, PF >= 1.2 individually.

Outputs:
  - backtests/charts/kz_pair_filter.png
  - backtests/data/kz_pair_filter_stats.csv
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
BROKER_OFFSET_HOURS = 3
HOLD_DAYS = 7
TP_PIPS = 12

TRADES_CSV = ROOT / "data/kz_trades_enriched.csv"
OUT_PNG = ROOT / "charts/kz_pair_filter.png"
OUT_CSV = ROOT / "data/kz_pair_filter_stats.csv"

MIN_N_SUBSET = 40  # stop greedy when subset trade count drops below this


def pip(symbol):
    return 0.01 if "JPY" in symbol else 0.0001


def to_utc(broker_unix):
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def load_bars(symbol):
    f = ROOT / f"data/{symbol}_M30.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["utc_t"] = df["time"].apply(to_utc)
    return df


def simulate_flat_tp(df, opened_at, direction, entry, sl, tp_pips, p, hold_days=HOLD_DAYS):
    """Returns (pnl_pips, outcome, mfe_pips). MFE = max favourable excursion in pips."""
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return None, "NO_DATA", None
    tp_price = entry + tp_pips * p if direction == "LONG" else entry - tp_pips * p
    mfe = 0.0
    for _, b in window.iterrows():
        if direction == "LONG":
            cur_mfe = (b["high"] - entry) / p
            if cur_mfe > mfe:
                mfe = cur_mfe
            if b["low"] <= sl:
                return (sl - entry) / p, "SL", mfe
            if b["high"] >= tp_price:
                return tp_pips, "TP", mfe
        else:
            cur_mfe = (entry - b["low"]) / p
            if cur_mfe > mfe:
                mfe = cur_mfe
            if b["high"] >= sl:
                return (entry - sl) / p, "SL", mfe
            if b["low"] <= tp_price:
                return tp_pips, "TP", mfe
    last = window.iloc[-1]
    pnl = ((last["close"] - entry) if direction == "LONG" else (entry - last["close"])) / p
    return pnl, "TIME", mfe


def stats(pnls):
    a = np.array(pnls, dtype=float)
    n = len(a)
    if n == 0:
        return None
    wins = (a > 0).sum()
    gp = a[a > 0].sum() if wins else 0.0
    gl = abs(a[a <= 0].sum()) if (a <= 0).sum() else 0.001
    eq = np.cumsum(a)
    dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0.0
    return {
        "n": int(n),
        "wr": wins / n * 100,
        "pf": gp / gl,
        "tot": float(a.sum()),
        "avg": float(a.sum() / n),
        "dd": float(dd),
        "eq": eq,
    }


def subset_stats(rows, keep_symbols):
    """Aggregate stats for trades whose symbol is in keep_symbols (chronological order preserved)."""
    pnls = [r["pnl"] for r in rows if r["sym"] in keep_symbols]
    return stats(pnls)


def main():
    trades = pd.read_csv(TRADES_CSV)
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)
    trades = trades.sort_values("opened_at").reset_index(drop=True)
    print(f"Loaded {len(trades)} closed KZ_HUNT trades.\n")

    bar_cache = {}
    rows = []  # chronological list of dicts: {sym, pnl, outcome, mfe, id}

    for _, t in trades.iterrows():
        sym = t["symbol"]
        if sym not in bar_cache:
            bar_cache[sym] = load_bars(sym)
        df = bar_cache[sym]
        if df is None:
            continue
        p = pip(sym)
        res, outcome, mfe = simulate_flat_tp(
            df, t["opened_at"].to_pydatetime(), t["direction"],
            t["entry_price"], t["stop_loss"], TP_PIPS, p,
        )
        if res is None:
            continue
        rows.append({
            "sym": sym,
            "pnl": float(res),
            "outcome": outcome,
            "mfe": float(mfe) if mfe is not None else 0.0,
            "id": int(t["id"]),
            "opened_at": t["opened_at"],
        })

    print(f"Simulated {len(rows)} trades (TP={TP_PIPS}p flat).\n")

    all_symbols = sorted({r["sym"] for r in rows})

    # ─── Per-pair stats ────────────────────────────────────────────────
    per_pair = {}
    for sym in all_symbols:
        sym_rows = [r for r in rows if r["sym"] == sym]
        pnls = [r["pnl"] for r in sym_rows]
        mfes = [r["mfe"] for r in sym_rows]
        s = stats(pnls)
        s["mean_mfe"] = float(np.mean(mfes)) if mfes else 0.0
        s["sym"] = sym
        per_pair[sym] = s

    print(f"{'Symbol':<8} {'N':>4} {'WR':>5} {'PF':>5} {'Total':>9} {'Avg':>7} {'MaxDD':>7} {'MFE':>6}")
    print("-" * 60)
    for sym in all_symbols:
        s = per_pair[sym]
        print(f"{sym:<8} {s['n']:>4} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
              f"{s['tot']:>+8.1f}p {s['avg']:>+6.1f}p {s['dd']:>6.1f}p {s['mean_mfe']:>5.1f}p")
    print()

    # ─── Baseline (all pairs) ──────────────────────────────────────────
    baseline = subset_stats(rows, set(all_symbols))
    print(f"BASELINE (all {len(all_symbols)} pairs): N={baseline['n']} "
          f"PF={baseline['pf']:.2f} Total={baseline['tot']:+.1f}p "
          f"WR={baseline['wr']:.0f}% DD={baseline['dd']:.1f}p\n")

    # ─── Greedy drop ───────────────────────────────────────────────────
    print("=== Greedy drop (improve aggregate PF) ===")
    keep = set(all_symbols)
    cur = baseline
    history = [("(start)", sorted(keep), cur)]
    while True:
        best_drop = None
        best_pf = cur["pf"]
        best_stat = None
        for sym in list(keep):
            cand = keep - {sym}
            if not cand:
                continue
            s = subset_stats(rows, cand)
            if s is None or s["n"] < MIN_N_SUBSET:
                continue
            if s["pf"] > best_pf + 1e-9:
                best_pf = s["pf"]
                best_drop = sym
                best_stat = s
        if best_drop is None:
            break
        keep.remove(best_drop)
        cur = best_stat
        history.append((f"drop {best_drop}", sorted(keep), cur))
        print(f"  drop {best_drop:<8} -> N={cur['n']} PF={cur['pf']:.2f} "
              f"Total={cur['tot']:+.1f}p WR={cur['wr']:.0f}% DD={cur['dd']:.1f}p")
    greedy_keep = sorted(keep)
    greedy_stat = cur
    print(f"\nGreedy result: keep {greedy_keep}")
    print(f"  N={greedy_stat['n']} PF={greedy_stat['pf']:.2f} "
          f"Total={greedy_stat['tot']:+.1f}p WR={greedy_stat['wr']:.0f}% "
          f"DD={greedy_stat['dd']:.1f}p\n")

    # ─── Trivial cuts ──────────────────────────────────────────────────
    pf10_keep = sorted([s for s, st in per_pair.items() if st["pf"] >= 1.0])
    pf12_keep = sorted([s for s, st in per_pair.items() if st["pf"] >= 1.2])
    pf10_stat = subset_stats(rows, set(pf10_keep)) if pf10_keep else None
    pf12_stat = subset_stats(rows, set(pf12_keep)) if pf12_keep else None
    print(f"PF>=1.0 keep: {pf10_keep}")
    if pf10_stat:
        print(f"  N={pf10_stat['n']} PF={pf10_stat['pf']:.2f} "
              f"Total={pf10_stat['tot']:+.1f}p WR={pf10_stat['wr']:.0f}% "
              f"DD={pf10_stat['dd']:.1f}p")
    print(f"PF>=1.2 keep: {pf12_keep}")
    if pf12_stat:
        print(f"  N={pf12_stat['n']} PF={pf12_stat['pf']:.2f} "
              f"Total={pf12_stat['tot']:+.1f}p WR={pf12_stat['wr']:.0f}% "
              f"DD={pf12_stat['dd']:.1f}p")
    print()

    # ─── Save per-pair stats CSV ───────────────────────────────────────
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_out = pd.DataFrame([
        {
            "symbol": sym,
            "n": s["n"],
            "wr": round(s["wr"], 2),
            "pf": round(s["pf"], 3),
            "total_pips": round(s["tot"], 2),
            "avg_pips": round(s["avg"], 2),
            "max_dd_pips": round(s["dd"], 2),
            "mean_mfe_pips": round(s["mean_mfe"], 2),
            "in_greedy": sym in greedy_keep,
            "in_pf10": sym in pf10_keep,
            "in_pf12": sym in pf12_keep,
        }
        for sym, s in per_pair.items()
    ])
    df_out.to_csv(OUT_CSV, index=False)
    print(f"Saved: {OUT_CSV}")

    # ─── Plot ──────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 11))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.4, 1.4, 1])

    # 1. Equity curves
    ax = fig.add_subplot(gs[0, :])
    ax.plot(baseline["eq"],
            label=f"ALL pairs (N={baseline['n']}, PF={baseline['pf']:.2f}, "
                  f"Total={baseline['tot']:+.0f}p, DD={baseline['dd']:.0f}p)",
            color="#888888", lw=1.6)
    ax.plot(greedy_stat["eq"],
            label=f"GREEDY {greedy_keep} (N={greedy_stat['n']}, "
                  f"PF={greedy_stat['pf']:.2f}, Total={greedy_stat['tot']:+.0f}p, "
                  f"DD={greedy_stat['dd']:.0f}p)",
            color="#2ca02c", lw=2.0)
    if pf10_stat:
        ax.plot(pf10_stat["eq"],
                label=f"PF>=1.0 {pf10_keep} (N={pf10_stat['n']}, "
                      f"PF={pf10_stat['pf']:.2f}, Total={pf10_stat['tot']:+.0f}p)",
                color="#1f77b4", lw=1.6, linestyle="--")
    if pf12_stat:
        ax.plot(pf12_stat["eq"],
                label=f"PF>=1.2 {pf12_keep} (N={pf12_stat['n']}, "
                      f"PF={pf12_stat['pf']:.2f}, Total={pf12_stat['tot']:+.0f}p)",
                color="#d62728", lw=1.6, linestyle=":")
    ax.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_title("KZ_HUNT pair filter — equity curves under flat +12p TP")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative pips")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)

    # 2. Per-pair PF + Total bars
    ax = fig.add_subplot(gs[1, 0])
    syms = list(per_pair.keys())
    pfs = [per_pair[s]["pf"] for s in syms]
    colors = ["#2ca02c" if s in greedy_keep else ("#1f77b4" if pf >= 1.0 else "#d62728")
              for s, pf in zip(syms, pfs)]
    ax.bar(syms, pfs, color=colors, alpha=0.85)
    ax.axhline(1.0, color="black", lw=1.0, linestyle="--", alpha=0.7, label="PF=1.0")
    ax.axhline(1.2, color="#888888", lw=0.8, linestyle=":", alpha=0.7, label="PF=1.2")
    for i, (s, pf) in enumerate(zip(syms, pfs)):
        ax.text(i, pf + 0.02, f"{pf:.2f}", ha="center", fontsize=8)
    ax.set_title("Per-pair Profit Factor (green=greedy keep, blue=PF≥1.0, red=PF<1.0)")
    ax.set_ylabel("PF")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30)

    # 3. Per-pair total pips
    ax = fig.add_subplot(gs[1, 1])
    tots = [per_pair[s]["tot"] for s in syms]
    colors_t = ["#2ca02c" if t > 0 else "#d62728" for t in tots]
    ax.bar(syms, tots, color=colors_t, alpha=0.85)
    ax.axhline(0, color="black", lw=0.5)
    for i, (s, t) in enumerate(zip(syms, tots)):
        ax.text(i, t + (3 if t >= 0 else -6), f"{t:+.0f}p",
                ha="center", fontsize=8)
    ax.set_title("Per-pair total pips (flat +12p TP)")
    ax.set_ylabel("Pips")
    ax.grid(alpha=0.3, axis="y")
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30)

    # 4. Per-pair trade count
    ax = fig.add_subplot(gs[2, 0])
    ns = [per_pair[s]["n"] for s in syms]
    colors_n = ["#2ca02c" if n >= 15 else ("#ff7f0e" if n >= 8 else "#d62728")
                for n in ns]
    ax.bar(syms, ns, color=colors_n, alpha=0.85)
    for i, (s, n) in enumerate(zip(syms, ns)):
        ax.text(i, n + 0.3, f"{n}", ha="center", fontsize=9)
    ax.set_title("Per-pair trade count (red=<8 low confidence)")
    ax.set_ylabel("# trades")
    ax.grid(alpha=0.3, axis="y")
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30)

    # 5. Summary table panel
    ax = fig.add_subplot(gs[2, 1])
    ax.axis("off")
    summary_lines = [
        f"BASELINE  N={baseline['n']:>3}  PF={baseline['pf']:.2f}  "
        f"Tot={baseline['tot']:+.0f}p  DD={baseline['dd']:.0f}p",
        f"GREEDY    N={greedy_stat['n']:>3}  PF={greedy_stat['pf']:.2f}  "
        f"Tot={greedy_stat['tot']:+.0f}p  DD={greedy_stat['dd']:.0f}p",
    ]
    if pf10_stat:
        summary_lines.append(
            f"PF>=1.0   N={pf10_stat['n']:>3}  PF={pf10_stat['pf']:.2f}  "
            f"Tot={pf10_stat['tot']:+.0f}p  DD={pf10_stat['dd']:.0f}p"
        )
    if pf12_stat:
        summary_lines.append(
            f"PF>=1.2   N={pf12_stat['n']:>3}  PF={pf12_stat['pf']:.2f}  "
            f"Tot={pf12_stat['tot']:+.0f}p  DD={pf12_stat['dd']:.0f}p"
        )
    summary_lines.append("")
    summary_lines.append(f"GREEDY keep: {', '.join(greedy_keep)}")
    summary_lines.append(f"PF>=1.0 keep: {', '.join(pf10_keep) if pf10_keep else '-'}")
    summary_lines.append(f"PF>=1.2 keep: {', '.join(pf12_keep) if pf12_keep else '-'}")

    ax.text(0.02, 0.98, "\n".join(summary_lines),
            ha="left", va="top", family="monospace", fontsize=10,
            transform=ax.transAxes)
    ax.set_title("Subset comparison")

    plt.suptitle(
        f"KZ_HUNT pair-subset analysis — flat +12p TP, "
        f"{len(rows)} live trades (since 2026-03-25)",
        fontsize=13, y=0.995,
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"Saved: {OUT_PNG}")


if __name__ == "__main__":
    main()
