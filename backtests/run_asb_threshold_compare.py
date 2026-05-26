"""ASB 0.3 vs 0.4 threshold comparison.

Live since 2026-05-15 deploy, ASB fired 0 trades — Asian-session ranges have
been 19-36% of ADR(14) on most days, well under the original 0.4 gate. Today
(2026-05-26) lowered to 0.3 to capture borderline-tight days. This script
re-runs the existing 8mo M5 backtest at both thresholds, with the production
config (GBPJPY+EURJPY, trend filter, 5 seeds), so we have a data-driven check
of the parameter change before committing live capital to it.

Comparing:
  - min_range_pct_adr = 0.4 (original)
  - min_range_pct_adr = 0.3 (proposed live)
  - max stays at 1.0 in both
"""
from __future__ import annotations
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(REPO_ROOT / "backtests"))
import run_asb_validation as asb
import run_asb_trend_filter as tf

SEEDS = (1001, 1002, 1003, 1004, 1005)
PAIRS = ["GBPJPY", "EURJPY"]
TREND_THRESHOLD_PIPS = 30


def simulate_pair_with_thresholds(
    symbol, df, equity_ref, min_pct_adr, max_pct_adr, use_trend_filter,
):
    """Fork of asb.simulate_pair with parameterized min/max ADR pct + trend overlay."""
    pip = asb.pip_size(symbol)
    trades = []
    df_indexed = df.set_index("time")
    daily = df_indexed.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    daily["adr14"] = asb.adr(daily)
    adr_lookup = {d.date(): v for d, v in daily["adr14"].items()}
    df = df.copy()
    df["date"] = df["time"].dt.date

    for date, day_df in df.groupby("date"):
        day_df = day_df.sort_values("time").reset_index(drop=True)
        dt = pd.Timestamp(date).tz_localize("UTC")
        weekday = dt.weekday()
        if weekday in (4, 5, 6):  # Match production config: skip Fri/Sat/Sun
            continue

        asian = day_df[
            (day_df["time"].dt.hour >= asb.ASIAN_START_H)
            & (day_df["time"].dt.hour < asb.ASIAN_END_H)
        ]
        if len(asian) < 5:
            continue
        asian_high = asian["high"].max()
        asian_low = asian["low"].min()
        range_size = (asian_high - asian_low) / pip
        if range_size <= 0:
            continue

        prev_date = (pd.Timestamp(date) - pd.Timedelta(days=1)).date()
        adr_prev = adr_lookup.get(prev_date)
        if adr_prev is None or pd.isna(adr_prev):
            continue
        adr_prev_pips = adr_prev / pip

        # PARAMETERIZED GATE
        if range_size < min_pct_adr * adr_prev_pips or range_size > max_pct_adr * adr_prev_pips:
            continue

        buffer_pips = max(2.0, 0.10 * range_size)
        long_stop = asian_high + buffer_pips * pip
        short_stop = asian_low - buffer_pips * pip

        # Trend filter overlay (only place the trend-aligned side if price > threshold from EMA200)
        place_long, place_short = True, True
        if use_trend_filter:
            seven_am = pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=asb.ASIAN_END_H)
            ema_info = tf.h1_ema200_at(df, seven_am)
            if ema_info is not None:
                cur, ema_val = ema_info
                diff_pips = (cur - ema_val) / pip
                if diff_pips > TREND_THRESHOLD_PIPS:
                    place_short = False  # uptrend; skip short side
                elif diff_pips < -TREND_THRESHOLD_PIPS:
                    place_long = False   # downtrend; skip long side
        if not place_long and not place_short:
            continue

        active = day_df[
            (day_df["time"].dt.hour >= asb.ASIAN_END_H)
            & (day_df["time"].dt.hour < asb.LONDON_END_H)
        ].sort_values("time").reset_index(drop=True)
        if active.empty:
            continue

        filled_dir = None
        fill_time = None
        fill_price = None
        for _, bar in active.iterrows():
            short_hit = place_short and bar["low"] <= short_stop
            long_hit = place_long and bar["high"] >= long_stop
            if short_hit and not long_hit:
                filled_dir = "SHORT"
                fill_time = bar["time"]
                slip_p = asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN, asb.STOP_SLIPPAGE_STD, asb.STOP_SLIPPAGE_CLIP)
                fill_price = short_stop - slip_p * pip
                break
            if long_hit and not short_hit:
                filled_dir = "LONG"
                fill_time = bar["time"]
                slip_p = asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN, asb.STOP_SLIPPAGE_STD, asb.STOP_SLIPPAGE_CLIP)
                fill_price = long_stop + slip_p * pip
                break
            if short_hit and long_hit:
                if abs(bar["open"] - long_stop) < abs(bar["open"] - short_stop):
                    filled_dir = "LONG"
                    fill_price = long_stop + asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN, asb.STOP_SLIPPAGE_STD, asb.STOP_SLIPPAGE_CLIP) * pip
                else:
                    filled_dir = "SHORT"
                    fill_price = short_stop - asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN, asb.STOP_SLIPPAGE_STD, asb.STOP_SLIPPAGE_CLIP) * pip
                fill_time = bar["time"]
                break

        if filled_dir is None:
            continue

        if filled_dir == "LONG":
            sl = asian_low - buffer_pips * pip
            tp = fill_price + range_size * pip
        else:
            sl = asian_high + buffer_pips * pip
            tp = fill_price - range_size * pip

        post_fill = day_df[day_df["time"] > fill_time].sort_values("time").reset_index(drop=True)
        if post_fill.empty:
            continue

        eod_time = pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=asb.EOD_H)
        exit_time = None
        exit_price = None
        exit_reason = ""
        for _, bar in post_fill.iterrows():
            t = bar["time"]
            if t >= eod_time:
                exit_time, exit_price, exit_reason = t, bar["open"], "TIME_STOP"
                break
            if filled_dir == "LONG":
                hit_sl = bar["low"] <= sl
                hit_tp = bar["high"] >= tp
            else:
                hit_sl = bar["high"] >= sl
                hit_tp = bar["low"] <= tp
            if hit_sl and hit_tp:
                exit_time, exit_price, exit_reason = t, sl, "SL"
                break
            if hit_sl:
                exit_time, exit_price, exit_reason = t, sl, "SL"
                break
            if hit_tp:
                exit_time, exit_price, exit_reason = t, tp, "TP"
                break

        if exit_time is None:
            continue

        slip_p = asb.adverse_slippage(asb.EXIT_SLIPPAGE_MEAN, asb.EXIT_SLIPPAGE_STD, asb.EXIT_SLIPPAGE_CLIP)
        if filled_dir == "LONG":
            exit_fill = exit_price - slip_p * pip
            pnl_pips = (exit_fill - fill_price) / pip
        else:
            exit_fill = exit_price + slip_p * pip
            pnl_pips = (fill_price - exit_fill) / pip

        stop_pips = abs(fill_price - sl) / pip
        risk_usd = equity_ref[0] * (asb.RISK_PCT / 100.0)
        lots = round(risk_usd / max(stop_pips * 10.0, 0.01), 2)
        lots = max(min(lots, 5.0), 0.01)
        pnl_usd = pnl_pips * lots * 10.0
        equity_ref[0] += pnl_usd

        trades.append(asb.Trade(
            pair=symbol, direction=filled_dir,
            range_size_pips=range_size,
            asian_high=asian_high, asian_low=asian_low,
            entry_time=fill_time, entry_price=fill_price, sl=sl, tp=tp,
            exit_time=exit_time, exit_price=exit_fill,
            exit_reason=exit_reason, pnl_pips=pnl_pips, pnl_usd=pnl_usd,
        ))
    return trades


