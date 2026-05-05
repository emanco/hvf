"""KZ_HUNT MFE-capture analysis: where does the giveback happen, and what
realistic exit policies would have captured more of it?

Tests several trail/lock policies against the actual close_reason data.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
BROKER_OFFSET_HOURS = 3
HOLD_DAYS = 7
TRADES_CSV = ROOT / "data/kz_trades.csv"
OUT_PNG = ROOT / "charts/kz_mfe_capture.png"


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


def trace_trade(df: pd.DataFrame, opened_at: datetime, direction: str,
                entry: float, sl: float, tp_t1: float, tp_t2: float,
                hold_days=HOLD_DAYS):
    """Walk forward bars from entry. Returns list of (utc_t, hi_pips, lo_pips, close_pips)
    in pips relative to entry. Stops at SL hit or end of hold window."""
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return [], "NO_DATA"
    p = pip("JPY" if False else "")  # placeholder, not used here
    out = []
    for _, b in window.iterrows():
        if direction == "LONG":
            hi_p = b["high"] - entry
            lo_p = b["low"] - entry
            cl_p = b["close"] - entry
        else:
            hi_p = entry - b["low"]
            lo_p = entry - b["high"]
            cl_p = entry - b["close"]
        out.append((b["utc_t"], hi_p, lo_p, cl_p))
        # If SL hit in this bar, stop
        if direction == "LONG" and b["low"] <= sl:
            return out, "SL"
        if direction == "SHORT" and b["high"] >= sl:
            return out, "SL"
    return out, "NO_HIT"


def policy_lock_at_mfe(trace, p, t1_pips, t2_pips, sl_pips,
                       lock_threshold_pips, lock_fraction):
    """Lock a fraction of position at first bar with high >= lock_threshold.
    Remaining keeps original SL/T2.
    Returns total pips (weighted)."""
    locked = False
    locked_pips = 0.0
    for utc_t, hi_pip_raw, lo_pip_raw, cl_pip_raw in trace:
        hi_p = hi_pip_raw / p
        lo_p = lo_pip_raw / p
        if not locked and hi_p >= lock_threshold_pips:
            locked = True
            locked_pips = lock_fraction * lock_threshold_pips
            # remaining (1-fraction) continues, with SL still at original
        if locked:
            # Check SL or T2 on remaining
            if lo_p <= -sl_pips:
                return locked_pips + (1 - lock_fraction) * (-sl_pips)
            if hi_p >= t2_pips:
                return locked_pips + (1 - lock_fraction) * t2_pips
        else:
            if lo_p <= -sl_pips:
                return -sl_pips  # full position SL'd
            if hi_p >= t2_pips:
                return t2_pips  # full position T2 hit
    # No exit — last close as approximation
    last_close = trace[-1][3] / p if trace else 0
    if locked:
        return locked_pips + (1 - lock_fraction) * last_close
    return last_close


def policy_chandelier_trail(trace, p, sl_pips, atr_mult_pips):
    """Trail SL atr_mult_pips below running max favorable high."""
    if not trace:
        return 0
    running_max = 0
    initial_sl = -sl_pips
    trailing_sl = initial_sl
    for utc_t, hi_pip_raw, lo_pip_raw, cl_pip_raw in trace:
        hi_p = hi_pip_raw / p
        lo_p = lo_pip_raw / p
        # Check SL first (conservative)
        if lo_p <= trailing_sl:
            return trailing_sl
        # Update running max + trailing SL
        if hi_p > running_max:
            running_max = hi_p
            new_sl = running_max - atr_mult_pips
            if new_sl > trailing_sl:
                trailing_sl = new_sl
    # No SL hit — close at last
    return trace[-1][3] / p


def policy_blended(trace, p, sl_pips, tp_lock_pips, lock_fraction,
                   chandelier_pips, hold_max_pips=None):
    """60% leg: flat TP at +tp_lock_pips, original SL.
    40% leg (or 1-lock_fraction): chandelier trail of chandelier_pips below peak.

    Both legs share intra-bar timeline. Conservative SL-first within bar.
    Returns weighted total pips.
    """
    if not trace:
        return 0

    flat_alive = True
    flat_pnl = 0.0
    trail_alive = True
    trail_pnl = 0.0
    running_max = 0.0
    trail_sl = -sl_pips  # both legs start with same SL

    for utc_t, hi_pip_raw, lo_pip_raw, cl_pip_raw in trace:
        hi_p = hi_pip_raw / p
        lo_p = lo_pip_raw / p

        # Update running max BEFORE checking SL (peak reached intra-bar)
        if hi_p > running_max:
            running_max = hi_p
            new_trail = running_max - chandelier_pips
            if new_trail > trail_sl:
                trail_sl = new_trail

        # Conservative: check SL first (worst-case ordering within bar)
        if flat_alive and lo_p <= -sl_pips:
            flat_pnl = -sl_pips
            flat_alive = False
        if trail_alive and lo_p <= trail_sl:
            trail_pnl = trail_sl
            trail_alive = False

        # Then check TP for flat leg
        if flat_alive and hi_p >= tp_lock_pips:
            flat_pnl = tp_lock_pips
            flat_alive = False

        # Optional cap for trail leg (e.g., T2 hard cap)
        if trail_alive and hold_max_pips is not None and hi_p >= hold_max_pips:
            trail_pnl = hold_max_pips
            trail_alive = False

        if not flat_alive and not trail_alive:
            break

    # Trades that didn't exit by end of window — close at last bar's close
    if flat_alive:
        flat_pnl = trace[-1][3] / p
    if trail_alive:
        trail_pnl = trace[-1][3] / p

    return lock_fraction * flat_pnl + (1 - lock_fraction) * trail_pnl


def main():
    trades = pd.read_csv(TRADES_CSV)
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)

    bar_cache = {}
    rows = []
    for _, t in trades.iterrows():
        sym = t["symbol"]
        if sym not in bar_cache:
            bar_cache[sym] = load_bars(sym)
        df = bar_cache[sym]
        if df is None:
            continue
        p = pip(sym)
        direction = t["direction"]
        entry = t["entry_price"]
        t1 = t["target_1"]
        t2 = t["target_2"]
        sl = t["stop_loss"]
        opened_at = t["opened_at"].to_pydatetime()

        if direction == "LONG":
            t1_pips = (t1 - entry) / p
            t2_pips = (t2 - entry) / p
            sl_pips = (entry - sl) / p
        else:
            t1_pips = (entry - t1) / p
            t2_pips = (entry - t2) / p
            sl_pips = (sl - entry) / p

        trace, _ = trace_trade(df, opened_at, direction, entry, sl, t1, t2)
        if not trace:
            continue

        # MFE in pips
        mfe = max((hi for _, hi, _, _ in trace), default=0) / p

        # Policies
        actual_pips = t["pnl_pips"] if pd.notna(t["pnl_pips"]) else 0
        # P1: Lock 50% at +15p, rest runs to T2 or SL
        p1 = policy_lock_at_mfe(trace, p, t1_pips, t2_pips, sl_pips, 15, 0.5)
        # P2: Lock 100% at +20p (effectively a +20p TP)
        p2 = policy_lock_at_mfe(trace, p, t1_pips, t2_pips, sl_pips, 20, 1.0)
        # P3: Chandelier trail at 10p below peak
        p3 = policy_chandelier_trail(trace, p, sl_pips, 10)
        # P4: Chandelier 15p
        p4 = policy_chandelier_trail(trace, p, sl_pips, 15)
        # P5: Chandelier 20p
        p5 = policy_chandelier_trail(trace, p, sl_pips, 20)
        # P6: Lock 60% at +15p, chandelier 10p on remaining
        # Combined policy — first lock half, then trail
        p6 = policy_lock_at_mfe(trace, p, t1_pips, t2_pips, sl_pips, 15, 0.6)

        # P7: Blended — 60% flat TP @ +20p, 40% chandelier trail
        p7a = policy_blended(trace, p, sl_pips, 20, 0.6, 10)   # tight trail
        p7b = policy_blended(trace, p, sl_pips, 20, 0.6, 15)   # mid trail
        p7c = policy_blended(trace, p, sl_pips, 20, 0.6, 20)   # loose trail
        # Variant: 60% TP @ +15p (tighter lock-in)
        p8a = policy_blended(trace, p, sl_pips, 15, 0.6, 15)
        # Variant: 70/30 split (more locked, less trail)
        p9 = policy_blended(trace, p, sl_pips, 20, 0.7, 15)
        # Variant: 50/50 split (more trail upside)
        p10 = policy_blended(trace, p, sl_pips, 20, 0.5, 15)

        rows.append({
            "id": int(t["id"]),
            "symbol": sym,
            "close_reason": t["close_reason"],
            "actual": round(actual_pips, 1),
            "mfe": round(mfe, 1),
            "t1_pips": round(t1_pips, 1),
            "t2_pips": round(t2_pips, 1),
            "sl_pips": round(sl_pips, 1),
            "P1_lock50_at15": round(p1, 1),
            "P2_TP_at20": round(p2, 1),
            "P3_chand_10p": round(p3, 1),
            "P4_chand_15p": round(p4, 1),
            "P5_chand_20p": round(p5, 1),
            "P6_lock60_at15": round(p6, 1),
            "P7a_60TP20_40trail10": round(p7a, 1),
            "P7b_60TP20_40trail15": round(p7b, 1),
            "P7c_60TP20_40trail20": round(p7c, 1),
            "P8a_60TP15_40trail15": round(p8a, 1),
            "P9_70TP20_30trail15": round(p9, 1),
            "P10_50TP20_50trail15": round(p10, 1),
        })

    df_out = pd.DataFrame(rows)
    n = len(df_out)
    print(f"Analyzed {n} trades")
    print()

    # Aggregate
    cols = ["actual", "P1_lock50_at15", "P2_TP_at20", "P3_chand_10p",
            "P4_chand_15p", "P5_chand_20p", "P6_lock60_at15",
            "P7a_60TP20_40trail10", "P7b_60TP20_40trail15",
            "P7c_60TP20_40trail20", "P8a_60TP15_40trail15",
            "P9_70TP20_30trail15", "P10_50TP20_50trail15"]
    print(f"{'Policy':<20} {'Total':>9} {'Avg':>7} {'WR':>5} {'PF':>5}")
    print("-" * 60)
    for c in cols:
        a = df_out[c].values
        wins = (a > 0).sum()
        gp = a[a > 0].sum() if wins else 0
        gl = abs(a[a <= 0].sum()) if (a <= 0).sum() else 0.001
        print(f"{c:<20} {a.sum():>+8.1f}p {a.sum()/n:>+6.1f}p {wins/n*100:>4.0f}% {gp/gl:>5.2f}")

    # MFE bucket analysis
    print("\n=== Where the giveback lives (by MFE bucket) ===")
    df_out["mfe_bucket"] = pd.cut(df_out["mfe"],
        bins=[-1, 5, 10, 20, 30, 50, 200],
        labels=["0-5p", "5-10p", "10-20p", "20-30p", "30-50p", "50p+"])
    grp = df_out.groupby("mfe_bucket", observed=True).agg(
        n=("id", "count"),
        actual_total=("actual", "sum"),
        mfe_total=("mfe", "sum"),
        actual_avg=("actual", "mean"),
        mfe_avg=("mfe", "mean"),
    )
    grp["capture_pct"] = (grp["actual_total"] / grp["mfe_total"] * 100).round(1)
    print(grp.to_string(float_format=lambda x: f"{x:+.1f}"))

    # ─── Plot ─────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Actual vs MFE scatter
    ax = axes[0, 0]
    colors = {"STOP_LOSS": "#d62728", "TRAILING_STOP": "#ff7f0e",
              "TAKE_PROFIT": "#2ca02c", "TARGET_2": "#1f77b4",
              "BREAKEVEN_SL": "#9467bd", "INVALIDATION": "#8c564b",
              "RECONCILIATION": "#7f7f7f", "TIME_STOP": "#bcbd22"}
    for cr in df_out["close_reason"].unique():
        sub = df_out[df_out["close_reason"] == cr]
        ax.scatter(sub["mfe"], sub["actual"], c=colors.get(cr, "black"),
                   label=f"{cr} (n={len(sub)})", alpha=0.7, s=40)
    # Diagonal lines
    mx = max(df_out["mfe"].max(), 60) + 5
    ax.plot([0, mx], [0, mx], "k--", lw=0.5, alpha=0.5, label="100% capture")
    ax.plot([0, mx], [0, mx*0.5], "k:", lw=0.5, alpha=0.5, label="50% capture")
    ax.plot([0, mx], [0, mx*0.25], "k:", lw=0.5, alpha=0.3, label="25% capture")
    ax.axhline(0, color="black", lw=0.3)
    ax.set_xlabel("MFE (pips)")
    ax.set_ylabel("Actual PnL (pips)")
    ax.set_title("Actual vs MFE per trade")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.3)

    # 2. Cumulative pips comparison — focus on best contenders
    ax = axes[0, 1]
    for c, label, lw, ls in [
        ("actual", "ACTUAL", 1.6, "-"),
        ("P2_TP_at20", "P2: flat TP @ +20p", 1.6, "-"),
        ("P7a_60TP20_40trail10", "P7a: 60%TP@20p + 40%trail10p", 1.4, "-"),
        ("P7b_60TP20_40trail15", "P7b: 60%TP@20p + 40%trail15p", 1.4, "-"),
        ("P7c_60TP20_40trail20", "P7c: 60%TP@20p + 40%trail20p", 1.2, "--"),
        ("P9_70TP20_30trail15", "P9: 70%TP@20p + 30%trail15p", 1.2, "--"),
        ("P10_50TP20_50trail15", "P10: 50%TP@20p + 50%trail15p", 1.2, "--"),
    ]:
        ax.plot(np.cumsum(df_out[c]), label=label, lw=lw, linestyle=ls)
    ax.axhline(0, color="black", lw=0.3)
    ax.set_title("Cumulative pips: exit policies side-by-side")
    ax.set_xlabel("Trade #"); ax.set_ylabel("Cumulative pips")
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)

    # 3. MFE bucket: actual capture %
    ax = axes[1, 0]
    bx = grp.index.astype(str)
    by = grp["capture_pct"].values
    bn = grp["n"].values
    bars = ax.bar(bx, by, color="#1f77b4", edgecolor="black")
    for bar, n, pct in zip(bars, bn, by):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f"n={n}\n{pct:.0f}%", ha="center", va="bottom", fontsize=9)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Actual capture % of MFE, by MFE bucket")
    ax.set_ylabel("Capture % (actual / MFE)")
    ax.grid(alpha=0.3, axis="y")

    # 4. Per-policy bar chart
    ax = axes[1, 1]
    totals = [df_out[c].sum() for c in cols]
    colors_b = ["#d62728" if v < 0 else "#2ca02c" for v in totals]
    ax.barh([c.replace("_", " ") for c in cols], totals, color=colors_b, edgecolor="black")
    for i, v in enumerate(totals):
        ax.text(v + (3 if v >= 0 else -3), i, f"{v:+.0f}p", va="center",
                ha="left" if v >= 0 else "right", fontsize=9)
    ax.axvline(0, color="black", lw=0.5)
    ax.set_title("Total pips by exit policy (117 trades)")
    ax.set_xlabel("Pips")
    ax.grid(alpha=0.3, axis="x")

    plt.suptitle(
        f"KZ_HUNT MFE-capture analysis — {n} trades since 2026-03-25\n"
        f"Goal: find an exit policy that captures more of the +4014p theoretical max",
        fontsize=12,
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {OUT_PNG}")
    df_out.to_csv(ROOT / "data/kz_mfe_per_trade.csv", index=False)


if __name__ == "__main__":
    main()
