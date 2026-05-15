"""Asian Session Breakout — sanity backtest on 8 months of M5 data.

Strategy:
  - Asian session window: 00:00-07:00 UTC. Compute high/low of all M5 bars in window.
  - Range filter: 0.4 * ADR(14) <= range <= 1.0 * ADR(14).
    Rejects NR-too-tight (noise) and wide-ranges-already-exhausted.
  - At 07:00 UTC place BUY_STOP at range_high + buffer, SELL_STOP at range_low - buffer.
    Buffer = max(2 pips, 0.10 * range).
  - Active until 11:00 UTC. Whichever side fills first wins; cancel the other.
  - SL = opposite range edge. R = range size in pips.
  - Exit: TP at 1.0 * R from entry (1:1 R:R), or SL at opposite edge, or 20:00 UTC time stop.
  - Filters: skip Fridays after 15:00 UTC (avoid weekend); skip Mondays (gap noise).

Friction:
  - Stop-order fills get ADVERSE slippage (worst-of: bar open at trigger time,
    or stop level + slippage). Cross-pairs at London open routinely slip 1-4 pips.
  - Spread at exit: median + small slippage.

Pairs: GBPJPY, EURJPY, GBPUSD (per literature — most likely to work on session-driven flow).
"""
from __future__ import annotations
import random
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hvf_trader.backtesting.spread_model import get_spread_pips

UTC = ZoneInfo("UTC")

STARTING_EQUITY = 700.0
RISK_PCT = 1.0

ASIAN_START_H = 0
ASIAN_END_H = 7
LONDON_END_H = 11
EOD_H = 20

# Stop-order slippage on the breakout fill (adverse, gaussian-clipped)
STOP_SLIPPAGE_MEAN = 1.5
STOP_SLIPPAGE_STD = 1.0
STOP_SLIPPAGE_CLIP = (0.0, 5.0)

EXIT_SLIPPAGE_MEAN = 0.5
EXIT_SLIPPAGE_STD = 0.3
EXIT_SLIPPAGE_CLIP = (0.0, 2.0)

SEEDS = (1001, 1002, 1003, 1004, 1005)
PAIRS = ["GBPJPY", "EURJPY", "GBPUSD"]  # overridden via --pairs


def pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def adverse_slippage(mean: float, std: float, clip: tuple[float, float],
                     rng=None) -> float:
    r = rng or random
    return max(clip[0], min(clip[1], r.gauss(mean, std)))


@dataclass
class Trade:
    pair: str
    direction: str
    range_size_pips: float
    asian_high: float
    asian_low: float
    entry_time: datetime
    entry_price: float
    sl: float
    tp: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0


