"""ASB trend-aligned overlay backtest.

Overlays an H1 EMA200 regime filter on the ASB bracket placement:
  - If price > EMA200 (uptrend): place BUY_STOP only, skip SELL_STOP
  - If price < EMA200 (downtrend): place SELL_STOP only, skip BUY_STOP

Compares baseline (no filter, both sides) vs trend-aligned (filtered side)
on the same 8-month M5 data. Mirrors QL's directional filter design.
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


SEEDS = (1001, 1002, 1003, 1004, 1005)
TREND_THRESHOLD_PIPS = 30  # band around EMA200 where we trade both directions


def h1_ema200_at(df_m5: pd.DataFrame, target_time: pd.Timestamp) -> tuple[float, float] | None:
    """Compute H1 EMA200 close + current price as of target_time (07:00 UTC).

    Returns (current_close, ema200_value) or None if insufficient data.
    """
    if df_m5 is None or df_m5.empty or "time" not in df_m5.columns:
        return None
    cut = df_m5[df_m5["time"] < target_time]
    if len(cut) < 1500:  # need at least ~200 H1 bars of M5 data (~12 hr × 200)
        return None
    df = cut.set_index("time")
    h1 = df.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    if len(h1) < 220:
        return None
    ema = h1["close"].ewm(span=200, adjust=False).mean()
    return float(h1["close"].iloc[-1]), float(ema.iloc[-1])


def simulate_pair_with_trend(symbol, df, equity_ref):
    """Variant of asb.simulate_pair that skips the trend-fighting side at placement."""
    import pandas as pd
    from datetime import datetime, timedelta, time as time_obj

    # Borrow much of the parent's logic but inject trend filter at placement.
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
        if weekday in (5, 6):
            continue

        asian_window = day_df[
            (day_df["time"].dt.hour >= asb.ASIAN_START_H)
            & (day_df["time"].dt.hour < asb.ASIAN_END_H)
        ]
        if len(asian_window) < 5:
            continue

        asian_high = asian_window["high"].max()
        asian_low = asian_window["low"].min()
        range_size = (asian_high - asian_low) / pip
        if range_size <= 0:
            continue

        prev_date = (pd.Timestamp(date) - pd.Timedelta(days=1)).date()
        adr_prev = adr_lookup.get(prev_date)
        if adr_prev is None or pd.isna(adr_prev):
            continue
        adr_prev_pips = adr_prev / pip
        if range_size < 0.4 * adr_prev_pips or range_size > 1.0 * adr_prev_pips:
            continue

        buffer_pips = max(2.0, 0.10 * range_size)
        long_stop = asian_high + buffer_pips * pip
        short_stop = asian_low - buffer_pips * pip

        # Trend filter: as of 07:00 UTC, compute H1 EMA200
        capture_time = pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=asb.ASIAN_END_H)
        trend_info = h1_ema200_at(df, capture_time)
        place_long = True
        place_short = True
        if trend_info is not None:
            current, ema200 = trend_info
            diff_pips = (current - ema200) / pip
            if diff_pips > TREND_THRESHOLD_PIPS:
                # Uptrend — skip SHORT
                place_short = False
            elif diff_pips < -TREND_THRESHOLD_PIPS:
                # Downtrend — skip LONG
                place_long = False

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
                slip_p = asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN,
                                              asb.STOP_SLIPPAGE_STD,
                                              asb.STOP_SLIPPAGE_CLIP)
                fill_price = short_stop - slip_p * pip
                break
            if long_hit and not short_hit:
                filled_dir = "LONG"
                fill_time = bar["time"]
                slip_p = asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN,
                                              asb.STOP_SLIPPAGE_STD,
                                              asb.STOP_SLIPPAGE_CLIP)
                fill_price = long_stop + slip_p * pip
                break
            if short_hit and long_hit:
                if abs(bar["open"] - long_stop) < abs(bar["open"] - short_stop):
                    filled_dir = "LONG"
                    slip_p = asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN,
                                                  asb.STOP_SLIPPAGE_STD,
                                                  asb.STOP_SLIPPAGE_CLIP)
                    fill_price = long_stop + slip_p * pip
                else:
                    filled_dir = "SHORT"
                    slip_p = asb.adverse_slippage(asb.STOP_SLIPPAGE_MEAN,
                                                  asb.STOP_SLIPPAGE_STD,
                                                  asb.STOP_SLIPPAGE_CLIP)
                    fill_price = short_stop - slip_p * pip
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
                if bar["low"] <= sl and bar["high"] >= tp:
                    exit_time, exit_price, exit_reason = t, sl, "SL"
                    break
                if bar["low"] <= sl:
                    exit_time, exit_price, exit_reason = t, sl, "SL"
                    break
                if bar["high"] >= tp:
                    exit_time, exit_price, exit_reason = t, tp, "TP"
                    break
            else:
                if bar["high"] >= sl and bar["low"] <= tp:
                    exit_time, exit_price, exit_reason = t, sl, "SL"
                    break
                if bar["high"] >= sl:
                    exit_time, exit_price, exit_reason = t, sl, "SL"
                    break
                if bar["low"] <= tp:
                    exit_time, exit_price, exit_reason = t, tp, "TP"
                    break

        if exit_time is None:
            continue

        slip_p = asb.adverse_slippage(asb.EXIT_SLIPPAGE_MEAN, asb.EXIT_SLIPPAGE_STD,
                                      asb.EXIT_SLIPPAGE_CLIP)
        if filled_dir == "LONG":
            exit_fill = exit_price - slip_p * pip
            pnl_pips = (exit_fill - fill_price) / pip
        else:
            exit_fill = exit_price + slip_p * pip
            pnl_pips = (fill_price - exit_fill) / pip

        stop_pips = abs(fill_price - sl) / pip
        equity_now = equity_ref[0]
        risk_usd = equity_now * (asb.RISK_PCT / 100.0)
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


def run_arm(use_trend_filter: bool):
    """Run one arm with or without trend filter. Aggregates across seeds."""
    asb.PAIRS = ["GBPJPY", "EURJPY"]
    per_seed = []
    for seed in SEEDS:
        random.seed(seed)
        equity_ref = [asb.STARTING_EQUITY]
        all_trades = []
        for sym in asb.PAIRS:
            df = asb.load_m5(sym)
            if use_trend_filter:
                t = simulate_pair_with_trend(sym, df, equity_ref)
            else:
                t = asb.simulate_pair(sym, df, equity_ref)
            all_trades.extend(t)
        per_seed.append((seed, all_trades, equity_ref[0]))
    return per_seed


def summarize(trades):
    if not trades:
        return {"n": 0}
    wins = [t for t in trades if t.pnl_pips > 0]
    losses = [t for t in trades if t.pnl_pips <= 0]
    gw = sum(t.pnl_pips for t in wins)
    gl = abs(sum(t.pnl_pips for t in losses))
    pf = gw / gl if gl else float("inf")
    return {
        "n": len(trades),
        "wr": len(wins) / len(trades) * 100,
        "pf": pf,
        "pips": sum(t.pnl_pips for t in trades),
        "usd": sum(t.pnl_usd for t in trades),
    }


def build_curve(trades):
    sorted_t = sorted(trades, key=lambda x: x.exit_time)
    times = [sorted_t[0].entry_time] if sorted_t else []
    eq = [asb.STARTING_EQUITY]
    for t in sorted_t:
        eq.append(eq[-1] + t.pnl_usd)
        times.append(t.exit_time)
    return times, eq


def main():
    print("Asian Session Breakout — trend-filter overlay backtest")
    print(f"  Pairs: GBPJPY, EURJPY  Window: 8 months M5")
    print(f"  Trend filter threshold: ±{TREND_THRESHOLD_PIPS}p from H1 EMA200\n")

    print("Arm A: baseline (no trend filter)")
    a = run_arm(use_trend_filter=False)
    print("Arm B: trend-aligned (skip side fighting H1 EMA200)")
    b = run_arm(use_trend_filter=True)

    for label, runs in (("BASELINE", a), ("TREND-FILTERED", b)):
        print(f"\n{label}:")
        pfs, finals = [], []
        for seed, trades, final in runs:
            s = summarize(trades)
            pfs.append(s["pf"]); finals.append(final)
            print(
                f"  seed={seed}: N={s['n']:>3} WR={s['wr']:5.1f}% PF={s['pf']:5.2f} "
                f"pips={s['pips']:+8.1f} USD={s['usd']:+7.2f} final=${final:,.2f}"
            )
        print(f"  mean PF: {sum(pfs)/len(pfs):.2f}  mean final: ${sum(finals)/len(finals):,.2f}")

    # Use seed 1003 (middle) for the chart
    mid_a = a[len(a) // 2][1]
    mid_b = b[len(b) // 2][1]
    a_times, a_eq = build_curve(mid_a)
    b_times, b_eq = build_curve(mid_b)
    a_stats = summarize(mid_a)
    b_stats = summarize(mid_b)

    # Per-direction breakdown for the filtered arm
    print(f"\nFiltered-arm directional split (seed=1003):")
    longs = [t for t in mid_b if t.direction == "LONG"]
    shorts = [t for t in mid_b if t.direction == "SHORT"]
    print(f"  LONG  : {summarize(longs)}")
    print(f"  SHORT : {summarize(shorts)}")

    # Drawdowns
    a_dd_max = abs(((np.array(a_eq) - np.maximum.accumulate(a_eq)) / np.maximum.accumulate(a_eq) * 100).min())
    b_dd_max = abs(((np.array(b_eq) - np.maximum.accumulate(b_eq)) / np.maximum.accumulate(b_eq) * 100).min())

    fig, axes = plt.subplots(
        2, 1, figsize=(14, 9),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.3},
    )
    ax1 = axes[0]
    ax1.plot(a_times, a_eq, color="steelblue", linewidth=1.4,
             label=f"Baseline ASB (PF {a_stats['pf']:.2f}, +${a_eq[-1] - asb.STARTING_EQUITY:.0f}, DD {a_dd_max:.1f}%, N={a_stats['n']})",
             alpha=0.8)
    ax1.plot(b_times, b_eq, color="seagreen", linewidth=2.0,
             label=f"Trend-filtered ASB (PF {b_stats['pf']:.2f}, +${b_eq[-1] - asb.STARTING_EQUITY:.0f}, DD {b_dd_max:.1f}%, N={b_stats['n']})")
    ax1.axhline(y=asb.STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax1.set_title(
        f"ASB Trend-Filter Overlay — GBPJPY+EURJPY, M5 8mo",
        fontsize=12, fontweight="bold",
    )
    ax1.set_ylabel("Equity ($)")
    ax1.legend(fontsize=10, loc="upper left")
    ax1.grid(True, alpha=0.3)

    # Drawdown of trend-filtered (the candidate to deploy)
    eq_arr = np.array(b_eq)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak * 100
    ax2 = axes[1]
    ax2.fill_between(b_times, dd, 0, color="red", alpha=0.3)
    ax2.plot(b_times, dd, color="red", linewidth=0.7)
    ax2.set_ylabel("DD (%) trend-filtered")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out = REPO_ROOT / "backtests" / "charts" / "asb_trend_filter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved chart: {out}")


if __name__ == "__main__":
    main()
