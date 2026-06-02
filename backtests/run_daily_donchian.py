"""Daily Donchian breakout backtest (Turtle System 1, simplified).

Strategy:
  - Entry: D1 close breaks the prior 20-day rolling extreme (high for LONG,
    low for SHORT). Close-based, not intraday touch, to avoid whipsaw on
    fakeouts.
  - Initial stop: 2 * ATR(20) from entry (Turtle's "2N" — wider than the
    breakout level itself; lets the trade breathe).
  - Trailing stop: prior 10-day opposite extreme, updated each new D1 close.
  - Exit: stop hit, OR opposite-direction breakout (flips position).
  - Sizing: 1% account risk per trade based on stop distance.
  - Friction: spread 1.5p entry + 1.5p exit + 1p slippage = ~4p round trip
    on majors (3-4 pips on a 200-500p stop is negligible — the design
    intent of slower strategies).
  - One position max per pair; no pyramiding (Turtle's "add at 0.5N" omitted
    for first-cut clarity).

Tests on 8 years of H1 data resampled to D1 across 7 pairs.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent

PAIRS = ["EURUSD", "GBPUSD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]

# Donchian + ATR params
ENTRY_LOOKBACK = 20      # 20-day breakout
EXIT_LOOKBACK = 10       # 10-day trailing
ATR_PERIOD = 20
ATR_STOP_MULT = 2.0      # Turtle's "2N" initial stop

# Sizing + friction
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0
SPREAD_PIPS = 1.5
SLIP_PIPS = 1.0
ROUND_TRIP_PIPS = 2 * SPREAD_PIPS + SLIP_PIPS  # ~4p on majors


def pip(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def pip_value_per_lot(symbol: str) -> float:
    """Approximate $/pip per standard lot for a USD account.
    Good enough for relative comparison across pairs."""
    if symbol == "EURUSD" or symbol == "GBPUSD" or symbol == "NZDUSD" or symbol == "AUDUSD":
        return 10.0
    if symbol == "USDCHF":
        return 11.5  # ~rate-dependent, use mid
    if symbol == "EURGBP":
        return 13.5
    if "JPY" in symbol:
        return 6.7  # ~rate-dependent; current ~150
    return 10.0


def load_d1(symbol: str) -> pd.DataFrame:
    """Resample H1 → D1 (Mon-Fri only)."""
    df = pd.read_csv(ROOT / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    d1 = d1[d1.index.weekday < 5]  # drop weekends
    return d1


@dataclass
class Trade:
    pair: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    initial_stop_pips: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(symbol: str, d1: pd.DataFrame, equity_ref: list[float]) -> list[Trade]:
    p = pip(symbol)
    pvl = pip_value_per_lot(symbol)
    # Rolling extremes (excluding today, so shift(1))
    d1["entry_high"] = d1["high"].rolling(ENTRY_LOOKBACK).max().shift(1)
    d1["entry_low"] = d1["low"].rolling(ENTRY_LOOKBACK).min().shift(1)
    d1["exit_high"] = d1["high"].rolling(EXIT_LOOKBACK).max().shift(1)
    d1["exit_low"] = d1["low"].rolling(EXIT_LOOKBACK).min().shift(1)
    d1["atr"] = compute_atr(d1, ATR_PERIOD).shift(1)

    trades: list[Trade] = []
    open_trade: Trade | None = None
    for t, row in d1.iterrows():
        if pd.isna(row["entry_high"]) or pd.isna(row["atr"]):
            continue

        # Manage open trade first (check stop on this bar's high/low)
        if open_trade is not None:
            if open_trade.direction == "LONG":
                # Stop check — use bar low; assume gap-through fills at open
                if row["low"] <= open_trade.stop:
                    exit_price = min(row["open"], open_trade.stop)  # gap protection
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.exit_reason = "STOP"
                    raw_pips = (exit_price - open_trade.entry_price) / p
                    open_trade.pnl_pips = raw_pips - ROUND_TRIP_PIPS
                else:
                    # Trail stop up to prior 10-day low if higher
                    new_stop = max(open_trade.stop, row["exit_low"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop
            else:  # SHORT
                if row["high"] >= open_trade.stop:
                    exit_price = max(row["open"], open_trade.stop)
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.exit_reason = "STOP"
                    raw_pips = (open_trade.entry_price - exit_price) / p
                    open_trade.pnl_pips = raw_pips - ROUND_TRIP_PIPS
                else:
                    new_stop = min(open_trade.stop, row["exit_high"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop

            if open_trade.exit_reason:
                # Realize PnL and close
                lots = (equity_ref[0] * RISK_PCT / 100.0) / max(open_trade.initial_stop_pips * pvl, 0.01)
                lots = max(min(round(lots, 2), 50.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pips * lots * pvl
                equity_ref[0] += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        # Look for new entry (only if flat)
        if open_trade is None:
            atr = row["atr"]
            # LONG breakout — close > 20-day high
            if row["close"] > row["entry_high"]:
                entry_price = row["close"] + SLIP_PIPS * p
                initial_stop = entry_price - ATR_STOP_MULT * atr
                stop_pips = (entry_price - initial_stop) / p
                open_trade = Trade(
                    pair=symbol, direction="LONG",
                    entry_time=t, entry_price=entry_price,
                    stop=initial_stop, initial_stop_pips=stop_pips,
                )
            # SHORT breakout — close < 20-day low
            elif row["close"] < row["entry_low"]:
                entry_price = row["close"] - SLIP_PIPS * p
                initial_stop = entry_price + ATR_STOP_MULT * atr
                stop_pips = (initial_stop - entry_price) / p
                open_trade = Trade(
                    pair=symbol, direction="SHORT",
                    entry_time=t, entry_price=entry_price,
                    stop=initial_stop, initial_stop_pips=stop_pips,
                )

    # Close any still-open at end (mark-to-market at last close)
    if open_trade is not None:
        last_row = d1.iloc[-1]
        if open_trade.direction == "LONG":
            raw = (last_row["close"] - open_trade.entry_price) / p
        else:
            raw = (open_trade.entry_price - last_row["close"]) / p
        open_trade.exit_time = last_row.name
        open_trade.exit_price = last_row["close"]
        open_trade.exit_reason = "OPEN_END"
        open_trade.pnl_pips = raw - ROUND_TRIP_PIPS
        lots = (equity_ref[0] * RISK_PCT / 100.0) / max(open_trade.initial_stop_pips * pvl, 0.01)
        lots = max(min(round(lots, 2), 50.0), 0.01)
        open_trade.pnl_usd = open_trade.pnl_pips * lots * pvl
        equity_ref[0] += open_trade.pnl_usd
        trades.append(open_trade)

    return trades


def stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    pnls_pips = np.array([t.pnl_pips for t in trades])
    pnls_usd = np.array([t.pnl_usd for t in trades])
    n = len(trades)
    wins = (pnls_pips > 0).sum()
    losses = (pnls_pips <= 0).sum()
    gp = pnls_pips[pnls_pips > 0].sum()
    gl = abs(pnls_pips[pnls_pips <= 0].sum())
    pf = gp / gl if gl else float("inf")
    avg_win = pnls_pips[pnls_pips > 0].mean() if wins else 0
    avg_loss = pnls_pips[pnls_pips <= 0].mean() if losses else 0
    return {
        "n": n,
        "wr": wins / n * 100,
        "pf": pf,
        "pips": pnls_pips.sum(),
        "usd": pnls_usd.sum(),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "r_multiple": abs(avg_win / avg_loss) if avg_loss else 0,
    }


def main():
    print(f"Daily Donchian {ENTRY_LOOKBACK}/{EXIT_LOOKBACK} backtest — Turtle System 1 (simplified)")
    print(f"  Pairs: {PAIRS}")
    print(f"  Initial stop: {ATR_STOP_MULT}x ATR({ATR_PERIOD})")
    print(f"  Risk: {RISK_PCT}% per trade, starting equity ${STARTING_EQUITY:,.0f}")
    print(f"  Friction: {ROUND_TRIP_PIPS}p round-trip per trade\n")

    all_trades: dict[str, list[Trade]] = {}
    equity_ref = [STARTING_EQUITY]
    for sym in PAIRS:
        d1 = load_d1(sym)
        trades = simulate(sym, d1, equity_ref)
        all_trades[sym] = trades
        s = stats(trades)
        if s["n"] > 0:
            print(
                f"  {sym}: N={s['n']:>3} WR={s['wr']:5.1f}% PF={s['pf']:5.2f} "
                f"pips={s['pips']:+8.0f} USD={s['usd']:+9.2f} "
                f"avg_win={s['avg_win']:+5.0f}p avg_loss={s['avg_loss']:+5.0f}p "
                f"R={s['r_multiple']:.2f}"
            )
        else:
            print(f"  {sym}: 0 trades")

    # Combined portfolio
    combined = [t for ts in all_trades.values() for t in ts]
    combined.sort(key=lambda t: t.exit_time)
    s_all = stats(combined)
    final_eq = equity_ref[0]
    ret = (final_eq / STARTING_EQUITY - 1) * 100
    pnls = np.array([t.pnl_usd for t in combined])
    eq = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(pnls)])
    dd = np.maximum.accumulate(eq) - eq
    max_dd = dd.max()
    max_dd_pct = (max_dd / np.maximum.accumulate(eq).max()) * 100
    years = (combined[-1].exit_time - combined[0].entry_time).days / 365.25
    cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0

    print()
    print(f"=== PORTFOLIO (all {len(PAIRS)} pairs combined) ===")
    print(f"  Trades: {s_all['n']}  WR: {s_all['wr']:.1f}%  PF: {s_all['pf']:.2f}")
    print(f"  Total pips: {s_all['pips']:+,.0f}")
    print(f"  Starting equity: ${STARTING_EQUITY:,.2f}")
    print(f"  Final equity:    ${final_eq:,.2f}")
    print(f"  Return:          {ret:+.1f}%   ({years:.1f} years)")
    print(f"  CAGR:            {cagr:+.2f}%")
    print(f"  Max DD:          ${max_dd:,.2f} ({max_dd_pct:.1f}%)")
    print(f"  MAR:             {(cagr / max_dd_pct):.2f}" if max_dd_pct > 0 else "  MAR: inf")
    print(f"  Avg win:  {s_all['avg_win']:+.0f}p   Avg loss: {s_all['avg_loss']:+.0f}p   R: {s_all['r_multiple']:.2f}")

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(14, 9),
                              gridspec_kw={"height_ratios": [3, 1], "hspace": 0.3})
    ax1 = axes[0]
    times = [combined[0].entry_time] + [t.exit_time for t in combined]
    ax1.plot(times, eq, color="steelblue", linewidth=1.5)
    ax1.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax1.set_title(
        f"Daily Donchian 20/10 — {len(PAIRS)} pairs, {years:.1f} years\n"
        f"${STARTING_EQUITY:,.0f} → ${final_eq:,.2f}  ({ret:+.1f}%, CAGR {cagr:+.1f}%, "
        f"PF {s_all['pf']:.2f}, MAR {(cagr / max_dd_pct):.2f}, DD {max_dd_pct:.1f}%)",
        fontsize=12, fontweight="bold", linespacing=1.4,
    )
    ax1.set_ylabel("Equity ($)")
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    dd_pct = -dd / np.maximum.accumulate(eq) * 100
    ax2.fill_between(times, dd_pct, 0, color="red", alpha=0.3)
    ax2.plot(times, dd_pct, color="red", linewidth=0.7)
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out = ROOT / "charts" / "daily_donchian.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved chart: {out}")


if __name__ == "__main__":
    main()