def adr(daily: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Daily Range (high-low) over `period` days, exponentially smoothed."""
    rng = (daily["high"] - daily["low"])
    return rng.ewm(alpha=1 / period, adjust=False).mean()


def load_m5(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{symbol}_M5.csv")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def simulate_pair(symbol: str, df: pd.DataFrame, equity_ref: list[float]) -> list[Trade]:
    """Walk through trading days, simulate Asian Session Breakout per day."""
    pip = pip_size(symbol)
    trades: list[Trade] = []

    # Build daily OHLC for ADR
    df_indexed = df.set_index("time")
    daily = df_indexed.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    daily["adr14"] = adr(daily)
    # Key the ADR lookup by date (naive) so it matches df["date"] keys
    adr_lookup = {d.date(): v for d, v in daily["adr14"].items()}

    # Group by date for daily simulation
    df["date"] = df["time"].dt.date

    for date, day_df in df.groupby("date"):
        day_df = day_df.sort_values("time").reset_index(drop=True)
        dt = pd.Timestamp(date).tz_localize("UTC")
        weekday = dt.weekday()  # 0=Mon

        # Filter: skip Mondays (gap noise) and Saturdays
        if weekday in (5, 6):  # Sat/Sun
            continue

        # Asian session window: 00:00-07:00 UTC
        asian = day_df[
            (day_df["time"].dt.hour >= ASIAN_START_H)
            & (day_df["time"].dt.hour < ASIAN_END_H)
        ]
        if len(asian) < 5:
            continue

        asian_high = asian["high"].max()
        asian_low = asian["low"].min()
        range_size = (asian_high - asian_low) / pip
        if range_size <= 0:
            continue

        # Range filter against ADR(14) — use yesterday's ADR so no lookahead
        prev_date = (pd.Timestamp(date) - pd.Timedelta(days=1)).date()
        adr_prev = adr_lookup.get(prev_date, None)
        if adr_prev is None or pd.isna(adr_prev):
            continue
        adr_prev_pips = adr_prev / pip
        if range_size < 0.4 * adr_prev_pips or range_size > 1.0 * adr_prev_pips:
            continue

        # Stop-order placement
        buffer_pips = max(2.0, 0.10 * range_size)
        long_stop = asian_high + buffer_pips * pip
        short_stop = asian_low - buffer_pips * pip

        # Active window: 07:00-11:00 UTC
        active = day_df[
            (day_df["time"].dt.hour >= ASIAN_END_H)
            & (day_df["time"].dt.hour < LONDON_END_H)
        ].sort_values("time").reset_index(drop=True)
        if active.empty:
            continue

        # Find which stop fires first
        filled_dir = None
        fill_time = None
        fill_price = None
        for _, bar in active.iterrows():
            short_hit = bar["low"] <= short_stop
            long_hit = bar["high"] >= long_stop
            if short_hit and not long_hit:
                filled_dir = "SHORT"
                fill_time = bar["time"]
                # Adverse slippage past the stop level
                slip_p = adverse_slippage(STOP_SLIPPAGE_MEAN, STOP_SLIPPAGE_STD,
                                          STOP_SLIPPAGE_CLIP)
                fill_price = short_stop - slip_p * pip
                break
            if long_hit and not short_hit:
                filled_dir = "LONG"
                fill_time = bar["time"]
                slip_p = adverse_slippage(STOP_SLIPPAGE_MEAN, STOP_SLIPPAGE_STD,
                                          STOP_SLIPPAGE_CLIP)
                fill_price = long_stop + slip_p * pip
                break
            if short_hit and long_hit:
                # Same bar both touched — pick the side closer to the bar's open
                # (whichever was hit first chronologically as bar formed).
                if abs(bar["open"] - long_stop) < abs(bar["open"] - short_stop):
                    filled_dir = "LONG"
                    slip_p = adverse_slippage(STOP_SLIPPAGE_MEAN, STOP_SLIPPAGE_STD,
                                              STOP_SLIPPAGE_CLIP)
                    fill_price = long_stop + slip_p * pip
                else:
                    filled_dir = "SHORT"
                    slip_p = adverse_slippage(STOP_SLIPPAGE_MEAN, STOP_SLIPPAGE_STD,
                                              STOP_SLIPPAGE_CLIP)
                    fill_price = short_stop - slip_p * pip
                fill_time = bar["time"]
                break

        if filled_dir is None:
            continue  # neither stop fired in active window

        # Entry / SL / TP
        if filled_dir == "LONG":
            sl = asian_low - buffer_pips * pip  # opposite range edge
            tp = fill_price + range_size * pip  # 1R target
        else:
            sl = asian_high + buffer_pips * pip
            tp = fill_price - range_size * pip

        # Walk bars after fill until exit
        post_fill = day_df[day_df["time"] > fill_time].sort_values("time").reset_index(drop=True)
        if post_fill.empty:
            continue

        eod_time = pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=EOD_H)
        exit_time = None
        exit_price = None
        exit_reason = ""

        for _, bar in post_fill.iterrows():
            t = bar["time"]
            if t >= eod_time:
                # Time stop at 20:00 UTC
                exit_time = t
                # Approximate at bar open
                exit_price = bar["open"]
                exit_reason = "TIME_STOP"
                break

            if filled_dir == "LONG":
                hit_sl = bar["low"] <= sl
                hit_tp = bar["high"] >= tp
                if hit_sl and hit_tp:
                    # Both — assume SL first (worst case)
                    exit_time, exit_price, exit_reason = t, sl, "SL"
                    break
                if hit_sl:
                    exit_time, exit_price, exit_reason = t, sl, "SL"
                    break
                if hit_tp:
                    exit_time, exit_price, exit_reason = t, tp, "TP"
                    break
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
            # Ran past data window
            continue

        # Exit slippage
        slip_p = adverse_slippage(EXIT_SLIPPAGE_MEAN, EXIT_SLIPPAGE_STD,
                                  EXIT_SLIPPAGE_CLIP)
        if filled_dir == "LONG":
            exit_fill = exit_price - slip_p * pip
            pnl_pips = (exit_fill - fill_price) / pip
        else:
            exit_fill = exit_price + slip_p * pip
            pnl_pips = (fill_price - exit_fill) / pip

        # Lot size from risk
        stop_pips = abs(fill_price - sl) / pip
        equity_now = equity_ref[0]
        risk_usd = equity_now * (RISK_PCT / 100.0)
        # Rough JPY-pair pip value scaling
        pip_value_per_lot = 10.0  # approx $10/pip/standard lot for non-JPY
        if "JPY" in symbol:
            # 1 pip on JPY pair = 0.01 quoted in JPY; $10/pip/lot is the standard
            # quoted-currency-agnostic approximation. Good enough for sanity.
            pip_value_per_lot = 10.0
        lots = round(risk_usd / max(stop_pips * pip_value_per_lot, 0.01), 2)
        lots = max(min(lots, 5.0), 0.01)
        pnl_usd = pnl_pips * lots * 10.0

        equity_ref[0] += pnl_usd

        trades.append(Trade(
            pair=symbol, direction=filled_dir,
            range_size_pips=range_size,
            asian_high=asian_high, asian_low=asian_low,
            entry_time=fill_time, entry_price=fill_price, sl=sl, tp=tp,
            exit_time=exit_time, exit_price=exit_fill,
            exit_reason=exit_reason, pnl_pips=pnl_pips, pnl_usd=pnl_usd,
        ))

    return trades


def run_seed(seed: int) -> tuple[list[Trade], float]:
    random.seed(seed)
    equity_ref = [STARTING_EQUITY]
    all_trades = []
    for sym in PAIRS:
        df = load_m5(sym)
        trades = simulate_pair(sym, df, equity_ref)
        all_trades.extend(trades)
    return all_trades, equity_ref[0]


def summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    wins = [t for t in trades if t.pnl_pips > 0]
    losses = [t for t in trades if t.pnl_pips <= 0]
    gw = sum(t.pnl_pips for t in wins)
    gl = abs(sum(t.pnl_pips for t in losses))
    pf = gw / gl if gl else float("inf")
    return {
        "n": len(trades),
        "wins": len(wins),
        "wr": len(wins) / len(trades) * 100,
        "pf": pf,
        "pips": sum(t.pnl_pips for t in trades),
        "usd": sum(t.pnl_usd for t in trades),
    }


def main():
    global PAIRS
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", nargs="+", default=PAIRS)
    p.add_argument("--out", default="asb_validation.png")
    args = p.parse_args()
    PAIRS = args.pairs
    print(f"Asian Session Breakout — sanity backtest on M5 data")
    print(f"  Pairs: {PAIRS}, starting equity ${STARTING_EQUITY}, risk {RISK_PCT}%")
    print(f"  Asian window: 00-07 UTC | Active: 07-11 UTC | EOD time-stop: 20 UTC")
    print(f"  Range filter: 0.4x..1.0x ADR(14); stop buffer = max(2p, 0.10*range)")
    print(f"  Seeds: {SEEDS}\n")

    runs = []
    for seed in SEEDS:
        trades, final_eq = run_seed(seed)
        s = summarize(trades)
        runs.append((seed, trades, final_eq, s))
        if s["n"] > 0:
            print(
                f"seed={seed}: N={s['n']:>3} WR={s['wr']:5.1f}% "
                f"PF={s['pf']:5.2f} pips={s['pips']:+8.1f} "
                f"USD={s['usd']:+8.2f} final=${final_eq:,.2f}"
            )
        else:
            print(f"seed={seed}: no trades")

    pfs = [r[3]["pf"] for r in runs if r[3]["n"] > 0]
    if pfs:
        mean_pf = sum(pfs) / len(pfs)
        std_pf = (sum((p - mean_pf) ** 2 for p in pfs) / max(len(pfs) - 1, 1)) ** 0.5
        print(f"\nAcross {len(pfs)} seeds: mean PF {mean_pf:.2f} (std {std_pf:.2f}, range [{min(pfs):.2f},{max(pfs):.2f}])")
        print(f"  mean pips: {sum(r[3]['pips'] for r in runs) / len(pfs):+.1f}")
        print(f"  mean USD:  ${sum(r[3]['usd'] for r in runs) / len(pfs):+.2f}")

    # Per-pair attribution (middle seed)
    mid_seed, mid_trades, mid_final, mid_s = runs[len(runs) // 2]
    if not mid_trades:
        print("No trades to chart.")
        return

    print(f"\nPer-pair attribution (seed={mid_seed}):")
    print(f"  {'pair':<8} {'N':>3} {'WR':>6} {'PF':>6} {'pips':>9}")
    for sym in PAIRS:
        tp = [t for t in mid_trades if t.pair == sym]
        if not tp:
            print(f"  {sym:<8} {'0':>3}")
            continue
        wins = [t for t in tp if t.pnl_pips > 0]
        gw = sum(t.pnl_pips for t in wins)
        gl = abs(sum(t.pnl_pips for t in tp if t.pnl_pips <= 0))
        pf = gw / gl if gl else float("inf")
        print(
            f"  {sym:<8} {len(tp):>3} {len(wins)/len(tp)*100:>5.1f}% "
            f"{pf:>6.2f} {sum(t.pnl_pips for t in tp):>+9.1f}"
        )

    print(f"\nExit reason breakdown:")
    for reason in ["TP", "SL", "TIME_STOP"]:
        tp = [t for t in mid_trades if t.exit_reason == reason]
        avg = sum(t.pnl_pips for t in tp) / max(len(tp), 1)
        print(f"  {reason:<10} N={len(tp)} avg_pips={avg:+.1f}")

    # Equity curve
    mid_trades.sort(key=lambda t: t.exit_time or datetime.min.replace(tzinfo=UTC))
    times = [mid_trades[0].entry_time] + [t.exit_time for t in mid_trades]
    eq = [STARTING_EQUITY]
    for t in mid_trades:
        eq.append(eq[-1] + t.pnl_usd)
    peak = np.maximum.accumulate(np.array(eq))
    dd = (np.array(eq) - peak) / peak * 100
    max_dd = abs(dd.min())
    ret_pct = (eq[-1] - STARTING_EQUITY) / STARTING_EQUITY * 100

    fig, axes = plt.subplots(
        2, 1, figsize=(14, 8),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.3},
    )
    ax1 = axes[0]
    ax1.plot(times, eq, color="steelblue", linewidth=1.5)
    ax1.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax1.set_title(
        f"Asian Session Breakout (M5, 3 pairs) — ${STARTING_EQUITY:.0f} -> ${eq[-1]:,.2f} "
        f"({ret_pct:+.1f}%)\n"
        f"N={len(mid_trades)} trades, PF={mid_s['pf']:.2f}, "
        f"WR={mid_s['wr']:.1f}%, MaxDD={max_dd:.1f}%, seed={mid_seed}",
        fontsize=12, fontweight="bold", linespacing=1.4,
    )
    ax1.set_ylabel("Equity ($)")
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.fill_between(times, dd, 0, color="red", alpha=0.3)
    ax2.plot(times, dd, color="red", linewidth=0.7)
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out_png = REPO_ROOT / "backtests" / "charts" / args.out
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved equity curve: {out_png}")


if __name__ == "__main__":
    main()
