"""Cross-pair correlation divergence (statistical arbitrage) backtest.

Strategy:
  - Pick two correlated FX pairs (e.g., EURUSD vs GBPUSD).
  - Compute log-spread = log(P1) - log(P2) on H1 bars.
  - Compute rolling z-score (60-bar lookback by default).
  - Entry: |z| > 2.0 -> trade the spread back toward mean.
    z > +2: SHORT P1, LONG P2 (spread expected to revert down)
    z < -2: LONG P1, SHORT P2 (spread expected to revert up)
  - Exit: |z| crosses zero (full mean reversion) OR
          |z| > 3.5 (stop loss — spread kept diverging) OR
          time stop at 5 days (120 bars).

Friction: each trade has 4 spread costs (entry x 2 legs, exit x 2 legs).
The big test for FX stat-arb is whether the small mean-reversion edge
survives this cost.

Sizing: equal notional per leg. Lot size scaled so each leg = $5k notional
(roughly 0.04-0.05 lots on majors). Risk is implicit — no fixed stop in $
terms, just the z-score stop.

Pairs tested:
  - EURUSD vs GBPUSD (both USD majors, highest correlation)
  - EURJPY vs GBPJPY (both JPY crosses)
  - GBPCHF vs GBPCAD (both GBP crosses, less common)
"""
from __future__ import annotations
import random
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hvf_trader.backtesting.spread_model import get_spread_pips, apply_slippage_pips


STARTING_EQUITY = 700.0
NOTIONAL_PER_LEG = 5000.0  # $5k per leg, so total trade exposure = $10k

# Strategy params (defaults — tuneable)
LOOKBACK = 60          # rolling window for z-score (bars)
ENTRY_Z = 2.0          # |z| threshold to enter
EXIT_Z = 0.0           # z threshold to exit (mean reversion target)
STOP_Z = 3.5           # |z| threshold to stop out (divergence kept going)
TIME_STOP_BARS = 120   # 5 days * 24 H1 bars

EXIT_SLIPPAGE_MEAN = 0.5
EXIT_SLIPPAGE_STD = 0.3
EXIT_SLIPPAGE_CLIP = (0.0, 2.0)
SEEDS = (1001, 1002, 1003, 1004, 1005)

# Test these pairs (GBPCHF/GBPCAD H1 CSV uses sequential index not unix
# timestamp — skipped for now).
TEST_PAIRS = [
    ("EURUSD", "GBPUSD"),
    ("EURJPY", "GBPJPY"),
]


def pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def load_h1(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{symbol}_H1.csv")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["time", "open", "high", "low", "close"]]


def align_pair(df1: pd.DataFrame, df2: pd.DataFrame) -> pd.DataFrame:
    """Inner-join on time."""
    d1 = df1.rename(columns={c: f"{c}_1" for c in df1.columns if c != "time"})
    d2 = df2.rename(columns={c: f"{c}_2" for c in df2.columns if c != "time"})
    return pd.merge(d1, d2, on="time", how="inner").sort_values("time").reset_index(drop=True)


def compute_spread_zscore(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    df = df.copy()
    df["spread"] = np.log(df["close_1"]) - np.log(df["close_2"])
    df["spread_mean"] = df["spread"].rolling(lookback).mean()
    df["spread_std"] = df["spread"].rolling(lookback).std()
    df["zscore"] = (df["spread"] - df["spread_mean"]) / df["spread_std"]
    return df


@dataclass
class ArbTrade:
    pair1: str
    pair2: str
    direction: str  # LONG_SPREAD (long P1, short P2) or SHORT_SPREAD
    entry_time: pd.Timestamp
    entry_z: float
    entry_p1: float
    entry_p2: float
    exit_time: pd.Timestamp = None
    exit_z: float = 0.0
    exit_p1: float = 0.0
    exit_p2: float = 0.0
    exit_reason: str = ""
    pnl_p1_pips: float = 0.0  # leg-1 pips (correct sign for direction)
    pnl_p2_pips: float = 0.0
    pnl_usd: float = 0.0


def adverse_slip(rng=None) -> float:
    r = rng or random
    return max(EXIT_SLIPPAGE_CLIP[0],
               min(EXIT_SLIPPAGE_CLIP[1],
                   r.gauss(EXIT_SLIPPAGE_MEAN, EXIT_SLIPPAGE_STD)))


def simulate(pair1: str, pair2: str, df: pd.DataFrame) -> list[ArbTrade]:
    """Walk the merged dataframe and simulate stat-arb trades."""
    df = compute_spread_zscore(df, LOOKBACK)
    df = df.dropna(subset=["zscore"]).reset_index(drop=True)
    pip1 = pip_size(pair1)
    pip2 = pip_size(pair2)
    trades: list[ArbTrade] = []
    pos: ArbTrade | None = None
    entry_bar_idx: int | None = None

    for i in range(len(df) - 1):
        bar = df.iloc[i]
        nxt = df.iloc[i + 1]
        z = bar["zscore"]
        if pd.isna(z):
            continue

        # In-position: check exit
        if pos is not None:
            should_exit = False
            reason = ""
            if pos.direction == "LONG_SPREAD":
                # Entered at z < 0; exit when z >= EXIT_Z (mean reversion)
                if z >= EXIT_Z:
                    should_exit, reason = True, "MEAN_REV"
                elif z <= -STOP_Z:
                    should_exit, reason = True, "STOP"
            else:
                # SHORT_SPREAD: entered at z > 0; exit when z <= EXIT_Z
                if z <= EXIT_Z:
                    should_exit, reason = True, "MEAN_REV"
                elif z >= STOP_Z:
                    should_exit, reason = True, "STOP"
            if not should_exit and i - entry_bar_idx >= TIME_STOP_BARS:
                should_exit, reason = True, "TIME_STOP"

            if should_exit:
                # Exit at next bar's open with adverse slippage on each leg
                exit_p1 = nxt["open_1"]
                exit_p2 = nxt["open_2"]
                spread1 = get_spread_pips(pair1, nxt["time"].hour) * pip1
                spread2 = get_spread_pips(pair2, nxt["time"].hour) * pip2
                slip1 = adverse_slip() * pip1
                slip2 = adverse_slip() * pip2

                # LONG_SPREAD = long P1, short P2. Exit: sell P1 (at bid), buy P2 (at ask).
                # Loss side: subtract half-spread + slippage from P1 sell, add to P2 buy.
                if pos.direction == "LONG_SPREAD":
                    fill_p1 = exit_p1 - spread1 / 2 - slip1  # sell P1
                    fill_p2 = exit_p2 + spread2 / 2 + slip2  # cover P2 short = buy
                    pos.pnl_p1_pips = (fill_p1 - pos.entry_p1) / pip1
                    pos.pnl_p2_pips = (pos.entry_p2 - fill_p2) / pip2  # short P2
                else:
                    fill_p1 = exit_p1 + spread1 / 2 + slip1  # cover P1 short = buy
                    fill_p2 = exit_p2 - spread2 / 2 - slip2  # sell P2
                    pos.pnl_p1_pips = (pos.entry_p1 - fill_p1) / pip1
                    pos.pnl_p2_pips = (fill_p2 - pos.entry_p2) / pip2

                # USD PnL: each pip on $10k notional ≈ $1 per pip for non-JPY,
                # $0.66-0.85 for JPY. Approximate as: leg_notional * pip_pct.
                # pip_pct = pip / entry_price.
                p1_dollar_per_pip = (NOTIONAL_PER_LEG * pip1) / pos.entry_p1
                p2_dollar_per_pip = (NOTIONAL_PER_LEG * pip2) / pos.entry_p2
                pos.pnl_usd = (pos.pnl_p1_pips * p1_dollar_per_pip
                               + pos.pnl_p2_pips * p2_dollar_per_pip)
                pos.exit_time = nxt["time"]
                pos.exit_z = z
                pos.exit_p1 = fill_p1
                pos.exit_p2 = fill_p2
                pos.exit_reason = reason
                trades.append(pos)
                pos = None
                entry_bar_idx = None
                continue

        # Out of position: check entry
        if pos is None and not pd.isna(z):
            if z <= -ENTRY_Z:
                # Spread cheap — LONG spread (long P1, short P2)
                entry_p1 = nxt["open_1"]
                entry_p2 = nxt["open_2"]
                spread1 = get_spread_pips(pair1, nxt["time"].hour) * pip1
                spread2 = get_spread_pips(pair2, nxt["time"].hour) * pip2
                slip1 = adverse_slip() * pip1
                slip2 = adverse_slip() * pip2
                fill_p1 = entry_p1 + spread1 / 2 + slip1  # buy P1
                fill_p2 = entry_p2 - spread2 / 2 - slip2  # sell P2 (short)
                pos = ArbTrade(
                    pair1=pair1, pair2=pair2, direction="LONG_SPREAD",
                    entry_time=nxt["time"], entry_z=z,
                    entry_p1=fill_p1, entry_p2=fill_p2,
                )
                entry_bar_idx = i + 1
            elif z >= ENTRY_Z:
                # Spread expensive — SHORT spread (short P1, long P2)
                entry_p1 = nxt["open_1"]
                entry_p2 = nxt["open_2"]
                spread1 = get_spread_pips(pair1, nxt["time"].hour) * pip1
                spread2 = get_spread_pips(pair2, nxt["time"].hour) * pip2
                slip1 = adverse_slip() * pip1
                slip2 = adverse_slip() * pip2
                fill_p1 = entry_p1 - spread1 / 2 - slip1  # sell P1 (short)
                fill_p2 = entry_p2 + spread2 / 2 + slip2  # buy P2
                pos = ArbTrade(
                    pair1=pair1, pair2=pair2, direction="SHORT_SPREAD",
                    entry_time=nxt["time"], entry_z=z,
                    entry_p1=fill_p1, entry_p2=fill_p2,
                )
                entry_bar_idx = i + 1

    return trades


def summarize(trades: list[ArbTrade], label: str) -> dict:
    if not trades:
        return {"label": label, "n": 0}
    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    gw = sum(t.pnl_usd for t in wins)
    gl = abs(sum(t.pnl_usd for t in losses))
    pf = gw / gl if gl else float("inf")
    return {
        "label": label,
        "n": len(trades),
        "wr": len(wins) / len(trades) * 100,
        "pf": pf,
        "usd": sum(t.pnl_usd for t in trades),
    }


def correlation(df: pd.DataFrame) -> float:
    return df["close_1"].pct_change().corr(df["close_2"].pct_change())


def main():
    print("Cross-pair correlation divergence backtest")
    print(f"  z-entry={ENTRY_Z}, z-exit={EXIT_Z}, z-stop={STOP_Z}, lookback={LOOKBACK} bars (H1)")
    print(f"  Notional per leg: ${NOTIONAL_PER_LEG}, starting equity ${STARTING_EQUITY}\n")

    all_results = {}
    all_trades_global = []

    for pair1, pair2 in TEST_PAIRS:
        print("=" * 70)
        print(f"PAIR: {pair1} vs {pair2}")
        print("=" * 70)
        d1 = load_h1(pair1)
        d2 = load_h1(pair2)
        merged = align_pair(d1, d2)
        if len(merged) < LOOKBACK + 100:
            print(f"  insufficient overlap ({len(merged)} bars)")
            continue
        corr = correlation(merged)
        print(f"  Overlap: {len(merged)} H1 bars ({merged['time'].iloc[0].date()} to {merged['time'].iloc[-1].date()})")
        print(f"  Return correlation: {corr:.3f}")
        if corr < 0.3:
            print("  WARNING: low correlation. Stat-arb is risky here.")

        seed_results = []
        for seed in SEEDS:
            random.seed(seed)
            trades = simulate(pair1, pair2, merged)
            s = summarize(trades, f"seed_{seed}")
            seed_results.append((seed, trades, s))
            if s["n"] > 0:
                print(f"  seed={seed}: N={s['n']:>3} WR={s['wr']:5.1f}% PF={s['pf']:5.2f} USD={s['usd']:+8.2f}")
            else:
                print(f"  seed={seed}: 0 trades")

        # Use middle seed for the breakdown chart
        mid_seed, mid_trades, mid_s = seed_results[len(seed_results) // 2]
        if mid_s["n"] > 0:
            pfs = [r[2]["pf"] for r in seed_results if r[2]["n"] > 0]
            usds = [r[2]["usd"] for r in seed_results if r[2]["n"] > 0]
            print(f"  mean PF across seeds: {sum(pfs)/len(pfs):.2f}  mean USD: ${sum(usds)/len(usds):+.2f}")
            # Exit reason breakdown
            for reason in ("MEAN_REV", "STOP", "TIME_STOP"):
                rt = [t for t in mid_trades if t.exit_reason == reason]
                if rt:
                    avg_usd = sum(t.pnl_usd for t in rt) / len(rt)
                    print(f"    {reason:<10} N={len(rt)} avg_USD={avg_usd:+.2f}")

        all_results[(pair1, pair2)] = seed_results
        all_trades_global.append((pair1, pair2, mid_trades, mid_s))
        print()

    # Build a 3-panel chart, one per pair
    fig, axes = plt.subplots(
        len(TEST_PAIRS), 1, figsize=(14, 4 * len(TEST_PAIRS)),
        gridspec_kw={"hspace": 0.4},
    )
    if len(TEST_PAIRS) == 1:
        axes = [axes]

    for i, (pair1, pair2, trades, s) in enumerate(all_trades_global):
        ax = axes[i]
        if s["n"] == 0:
            ax.text(0.5, 0.5, "no trades", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(f"{pair1} vs {pair2}: no trades")
            continue
        # Equity curve from sorted trade exits
        sorted_t = sorted(trades, key=lambda t: t.exit_time)
        times = [sorted_t[0].entry_time]
        eq = [STARTING_EQUITY]
        for t in sorted_t:
            eq.append(eq[-1] + t.pnl_usd)
            times.append(t.exit_time)
        eq_arr = np.array(eq)
        peak = np.maximum.accumulate(eq_arr)
        dd = (eq_arr - peak) / peak * 100
        max_dd = abs(dd.min())
        ret_pct = (eq[-1] - STARTING_EQUITY) / STARTING_EQUITY * 100
        ax.plot(times, eq, color="steelblue", linewidth=1.4)
        ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        ax.set_title(
            f"{pair1} vs {pair2} stat-arb — N={s['n']}, PF={s['pf']:.2f}, "
            f"USD ${eq[-1]:.2f} ({ret_pct:+.1f}%), MaxDD {max_dd:.1f}%",
            fontsize=11, fontweight="bold",
        )
        ax.set_ylabel("Equity ($)")
        ax.grid(True, alpha=0.3)

    out = REPO_ROOT / "backtests" / "charts" / "pair_arb.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved chart: {out}")


if __name__ == "__main__":
    main()
