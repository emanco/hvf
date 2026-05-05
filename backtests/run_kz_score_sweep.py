"""Score-threshold sweep for KZ_HUNT trades under a flat +12p TP exit policy.

Re-uses the same simulator convention as run_kz_flat_tp_compare.py:
  - SL-first within bar
  - hold up to 7 days from open
  - +12p flat TP
  - original spread-comp SL from trade record
  - broker-time M30 bars (UTC+3 -> UTC)

For each threshold in [50, 55, 60, 65, 70, 75, 80, 85, 90] we filter
trades by score >= thr, simulate +12p flat TP, and report
N / WR / PF / total pips / MaxDD / MAR.

Outputs:
  - console summary table
  - backtests/charts/kz_score_sweep.png
  - backtests/data/kz_score_sweep_detail.csv (per-trade per-threshold)
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
OUT_PNG = ROOT / "charts/kz_score_sweep.png"
OUT_DETAIL = ROOT / "data/kz_score_sweep_detail.csv"

THRESHOLDS = [50, 55, 60, 65, 70, 75, 80, 85, 90]


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
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return None, "NO_DATA"
    tp_price = entry + tp_pips * p if direction == "LONG" else entry - tp_pips * p
    for _, b in window.iterrows():
        if direction == "LONG":
            if b["low"] <= sl:
                return (sl - entry) / p, "SL"
            if b["high"] >= tp_price:
                return tp_pips, "TP"
        else:
            if b["high"] >= sl:
                return (entry - sl) / p, "SL"
            if b["low"] <= tp_price:
                return tp_pips, "TP"
    last = window.iloc[-1]
    pnl = ((last["close"] - entry) if direction == "LONG" else (entry - last["close"])) / p
    return pnl, "TIME"


def stats(pnls):
    a = np.array(pnls, dtype=float)
    n = len(a)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": 0, "tot": 0, "avg": 0, "dd": 0, "mar": 0, "eq": np.array([])}
    wins = (a > 0).sum()
    gp = a[a > 0].sum() if wins else 0
    losses_sum = abs(a[a <= 0].sum())
    pf = gp / losses_sum if losses_sum > 0 else float("inf")
    eq = np.cumsum(a)
    dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0
    tot = a.sum()
    mar = (tot / dd) if dd > 0 else (float("inf") if tot > 0 else 0)
    return {
        "n": n,
        "wr": wins / n * 100,
        "pf": pf,
        "tot": tot,
        "avg": tot / n,
        "dd": dd,
        "mar": mar,
        "eq": eq,
    }


def main():
    trades = pd.read_csv(TRADES_CSV)
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)
    print(f"Loaded {len(trades)} closed KZ_HUNT trades.\n")

    # Simulate every trade once, then filter by threshold afterward.
    bar_cache = {}
    sim_rows = []  # one per simulated trade
    skipped = 0

    for _, t in trades.iterrows():
        sym = t["symbol"]
        if sym not in bar_cache:
            bar_cache[sym] = load_bars(sym)
        df = bar_cache[sym]
        if df is None:
            skipped += 1
            continue
        p = pip(sym)
        res, outcome = simulate_flat_tp(
            df, t["opened_at"].to_pydatetime(), t["direction"],
            t["entry_price"], t["stop_loss"], TP_PIPS, p,
        )
        if res is None:
            skipped += 1
            continue
        sim_rows.append({
            "id": int(t["id"]),
            "symbol": sym,
            "direction": t["direction"],
            "score": float(t["score"]),
            "opened_at": t["opened_at"],
            "pnl_pips_flat12": res,
            "outcome_flat12": outcome,
            "actual_pnl_pips": float(t["pnl_pips"]) if pd.notna(t["pnl_pips"]) else 0.0,
        })

    sim_df = pd.DataFrame(sim_rows).sort_values("opened_at").reset_index(drop=True)
    print(f"Simulated {len(sim_df)} trades ({skipped} skipped: missing bars / no data).\n")

    # ─── Sweep ─────────────────────────────────────────────────────────
    summary = []
    eq_curves = {}
    for thr in THRESHOLDS:
        f = sim_df[sim_df["score"] >= thr]
        s = stats(f["pnl_pips_flat12"].tolist())
        summary.append({
            "threshold": thr,
            "n": s["n"],
            "wr_pct": round(s["wr"], 1),
            "pf": round(s["pf"], 2) if np.isfinite(s["pf"]) else float("inf"),
            "total_pips": round(s["tot"], 1),
            "avg_pips": round(s["avg"], 2),
            "max_dd_pips": round(s["dd"], 1),
            "mar": round(s["mar"], 2) if np.isfinite(s["mar"]) else float("inf"),
        })
        eq_curves[thr] = (f["pnl_pips_flat12"].values.cumsum() if s["n"] else np.array([]))

    summary_df = pd.DataFrame(summary)

    # Print summary
    print("KZ_HUNT score-threshold sweep — flat TP @ +12p\n")
    print(f"{'Thr':>4} {'N':>4} {'WR':>6} {'PF':>6} {'Total':>9} {'Avg':>7} {'MaxDD':>7} {'MAR':>6}")
    print("-" * 60)
    for row in summary:
        pf_str = f"{row['pf']:>5.2f}" if np.isfinite(row['pf']) else "  inf"
        mar_str = f"{row['mar']:>5.2f}" if np.isfinite(row['mar']) else "  inf"
        print(
            f"{row['threshold']:>4} {row['n']:>4} "
            f"{row['wr_pct']:>5.1f}% {pf_str} "
            f"{row['total_pips']:>+8.1f}p "
            f"{row['avg_pips']:>+6.2f}p "
            f"{row['max_dd_pips']:>6.1f}p "
            f"{mar_str}"
        )

    # ─── Save per-trade detail (one row per trade per threshold) ──────
    detail_rows = []
    for thr in THRESHOLDS:
        f = sim_df[sim_df["score"] >= thr].copy()
        f["threshold"] = thr
        f["cum_pips"] = f["pnl_pips_flat12"].cumsum()
        detail_rows.append(f)
    detail_df = pd.concat(detail_rows, ignore_index=True)
    OUT_DETAIL.parent.mkdir(parents=True, exist_ok=True)
    detail_df.to_csv(OUT_DETAIL, index=False)
    print(f"\nSaved per-trade detail: {OUT_DETAIL}")

    # ─── Plot ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 11))
    gs = fig.add_gridspec(3, 2, height_ratios=[2.3, 1, 1])

    # 1. Equity curves per threshold (top, full width)
    ax = fig.add_subplot(gs[0, :])
    cmap = plt.cm.viridis(np.linspace(0, 0.95, len(THRESHOLDS)))
    for c, thr in zip(cmap, THRESHOLDS):
        eq = eq_curves[thr]
        if len(eq) == 0:
            continue
        s = next(r for r in summary if r["threshold"] == thr)
        pf_str = f"{s['pf']:.2f}" if np.isfinite(s['pf']) else "inf"
        ax.plot(
            np.arange(1, len(eq) + 1),
            eq,
            color=c,
            lw=1.8,
            label=(
                f"thr>={thr}  N={s['n']:>3}  "
                f"PF={pf_str:>4}  WR={s['wr_pct']:>4.1f}%  "
                f"Tot={s['total_pips']:>+6.0f}p  DD={s['max_dd_pips']:>4.0f}p"
            ),
        )
    ax.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_title(
        f"KZ_HUNT score-threshold sweep — equity curves under flat TP +{TP_PIPS}p exit\n"
        f"({len(sim_df)} simulated trades, M30 IC Markets bars, 7d hold)"
    )
    ax.set_ylabel("Cumulative pips")
    ax.set_xlabel("Trade # (chronological, after filtering)")
    ax.legend(loc="upper left", fontsize=9, ncol=1, framealpha=0.9)
    ax.grid(alpha=0.3)

    # 2. PF + total pips bars
    ax = fig.add_subplot(gs[1, 0])
    thr_arr = np.array([r["threshold"] for r in summary])
    pf_arr = np.array([r["pf"] if np.isfinite(r["pf"]) else 0 for r in summary])
    tot_arr = np.array([r["total_pips"] for r in summary])

    ax2 = ax.twinx()
    bars = ax.bar(thr_arr - 1, pf_arr, width=2, color="#2ca02c", alpha=0.75, label="PF")
    ax.axhline(1.0, color="black", ls="--", lw=0.7, alpha=0.5)
    ax.set_ylabel("Profit Factor", color="#2ca02c")
    ax.tick_params(axis="y", labelcolor="#2ca02c")
    ax.set_xlabel("Score threshold")
    ax.set_title("PF (green bars) and Total pips (blue line) per threshold")

    ax2.plot(thr_arr, tot_arr, color="#1f77b4", marker="o", lw=2, label="Total pips")
    ax2.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax2.set_ylabel("Total pips", color="#1f77b4")
    ax2.tick_params(axis="y", labelcolor="#1f77b4")

    ax.set_xticks(thr_arr)
    ax.grid(alpha=0.25, axis="y")

    # 3. Trade count vs threshold
    ax = fig.add_subplot(gs[1, 1])
    n_arr = np.array([r["n"] for r in summary])
    bars = ax.bar(thr_arr, n_arr, width=3.5, color="#ff7f0e", alpha=0.85)
    ax.axhline(40, color="red", ls="--", lw=1, label="N=40 (min sig.)")
    ax.set_xlabel("Score threshold")
    ax.set_ylabel("Trade count")
    ax.set_title("Trade count vs score threshold")
    for b, n in zip(bars, n_arr):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1, str(n),
                ha="center", va="bottom", fontsize=9)
    ax.set_xticks(thr_arr)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25, axis="y")

    # 4. MaxDD per threshold
    ax = fig.add_subplot(gs[2, 0])
    dd_arr = np.array([r["max_dd_pips"] for r in summary])
    ax.bar(thr_arr, dd_arr, width=3.5, color="#d62728", alpha=0.8)
    ax.set_xlabel("Score threshold")
    ax.set_ylabel("MaxDD (pips)")
    ax.set_title("MaxDD per threshold (lower = smoother)")
    ax.set_xticks(thr_arr)
    ax.grid(alpha=0.25, axis="y")

    # 5. MAR (return / DD)
    ax = fig.add_subplot(gs[2, 1])
    mar_arr = np.array([
        r["mar"] if np.isfinite(r["mar"]) else (max(tot_arr) * 1.2 if r["mar"] == float("inf") else 0)
        for r in summary
    ])
    colors = ["#2ca02c" if m > 0 else "#d62728" for m in mar_arr]
    ax.bar(thr_arr, mar_arr, width=3.5, color=colors, alpha=0.85)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xlabel("Score threshold")
    ax.set_ylabel("MAR = Total / MaxDD")
    ax.set_title("MAR ratio per threshold (higher = better risk-adjusted)")
    ax.set_xticks(thr_arr)
    ax.grid(alpha=0.25, axis="y")

    plt.suptitle(
        f"KZ_HUNT entry-score threshold optimization — flat TP +{TP_PIPS}p",
        fontsize=14, y=0.995,
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"Saved chart: {OUT_PNG}")

    # ─── Recommendation logic ─────────────────────────────────────────
    # We want: N >= 40 (statistical significance), PF as high as possible,
    # MAR as high as possible, smoother curve (lower DD relative to total).
    eligible = [r for r in summary if r["n"] >= 40]
    print("\nEligible thresholds (N>=40):")
    for r in eligible:
        pf_str = f"{r['pf']:.2f}" if np.isfinite(r['pf']) else "inf"
        mar_str = f"{r['mar']:.2f}" if np.isfinite(r['mar']) else "inf"
        print(
            f"  thr>={r['threshold']}: N={r['n']}, PF={pf_str}, "
            f"Total={r['total_pips']:+.1f}p, DD={r['max_dd_pips']:.1f}p, "
            f"MAR={mar_str}"
        )


if __name__ == "__main__":
    main()
