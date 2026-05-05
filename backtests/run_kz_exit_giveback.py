"""KZ_HUNT exit giveback analysis.

For each closed KZ_HUNT trade, computes counterfactuals:
- ACTUAL: what the bot's complex exit logic produced
- HOLD_T1_FIXED: simple exit, TP=target_1, SL=stop_loss, no partial/trail
- HOLD_T2_FIXED: simple exit, TP=target_2, SL=stop_loss, no partial/trail
- MFE: peak unrealized profit during the trade window (run-it-to-the-top)

Walk forward from opened_at over M30 bars. For each bar check (in this
order, conservative SL-first):
  LONG : low <= SL → SL hit, lose stop_pips
         high >= TP → TP hit, gain target_pips
  SHORT: high >= SL → SL hit
         low <= TP → TP hit

If neither hits within 7 days of open, mark as TIME (use last bar close).

Output: console stats + chart of giveback distribution.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import csv

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
BROKER_OFFSET_HOURS = 3
HOLD_DAYS = 7
TRADES_CSV = ROOT / "data/kz_trades.csv"
OUT_PNG = ROOT / "charts/kz_exit_giveback.png"
OUT_CSV = ROOT / "data/kz_giveback_per_trade.csv"


def pip(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def to_utc(broker_unix: int) -> datetime:
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def load_bars(symbol: str):
    f = ROOT / f"data/{symbol}_M30.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["utc_t"] = df["time"].apply(to_utc)
    return df


def simulate_fixed(df: pd.DataFrame, opened_at: datetime, direction: str,
                   entry: float, tp: float, sl: float, hold_days=HOLD_DAYS):
    """Walk forward bars; return (outcome, exit_price, hit_at) — SL-first.

    outcome: 'TP', 'SL', or 'TIME'.
    """
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return ("NO_DATA", entry, None)

    for _, b in window.iterrows():
        lo, hi = b["low"], b["high"]
        if direction == "LONG":
            if lo <= sl:
                return ("SL", sl, b["utc_t"])
            if hi >= tp:
                return ("TP", tp, b["utc_t"])
        else:  # SHORT
            if hi >= sl:
                return ("SL", sl, b["utc_t"])
            if lo <= tp:
                return ("TP", tp, b["utc_t"])

    last = window.iloc[-1]
    return ("TIME", last["close"], last["utc_t"])


def compute_mfe(df: pd.DataFrame, opened_at: datetime, direction: str,
                entry: float, sl: float, hold_days=HOLD_DAYS):
    """Peak favorable excursion in pips (or until SL would have hit if no exit)."""
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return 0.0
    mfe = 0.0
    for _, b in window.iterrows():
        if direction == "LONG":
            if b["low"] <= sl:
                break  # SL hit, stop tracking
            mfe = max(mfe, b["high"] - entry)
        else:
            if b["high"] >= sl:
                break
            mfe = max(mfe, entry - b["low"])
    return mfe


def pnl_from_outcome(direction, entry, exit_price, sym):
    p = pip(sym)
    return ((exit_price - entry) if direction == "LONG" else (entry - exit_price)) / p


def main():
    trades = pd.read_csv(TRADES_CSV)
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)
    print(f"Loaded {len(trades)} closed KZ_HUNT trades.\n")

    bar_cache: dict[str, pd.DataFrame] = {}
    rows = []
    skipped = 0
    for _, t in trades.iterrows():
        sym = t["symbol"]
        if sym not in bar_cache:
            bar_cache[sym] = load_bars(sym)
        df = bar_cache[sym]
        if df is None:
            skipped += 1
            continue

        direction = t["direction"]
        entry = t["entry_price"]
        t1 = t["target_1"]
        t2 = t["target_2"]
        sl = t["stop_loss"]
        opened_at = t["opened_at"].to_pydatetime()
        actual_pips = t["pnl_pips"] if pd.notna(t["pnl_pips"]) else 0.0
        p = pip(sym)

        # Counterfactuals
        out_t1, exit_t1, _ = simulate_fixed(df, opened_at, direction, entry, t1, sl)
        out_t2, exit_t2, _ = simulate_fixed(df, opened_at, direction, entry, t2, sl)
        if out_t1 == "NO_DATA":
            skipped += 1
            continue
        pips_t1 = pnl_from_outcome(direction, entry, exit_t1, sym)
        pips_t2 = pnl_from_outcome(direction, entry, exit_t2, sym)

        # MFE: run to peak (no exit logic at all)
        mfe_pips = compute_mfe(df, opened_at, direction, entry, sl) / p

        # Giveback = T1 counterfactual minus actual (positive = bot lost pips on exit)
        giveback_t1 = pips_t1 - actual_pips
        giveback_t2 = pips_t2 - actual_pips
        rows.append({
            "id": int(t["id"]),
            "symbol": sym,
            "direction": direction,
            "close_reason": t["close_reason"],
            "partial_closed": int(t["partial_closed"]) if pd.notna(t["partial_closed"]) else 0,
            "actual_pips": round(actual_pips, 1),
            "t1_pips": round(pips_t1, 1),
            "t1_outcome": out_t1,
            "t2_pips": round(pips_t2, 1),
            "t2_outcome": out_t2,
            "mfe_pips": round(mfe_pips, 1),
            "giveback_t1": round(giveback_t1, 1),
            "giveback_t2": round(giveback_t2, 1),
        })

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT_CSV, index=False)
    print(f"Analyzed {len(df_out)} trades, skipped {skipped} (no bar coverage).\n")

    actual_total = df_out["actual_pips"].sum()
    t1_total = df_out["t1_pips"].sum()
    t2_total = df_out["t2_pips"].sum()
    mfe_total = df_out["mfe_pips"].sum()
    n = len(df_out)

    def stats(pnls):
        a = np.array(pnls)
        wins = (a > 0).sum()
        losses = (a <= 0).sum()
        gp = a[a > 0].sum() if wins else 0.0
        gl = abs(a[a <= 0].sum()) if losses else 0.001
        return wins, losses, gp, gl

    w_a, l_a, gp_a, gl_a = stats(df_out["actual_pips"])
    w_1, l_1, gp_1, gl_1 = stats(df_out["t1_pips"])
    w_2, l_2, gp_2, gl_2 = stats(df_out["t2_pips"])

    print(f"{'Strategy':<22} {'Total':>9} {'Avg':>7} {'WR':>5} {'PF':>5}")
    print("-" * 60)
    print(f"{'ACTUAL (live)':<22} {actual_total:>+8.1f}p {actual_total/n:>+6.1f}p "
          f"{w_a/n*100:>4.0f}% {gp_a/gl_a:>5.2f}")
    print(f"{'HOLD_T1_FIXED':<22} {t1_total:>+8.1f}p {t1_total/n:>+6.1f}p "
          f"{w_1/n*100:>4.0f}% {gp_1/gl_1:>5.2f}")
    print(f"{'HOLD_T2_FIXED':<22} {t2_total:>+8.1f}p {t2_total/n:>+6.1f}p "
          f"{w_2/n*100:>4.0f}% {gp_2/gl_2:>5.2f}")
    print(f"{'MFE (peak)':<22} {mfe_total:>+8.1f}p {mfe_total/n:>+6.1f}p")

    # Outcome breakdown for counterfactuals
    print("\nCounterfactual outcomes:")
    print(f"  HOLD_T1: {(df_out['t1_outcome']=='TP').sum()} TP, "
          f"{(df_out['t1_outcome']=='SL').sum()} SL, "
          f"{(df_out['t1_outcome']=='TIME').sum()} TIME")
    print(f"  HOLD_T2: {(df_out['t2_outcome']=='TP').sum()} TP, "
          f"{(df_out['t2_outcome']=='SL').sum()} SL, "
          f"{(df_out['t2_outcome']=='TIME').sum()} TIME")

    # Per-close-reason giveback
    print("\nGiveback by actual close_reason (T1 counterfactual − actual):")
    grp = df_out.groupby("close_reason").agg(
        n=("id", "count"),
        actual_avg=("actual_pips", "mean"),
        t1_avg=("t1_pips", "mean"),
        gb_avg=("giveback_t1", "mean"),
        gb_total=("giveback_t1", "sum"),
    ).sort_values("gb_total", ascending=False)
    print(grp.to_string(float_format=lambda x: f"{x:+.1f}"))

    # ─── Chart ─────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Equity curves
    ax = axes[0, 0]
    ax.plot(np.cumsum(df_out["actual_pips"]), label="Actual (live)", lw=1.6)
    ax.plot(np.cumsum(df_out["t1_pips"]), label="Hold to T1 fixed", lw=1.6)
    ax.plot(np.cumsum(df_out["t2_pips"]), label="Hold to T2 fixed", lw=1.6)
    ax.plot(np.cumsum(df_out["mfe_pips"]), label="MFE (theoretical max)",
            lw=1.0, alpha=0.5, linestyle=":")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title(f"KZ_HUNT cumulative pips by exit policy (N={n})")
    ax.set_ylabel("Cumulative pips")
    ax.set_xlabel("Trade #")
    ax.legend()
    ax.grid(alpha=0.3)

    # 2. Giveback histogram (T1 counterfactual)
    ax = axes[0, 1]
    ax.hist(df_out["giveback_t1"], bins=30, color="#1f77b4", alpha=0.8,
            edgecolor="black")
    ax.axvline(0, color="black", lw=1)
    ax.axvline(df_out["giveback_t1"].mean(), color="red", lw=1.5,
               label=f"Mean = {df_out['giveback_t1'].mean():+.1f}p")
    ax.set_title("Giveback per trade (HOLD_T1 − ACTUAL)\nPositive = bot's exit logic gave back pips")
    ax.set_xlabel("Pips")
    ax.set_ylabel("# trades")
    ax.legend()
    ax.grid(alpha=0.3)

    # 3. Per-symbol comparison
    ax = axes[1, 0]
    by_sym = df_out.groupby("symbol").agg(
        actual=("actual_pips", "sum"),
        t1=("t1_pips", "sum"),
        t2=("t2_pips", "sum"),
    )
    x = np.arange(len(by_sym))
    width = 0.27
    ax.bar(x - width, by_sym["actual"], width, label="Actual", color="#1f77b4")
    ax.bar(x,         by_sym["t1"],     width, label="Hold T1", color="#2ca02c")
    ax.bar(x + width, by_sym["t2"],     width, label="Hold T2", color="#ff7f0e")
    ax.set_xticks(x)
    ax.set_xticklabels(by_sym.index, rotation=30)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Total pips by symbol")
    ax.set_ylabel("Pips")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")

    # 4. Giveback by close_reason
    ax = axes[1, 1]
    rsn = df_out.groupby("close_reason").agg(
        gb=("giveback_t1", "sum"),
        n=("id", "count"),
    ).sort_values("gb", ascending=True)
    colors = ["#d62728" if v > 0 else "#2ca02c" for v in rsn["gb"]]
    ax.barh(rsn.index, rsn["gb"], color=colors, edgecolor="black")
    for i, (idx, row) in enumerate(rsn.iterrows()):
        ax.text(row["gb"] + (1 if row["gb"] >= 0 else -1), i,
                f"n={row['n']}", va="center",
                ha="left" if row["gb"] >= 0 else "right", fontsize=9)
    ax.axvline(0, color="black", lw=0.5)
    ax.set_title("Giveback by close_reason (HOLD_T1 − ACTUAL, total pips)")
    ax.set_xlabel("Pips")
    ax.grid(alpha=0.3, axis="x")

    plt.suptitle(
        f"KZ_HUNT exit-logic giveback analysis — {n} closed trades since 2026-03-25\n"
        f"Actual {actual_total:+.1f}p   |   HOLD_T1 {t1_total:+.1f}p   |   "
        f"HOLD_T2 {t2_total:+.1f}p   |   MFE peak {mfe_total:+.1f}p",
        fontsize=12,
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {OUT_PNG}")
    print(f"Per-trade detail: {OUT_CSV}")


if __name__ == "__main__":
    main()