def run_config(min_pct, max_pct, use_trend_filter, label):
    print(f"\n{'='*78}")
    print(f"{label}  (min_pct_adr={min_pct}, max_pct_adr={max_pct}, trend_filter={use_trend_filter})")
    print(f"{'='*78}")
    per_seed = []
    for seed in SEEDS:
        random.seed(seed)
        equity_ref = [asb.STARTING_EQUITY]
        all_trades = []
        for sym in PAIRS:
            df = asb.load_m5(sym)
            trades = simulate_pair_with_thresholds(
                sym, df, equity_ref, min_pct, max_pct, use_trend_filter,
            )
            all_trades.extend(trades)
        s = asb.summarize(all_trades)
        per_seed.append((seed, all_trades, equity_ref[0], s))
        if s["n"]:
            print(
                f"  seed={seed}: N={s['n']:>4} WR={s['wr']:5.1f}% PF={s['pf']:5.2f} "
                f"pips={s['pips']:+8.1f} USD={s['usd']:+8.2f} final=${equity_ref[0]:,.2f}"
            )
        else:
            print(f"  seed={seed}: 0 trades")

    pfs = [r[3]["pf"] for r in per_seed if r[3]["n"]]
    if pfs:
        mean_pf = sum(pfs) / len(pfs)
        std_pf = (sum((p - mean_pf) ** 2 for p in pfs) / max(len(pfs) - 1, 1)) ** 0.5
        mean_n = sum(r[3]["n"] for r in per_seed) / len(per_seed)
        mean_pips = sum(r[3]["pips"] for r in per_seed) / len(per_seed)
        mean_usd = sum(r[3]["usd"] for r in per_seed) / len(per_seed)
        print(
            f"\n  Across {len(pfs)} seeds: mean PF {mean_pf:.2f} (std {std_pf:.2f}, "
            f"range [{min(pfs):.2f}, {max(pfs):.2f}])"
        )
        print(f"  Mean N: {mean_n:.0f}  mean pips: {mean_pips:+.1f}  mean USD: ${mean_usd:+.2f}")
        # Per-pair
        mid = per_seed[len(per_seed) // 2]
        print(f"\n  Per-pair (seed={mid[0]}):")
        for sym in PAIRS:
            tp = [t for t in mid[1] if t.pair == sym]
            if not tp:
                print(f"    {sym}: 0 trades")
                continue
            wins = [t for t in tp if t.pnl_pips > 0]
            gw = sum(t.pnl_pips for t in wins)
            gl = abs(sum(t.pnl_pips for t in tp if t.pnl_pips <= 0))
            pf = gw / gl if gl else float("inf")
            print(
                f"    {sym}: N={len(tp):>4} WR={len(wins)/len(tp)*100:5.1f}% "
                f"PF={pf:5.2f} pips={sum(t.pnl_pips for t in tp):+8.1f}"
            )
        return mean_pf, mean_n, mean_pips, mean_usd, per_seed
    return None, 0, 0, 0, per_seed


def main():
    print("ASB threshold comparison: 0.4 vs 0.3")
    print(f"  Pairs: {PAIRS}")
    print(f"  Seeds: {SEEDS}")
    print(f"  Trend filter: ON (matches production)")

    results = {}
    for label, min_pct in [("BASELINE 0.4", 0.4), ("PROPOSED 0.3", 0.3)]:
        mean_pf, mean_n, mean_pips, mean_usd, per_seed = run_config(
            min_pct, 1.0, True, label,
        )
        results[label] = {
            "min_pct": min_pct, "mean_pf": mean_pf, "mean_n": mean_n,
            "mean_pips": mean_pips, "mean_usd": mean_usd, "per_seed": per_seed,
        }

    print("\n" + "=" * 78)
    print("SIDE-BY-SIDE COMPARISON")
    print("=" * 78)
    print(f"{'Config':<18} {'mean N':>8} {'mean PF':>9} {'mean pips':>11} {'mean USD':>11}")
    for label, r in results.items():
        print(
            f"{label:<18} {r['mean_n']:>8.0f} {r['mean_pf']:>9.2f} "
            f"{r['mean_pips']:>+11.1f} ${r['mean_usd']:>+10.2f}"
        )

    # Equity curve overlay (middle seed for each)
    fig, ax = plt.subplots(figsize=(14, 7))
    for label, r in results.items():
        mid = r["per_seed"][len(r["per_seed"]) // 2]
        trades = sorted(mid[1], key=lambda t: t.exit_time)
        if not trades:
            continue
        times = [trades[0].entry_time] + [t.exit_time for t in trades]
        eq = [asb.STARTING_EQUITY]
        for t in trades:
            eq.append(eq[-1] + t.pnl_usd)
        ax.plot(
            times, eq,
            label=f"{label} (N={len(trades)}, PF={r['mean_pf']:.2f}, final=${eq[-1]:,.0f})",
            linewidth=1.5,
        )
    ax.axhline(y=asb.STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax.set_title(f"ASB threshold comparison — {PAIRS}, trend filter ON\n0.4 vs 0.3 × ADR(14)",
                 fontsize=12, fontweight="bold")
    ax.set_ylabel("Equity ($)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    out = REPO_ROOT / "backtests" / "charts" / "asb_threshold_compare.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved chart: {out}")


if __name__ == "__main__":
    main()
