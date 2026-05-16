"""Carry-direction analysis on ASB trades.

Hypothesis: ASB on GBPJPY/EURJPY is structurally trading JPY-funding-currency
pairs. Historical carry: LONG = positive-carry direction. If LONGs systematically
outperform SHORTs, applying a "long-only" filter (or asymmetric sizing) on these
pairs could lift ASB's PF without changing the underlying signal.

Splits the standard ASB backtest by pair × direction × seed and reports per-cell
PF/WR/pips. Looks for asymmetry.
"""
from __future__ import annotations
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

sys.path.insert(0, str(REPO_ROOT / "backtests"))
import run_asb_validation as asb


SEEDS = (1001, 1002, 1003, 1004, 1005)


def summarize(trades, label):
    if not trades:
        return f"{label}: 0 trades"
    wins = [t for t in trades if t.pnl_pips > 0]
    losses = [t for t in trades if t.pnl_pips <= 0]
    gw = sum(t.pnl_pips for t in wins)
    gl = abs(sum(t.pnl_pips for t in losses))
    pf = gw / gl if gl else float("inf")
    avg = sum(t.pnl_pips for t in trades) / len(trades)
    return (
        f"{label}: N={len(trades):>3} WR={len(wins)/len(trades)*100:5.1f}% "
        f"PF={pf:5.2f} pips={sum(t.pnl_pips for t in trades):+8.1f} "
        f"avg={avg:+5.1f}p"
    )


def main():
    asb.PAIRS = ["GBPJPY", "EURJPY"]
    print(f"ASB carry-direction analysis — {asb.PAIRS}")
    print(f"  Seeds: {SEEDS}\n")

    # Aggregate across seeds
    per_cell: dict[tuple[str, str], list] = {}  # (pair, direction) -> trades
    for seed in SEEDS:
        random.seed(seed)
        equity_ref = [asb.STARTING_EQUITY]
        for sym in asb.PAIRS:
            df = asb.load_m5(sym)
            trades = asb.simulate_pair(sym, df, equity_ref)
            for t in trades:
                per_cell.setdefault((t.pair, t.direction), []).append(t)

    print("=" * 80)
    print("Per pair × direction (aggregated across 5 seeds — ~5x trade count)")
    print("=" * 80)
    for sym in asb.PAIRS:
        for direction in ("LONG", "SHORT"):
            trades = per_cell.get((sym, direction), [])
            print(f"  {sym:<8} {direction:<6}  {summarize(trades, '')}")

    # Per pair: PF asymmetry
    print()
    print("=" * 80)
    print("Direction asymmetry per pair (LONG PF vs SHORT PF)")
    print("=" * 80)
    for sym in asb.PAIRS:
        longs = per_cell.get((sym, "LONG"), [])
        shorts = per_cell.get((sym, "SHORT"), [])
        if not longs or not shorts:
            continue
        l_wins = [t for t in longs if t.pnl_pips > 0]
        s_wins = [t for t in shorts if t.pnl_pips > 0]
        l_gw = sum(t.pnl_pips for t in l_wins)
        l_gl = abs(sum(t.pnl_pips for t in longs if t.pnl_pips <= 0))
        s_gw = sum(t.pnl_pips for t in s_wins)
        s_gl = abs(sum(t.pnl_pips for t in shorts if t.pnl_pips <= 0))
        l_pf = l_gw / l_gl if l_gl else float("inf")
        s_pf = s_gw / s_gl if s_gl else float("inf")
        l_avg = sum(t.pnl_pips for t in longs) / len(longs)
        s_avg = sum(t.pnl_pips for t in shorts) / len(shorts)
        print(
            f"  {sym}: LONG PF={l_pf:.2f} avg={l_avg:+.1f}p  vs  "
            f"SHORT PF={s_pf:.2f} avg={s_avg:+.1f}p  "
            f"|  long_minus_short = {l_avg - s_avg:+.1f}p/trade"
        )

    # Combined long-only vs short-only across pairs
    print()
    print("=" * 80)
    print("Long-only vs Short-only across both pairs combined")
    print("=" * 80)
    all_longs = [t for k, v in per_cell.items() for t in v if k[1] == "LONG"]
    all_shorts = [t for k, v in per_cell.items() for t in v if k[1] == "SHORT"]
    print(f"  {summarize(all_longs, 'LONG  ')}")
    print(f"  {summarize(all_shorts, 'SHORT ')}")
    print(f"  {summarize(all_longs + all_shorts, 'BOTH  ')}")

    # If LONG outperforms SHORT, what would a long-only strategy look like?
    print()
    print("=" * 80)
    print("If we filtered to LONG-only on these pairs (hypothetical)")
    print("=" * 80)
    long_pips = sum(t.pnl_pips for t in all_longs)
    long_usd = sum(t.pnl_usd for t in all_longs)
    n_long = len(all_longs)
    short_pips = sum(t.pnl_pips for t in all_shorts)
    short_usd = sum(t.pnl_usd for t in all_shorts)
    n_short = len(all_shorts)
    n_total = n_long + n_short
    print(f"  Original (both): N={n_total} pips={long_pips + short_pips:+.1f} USD={long_usd + short_usd:+.2f}")
    print(f"  Long-only      : N={n_long}  pips={long_pips:+.1f} USD={long_usd:+.2f}")
    print(f"  Short-only     : N={n_short}  pips={short_pips:+.1f} USD={short_usd:+.2f}")

    # Telltale: if LONGs avg > 0 and SHORTs avg < 0, carry asymmetry is real
    print()
    print("Verdict:")
    if all_longs and all_shorts:
        l_avg = sum(t.pnl_pips for t in all_longs) / len(all_longs)
        s_avg = sum(t.pnl_pips for t in all_shorts) / len(all_shorts)
        diff = l_avg - s_avg
        if abs(diff) < 1.0:
            print(f"  No meaningful direction asymmetry ({diff:+.1f}p/trade). Carry not material here.")
        elif diff > 0:
            print(
                f"  LONG direction outperforms by {diff:+.1f}p/trade. "
                f"Carry hypothesis supported — a LONG-only or long-biased ASB "
                f"would likely lift PF."
            )
        else:
            print(
                f"  SHORT direction outperforms by {-diff:+.1f}p/trade. "
                f"Opposite of carry hypothesis. Either: (a) carry is no longer "
                f"a JPY-funding factor in 2025-26, or (b) trend regimes "
                f"overwhelmed carry in this sample."
            )


if __name__ == "__main__":
    main()
