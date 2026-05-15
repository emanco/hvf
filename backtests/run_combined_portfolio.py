"""Combined portfolio: ASB (GBPJPY+EURJPY) + RSI(2) (broader 5-pair).

Runs both strategies independently from $700 starting equity, restricted to
the period where both have data: 2025-08-13 to 2026-04-16 (ASB M5 window).

Plots 3 curves:
  - ASB standalone
  - RSI(2) standalone (restricted to same window)
  - Combined: cumulative sum of both strategies' PnL by time

Tests the hypothesis that the two strategies are uncorrelated enough that
their combined equity is smoother than either alone.
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

# Import the two strategy scripts as modules
sys.path.insert(0, str(REPO_ROOT / "backtests"))
import run_asb_validation as asb
import run_rsi2_validation as rsi2

START_DATE = pd.Timestamp("2025-08-13", tz="UTC")
END_DATE = pd.Timestamp("2026-04-16", tz="UTC")
STARTING_EQUITY = 700.0
SEED = 1003


def run_asb_in_window():
    """Run ASB on its 2-pair winning subset (GBPJPY + EURJPY)."""
    random.seed(SEED)
    asb.PAIRS = ["GBPJPY", "EURJPY"]
    equity_ref = [STARTING_EQUITY]
    trades = []
    for sym in asb.PAIRS:
        df = asb.load_m5(sym)
        trades.extend(asb.simulate_pair(sym, df, equity_ref))
    # Already within window since M5 data starts at 2025-08-13
    return trades


def run_rsi2_in_window():
    """Run RSI(2) on the broader 4-pair (no EURGBP) subset, then filter trades."""
    random.seed(SEED)
    pairs = ["EURUSD", "EURCHF", "USDCHF", "NZDUSD", "AUDCAD"]
    equity_ref = [STARTING_EQUITY]
    all_trades = []
    for sym in pairs:
        try:
            df = rsi2.load_daily(sym)
        except FileNotFoundError:
            continue
        all_trades.extend(rsi2.simulate_pair(sym, df, equity_ref))
    # Filter to overlapping window
    def _to_utc(x):
        ts = pd.Timestamp(x)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts

    in_window = [
        t for t in all_trades
        if t.exit_time is not None
        and _to_utc(t.exit_time) >= START_DATE
        and _to_utc(t.entry_time) <= END_DATE
    ]
    return in_window


def _norm_ts(x):
    ts = pd.Timestamp(x)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def build_equity_curve(trades, label: str):
    """Build a time-indexed equity curve starting at STARTING_EQUITY."""
    sorted_t = sorted(
        trades,
        key=lambda t: _norm_ts(t.exit_time) if t.exit_time is not None
        else pd.Timestamp.max.tz_localize("UTC")
    )
    times = [_norm_ts(sorted_t[0].entry_time)] if sorted_t else []
    eq = [STARTING_EQUITY]
    for t in sorted_t:
        eq.append(eq[-1] + t.pnl_usd)
        times.append(_norm_ts(t.exit_time))
    return times, eq


def build_combined_curve(asb_trades, rsi2_trades):
    """Combine into a single equity stream. Each strategy keeps its own
    PnL contribution; combined equity is starting + sum of both PnLs."""
    events = []
    for t in asb_trades:
        events.append((_norm_ts(t.exit_time), t.pnl_usd, "ASB"))
    for t in rsi2_trades:
        events.append((_norm_ts(t.exit_time), t.pnl_usd, "RSI"))
    events.sort(key=lambda e: e[0])
    times = [START_DATE]
    eq = [STARTING_EQUITY]
    for ts, pnl, _ in events:
        times.append(ts)
        eq.append(eq[-1] + pnl)
    return times, eq


def summarize(trades, label):
    if not trades:
        return f"{label}: 0 trades"
    wins = [t for t in trades if t.pnl_pips > 0]
    losses = [t for t in trades if t.pnl_pips <= 0]
    gw = sum(t.pnl_pips for t in wins)
    gl = abs(sum(t.pnl_pips for t in losses))
    pf = gw / gl if gl else float("inf")
    total_usd = sum(t.pnl_usd for t in trades)
    return (
        f"{label}: N={len(trades)} WR={len(wins)/len(trades)*100:.1f}% "
        f"PF={pf:.2f} pips={sum(t.pnl_pips for t in trades):+.1f} "
        f"USD=${total_usd:+.2f}"
    )


def main():
    print(f"Combined portfolio backtest")
    print(f"  Window: {START_DATE.date()} to {END_DATE.date()}")
    print(f"  Starting equity: ${STARTING_EQUITY}  Seed: {SEED}\n")

    asb_trades = run_asb_in_window()
    rsi2_trades = run_rsi2_in_window()

    print(summarize(asb_trades, "ASB (GBPJPY+EURJPY)"))
    print(summarize(rsi2_trades, "RSI(2) broader (4-pair, in window)"))

    asb_times, asb_eq = build_equity_curve(asb_trades, "ASB")
    rsi2_times, rsi2_eq = build_equity_curve(rsi2_trades, "RSI(2)")
    cmb_times, cmb_eq = build_combined_curve(asb_trades, rsi2_trades)

    # Stats
    def curve_stats(times, eq, label):
        if len(eq) < 2:
            return None
        peak = np.maximum.accumulate(np.array(eq))
        dd = (np.array(eq) - peak) / peak * 100
        return {
            "label": label,
            "final": eq[-1],
            "ret_pct": (eq[-1] - STARTING_EQUITY) / STARTING_EQUITY * 100,
            "max_dd": abs(dd.min()),
        }

    a_stats = curve_stats(asb_times, asb_eq, "ASB")
    r_stats = curve_stats(rsi2_times, rsi2_eq, "RSI(2)")
    c_stats = curve_stats(cmb_times, cmb_eq, "Combined")

    print(f"\nFinal equity:")
    for s in (a_stats, r_stats, c_stats):
        if s:
            print(
                f"  {s['label']:<10} ${s['final']:>7.2f}  "
                f"({s['ret_pct']:+.1f}%)  MaxDD {s['max_dd']:.1f}%"
            )

    # Plot
    fig, axes = plt.subplots(
        2, 1, figsize=(14, 9),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.3},
    )
    ax1 = axes[0]
    ax1.plot(asb_times, asb_eq, color="darkorange", linewidth=1.4,
             label=f"ASB only ($700 → ${asb_eq[-1]:.0f}, {a_stats['ret_pct']:+.1f}%)",
             alpha=0.85)
    ax1.plot(rsi2_times, rsi2_eq, color="steelblue", linewidth=1.4,
             label=f"RSI(2) only ($700 → ${rsi2_eq[-1]:.0f}, {r_stats['ret_pct']:+.1f}%)",
             alpha=0.85)
    ax1.plot(cmb_times, cmb_eq, color="seagreen", linewidth=2.2,
             label=f"COMBINED ($700 → ${cmb_eq[-1]:.0f}, {c_stats['ret_pct']:+.1f}%)")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax1.set_title(
        f"Combined Portfolio: ASB + RSI(2) — same period overlay\n"
        f"ASB={len(asb_trades)} trades  |  RSI(2)={len(rsi2_trades)} trades  |  "
        f"Combined MaxDD={c_stats['max_dd']:.1f}%",
        fontsize=12, fontweight="bold", linespacing=1.4,
    )
    ax1.set_ylabel("Equity ($)")
    ax1.legend(fontsize=10, loc="upper left")
    ax1.grid(True, alpha=0.3)

    # Drawdown subplot — combined only
    eq_arr = np.array(cmb_eq)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak * 100
    ax2 = axes[1]
    ax2.fill_between(cmb_times, dd, 0, color="red", alpha=0.3)
    ax2.plot(cmb_times, dd, color="red", linewidth=0.8)
    ax2.set_ylabel("Combined DD (%)")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out_png = REPO_ROOT / "backtests" / "charts" / "combined_portfolio.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved chart: {out_png}")


if __name__ == "__main__":
    main()
