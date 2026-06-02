"""HVF (Hunt Volatility Funnel) backtest on BTC and ETH.

HVF was the bot's original strategy — disabled on FX after PF 0.06 over
27 live trades. This script tests whether the same detector + scorer
produces edge on crypto, where the compression-then-expansion thesis
should fit better.

Approach:
  1. Load H1 data for BTCUSD and ETHUSD; resample to D1.
  2. Compute ATR(14), EMA(200), ADX(14) — required columns for HVF detector.
  3. Run compute_zigzag → get pivots → detect_hvf_patterns over the
     historical window.
  4. For each detected pattern, simulate the trade forward:
     - Entry: bar after detection where price breaks h3+buffer (LONG) /
       l3-buffer (SHORT).
     - Exit: SL hit, T1 hit (close 50%), T2 hit (close 100%), or 30-day
       time stop.
  5. Walk-forward by 3-year windows + variant: D1 vs H4 timeframe.

Outputs PF/WR/MAR per asset per window.
"""
from __future__ import annotations
import sys
import os
from dataclasses import dataclass
from pathlib import Path

# Suppress noisy detector logs during backtest
import logging
logging.getLogger("hvf_trader").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hvf_trader.detector.hvf_detector import detect_hvf_patterns, HVFPattern
from hvf_trader.detector.zigzag import compute_zigzag
from hvf_trader.detector.pattern_scorer import score_pattern
from hvf_trader import config

STARTING_EQUITY = 10000.0
RISK_PCT = 1.0
PARTIAL_PCT = 0.50      # close 50% at T1, ride 50% to T2 or breakeven
MAX_HOLD_BARS = 30      # 30 D1 bars = ~1 month time-stop
ROUND_TRIP_USD = 12.0   # ~$6 spread per side on BTCUSD; halve for ETH

ASSETS = [
    # (symbol, dollar_per_point_per_lot, round_trip_cost)
    ("BTCUSD", 1.0, 12.0),
    ("ETHUSD", 1.0, 5.0),
]


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add ATR(14), EMA(200), ADX(14) columns required by HVF detector."""
    df = df.copy()
    h, l, c = df["high"], df["low"], df["close"]
    # ATR via Wilder smoothing
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()

    # ADX(14) — Wilder
    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_w = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_w.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_w.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    # tick_volume column expected — fake it from the bar volume
    if "tick_volume" not in df.columns and "volume" in df.columns:
        df["tick_volume"] = df["volume"]
    elif "tick_volume" not in df.columns:
        df["tick_volume"] = 1
    return df


def load_d1(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "tick_volume": "sum" if "tick_volume" in df.columns else "size",
    }).dropna()
    return compute_indicators(d1)


def load_h4(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    h4 = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "tick_volume": "sum" if "tick_volume" in df.columns else "size",
    }).dropna()
    return compute_indicators(h4)


def load_h1(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    df = df.rename(columns={c: c for c in df.columns})  # no-op
    return compute_indicators(df)


@dataclass
class HVFTrade:
    symbol: str
    direction: str
    detect_time: pd.Timestamp
    entry_time: pd.Timestamp | None = None
    entry_price: float = 0.0
    stop: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    score: float = 0.0
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pts: float = 0.0
    pnl_usd: float = 0.0


def simulate_pattern(pattern: HVFPattern, df: pd.DataFrame, symbol: str,
                     dpp: float, rt_cost: float, score: float) -> HVFTrade | None:
    """Walk forward from pattern detection, simulate trade if breakout fires."""
    detect_idx = pattern.l3.index if pattern.direction == "LONG" else pattern.h3.index
    if detect_idx >= len(df) - 1:
        return None

    trade = HVFTrade(
        symbol=symbol, direction=pattern.direction,
        detect_time=df.index[detect_idx], score=score,
        entry_price=pattern.entry_price, stop=pattern.stop_loss,
        t1=pattern.target_1, t2=pattern.target_2,
    )

    # Look for the entry breakout (max 20 bars of "armed" window)
    armed_window = min(detect_idx + 20, len(df))
    entry_idx = None
    for i in range(detect_idx + 1, armed_window):
        bar = df.iloc[i]
        if pattern.direction == "LONG" and bar["high"] >= pattern.entry_price:
            entry_idx = i
            trade.entry_time = df.index[i]
            break
        if pattern.direction == "SHORT" and bar["low"] <= pattern.entry_price:
            entry_idx = i
            trade.entry_time = df.index[i]
            break
    if entry_idx is None:
        return None  # never armed → not a real trade

    # Simulate forward from entry
    initial_stop_dist = abs(trade.entry_price - trade.stop)
    if initial_stop_dist <= 0:
        return None

    partial_taken = False
    eff_pnl_pts = 0.0  # accumulated pip P/L net of partial
    for i in range(entry_idx + 1, min(entry_idx + 1 + MAX_HOLD_BARS, len(df))):
        bar = df.iloc[i]
        if pattern.direction == "LONG":
            if bar["low"] <= trade.stop:
                # Stop hit. If partial taken, the partial portion stays at +T1 pts.
                if partial_taken:
                    eff_pnl_pts += (trade.stop - trade.entry_price) * (1 - PARTIAL_PCT)
                    trade.pnl_pts = eff_pnl_pts
                else:
                    trade.pnl_pts = (trade.stop - trade.entry_price)
                trade.exit_time = df.index[i]
                trade.exit_price = trade.stop
                trade.exit_reason = "STOP" if not partial_taken else "BE_AFTER_PARTIAL"
                break
            if not partial_taken and bar["high"] >= trade.t1:
                # Take partial at T1, move stop to breakeven
                eff_pnl_pts += (trade.t1 - trade.entry_price) * PARTIAL_PCT
                trade.stop = trade.entry_price
                partial_taken = True
            if bar["high"] >= trade.t2:
                if partial_taken:
                    eff_pnl_pts += (trade.t2 - trade.entry_price) * (1 - PARTIAL_PCT)
                else:
                    eff_pnl_pts += (trade.t2 - trade.entry_price)
                trade.pnl_pts = eff_pnl_pts
                trade.exit_time = df.index[i]
                trade.exit_price = trade.t2
                trade.exit_reason = "TP2"
                break
        else:  # SHORT
            if bar["high"] >= trade.stop:
                if partial_taken:
                    eff_pnl_pts += (trade.entry_price - trade.stop) * (1 - PARTIAL_PCT)
                else:
                    eff_pnl_pts += (trade.entry_price - trade.stop)
                trade.pnl_pts = eff_pnl_pts
                trade.exit_time = df.index[i]
                trade.exit_price = trade.stop
                trade.exit_reason = "STOP" if not partial_taken else "BE_AFTER_PARTIAL"
                break
            if not partial_taken and bar["low"] <= trade.t1:
                eff_pnl_pts += (trade.entry_price - trade.t1) * PARTIAL_PCT
                trade.stop = trade.entry_price
                partial_taken = True
            if bar["low"] <= trade.t2:
                if partial_taken:
                    eff_pnl_pts += (trade.entry_price - trade.t2) * (1 - PARTIAL_PCT)
                else:
                    eff_pnl_pts += (trade.entry_price - trade.t2)
                trade.pnl_pts = eff_pnl_pts
                trade.exit_time = df.index[i]
                trade.exit_price = trade.t2
                trade.exit_reason = "TP2"
                break

    if trade.exit_time is None:
        # Time stop
        last_bar = df.iloc[min(entry_idx + MAX_HOLD_BARS, len(df) - 1)]
        if pattern.direction == "LONG":
            remaining_pnl = (last_bar["close"] - trade.entry_price)
        else:
            remaining_pnl = (trade.entry_price - last_bar["close"])
        if partial_taken:
            eff_pnl_pts += remaining_pnl * (1 - PARTIAL_PCT)
            trade.pnl_pts = eff_pnl_pts
        else:
            trade.pnl_pts = remaining_pnl
        trade.exit_time = last_bar.name
        trade.exit_price = last_bar["close"]
        trade.exit_reason = "TIME"

    # Apply friction
    trade.pnl_pts -= rt_cost

    # Lot sizing (1% risk based on initial stop)
    risk_usd = STARTING_EQUITY * RISK_PCT / 100.0
    lots = risk_usd / max(initial_stop_dist * dpp, 0.01)
    lots = max(min(round(lots, 2), 100.0), 0.01)
    trade.pnl_usd = trade.pnl_pts * lots * dpp

    return trade


def run_asset(symbol: str, dpp: float, rt_cost: float,
              start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
              timeframe: str = "D1"):
    if timeframe == "D1":
        d1 = load_d1(symbol)
    elif timeframe == "H4":
        d1 = load_h4(symbol)
    elif timeframe == "H1":
        d1 = load_h1(symbol)
    else:
        raise ValueError(timeframe)
    if start is not None:
        d1 = d1[d1.index >= start]
    if end is not None:
        d1 = d1[d1.index < end]
    if len(d1) < 250:
        return [], 0.0

    # Need ATR + ADX populated; drop initial NaN bars
    d1 = d1.dropna(subset=["atr"])
    if len(d1) < 100:
        return [], 0.0
    d1 = d1.reset_index().rename(columns={"index": "time"})
    if "time" not in d1.columns:  # if index reset gave 't'
        d1 = d1.rename(columns={"t": "time"})

    pivots = compute_zigzag(d1, atr_multiplier=config.ZIGZAG_ATR_MULTIPLIER)
    patterns = detect_hvf_patterns(d1, symbol, timeframe, pivots=pivots)

    trades = []
    for p in patterns:
        try:
            score = score_pattern(p, d1)
        except Exception:
            score = 50.0
        trade = simulate_pattern(p, d1, symbol, dpp, rt_cost, score)
        if trade is not None:
            trades.append(trade)
    trades.sort(key=lambda t: t.entry_time)
    return trades, len(patterns)


def stats(trades):
    if not trades:
        return None
    usd = np.array([t.pnl_usd for t in trades])
    n = len(trades)
    wins = (usd > 0).sum()
    gp = usd[usd > 0].sum()
    gl = abs(usd[usd <= 0].sum())
    pf = gp / gl if gl else float("inf")
    eq = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(usd)])
    dd = np.maximum.accumulate(eq) - eq
    max_dd_pct = (dd.max() / np.maximum.accumulate(eq).max() * 100) if dd.max() > 0 else 0
    avg_win = usd[usd > 0].mean() if wins else 0
    avg_loss = usd[usd <= 0].mean() if (usd <= 0).sum() else 0
    return {
        "n": n, "wr": wins / n * 100, "pf": pf,
        "total": usd.sum(), "dd_pct": max_dd_pct,
        "avg_win": avg_win, "avg_loss": avg_loss,
    }


def main():
    print(f"HVF backtest on crypto — multi-timeframe\n")

    full_results = {}
    for tf in ["D1", "H4", "H1"]:
        print(f"=== Timeframe: {tf} ===")
        for sym, dpp, rt in ASSETS:
            trades, n_patterns = run_asset(sym, dpp, rt, timeframe=tf)
            s = stats(trades)
            if s:
                print(f"  {sym}: patterns={n_patterns:>3}  armed={s['n']:>3}  "
                      f"WR={s['wr']:>4.0f}%  PF={s['pf']:>5.2f}  "
                      f"total=${s['total']:>+,.0f}  DD={s['dd_pct']:>4.1f}%")
                if tf == "D1":
                    full_results[sym] = (trades, s)
            else:
                print(f"  {sym}: {n_patterns} patterns detected, 0 armed/closed")
        print()

    # Walk-forward
    print("=" * 80)
    print("Walk-forward (3-year windows)")
    print("=" * 80)
    windows = [
        ("2017 → 2019",  "2017-01-01", "2020-01-01"),
        ("2020 → 2022",  "2020-01-01", "2023-01-01"),
        ("2023 → 2025",  "2023-01-01", "2026-01-01"),
    ]
    for label, start, end in windows:
        print(f"\n  Window {label}:")
        print(f"  {'Sym':<8} {'N':>4} {'WR':>5} {'PF':>5} {'Total':>9} {'DD':>6}")
        print(f"  {'-'*44}")
        for sym, dpp, rt in ASSETS:
            trades, _ = run_asset(sym, dpp, rt,
                                   start=pd.Timestamp(start, tz="UTC"),
                                   end=pd.Timestamp(end, tz="UTC"))
            s = stats(trades)
            if s:
                print(f"  {sym:<8} {s['n']:>4} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                      f"{s['total']:>+8.0f} {s['dd_pct']:>5.1f}%")
            else:
                print(f"  {sym:<8}    0 armed")

    # Plot equity curves
    if full_results:
        fig, axes = plt.subplots(len(full_results), 1, figsize=(14, 4 * len(full_results)))
        if len(full_results) == 1:
            axes = [axes]
        for ax, (sym, (trades, s)) in zip(axes, full_results.items()):
            times = [trades[0].entry_time] + [t.exit_time for t in trades]
            eq = np.concatenate([[STARTING_EQUITY],
                                  STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
            ax.plot(times, eq, color="steelblue", linewidth=1.5)
            ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
            ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
            ax.set_title(
                f"{sym} — HVF on D1, N={s['n']}, WR {s['wr']:.0f}%, PF {s['pf']:.2f}, "
                f"${STARTING_EQUITY:,.0f}→${STARTING_EQUITY+s['total']:,.2f}, "
                f"DD {s['dd_pct']:.1f}%",
                fontsize=11, fontweight="bold",
            )
            ax.set_ylabel("Equity ($)")
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        out = ROOT / "charts" / "hvf_crypto.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\nChart saved: {out}")


if __name__ == "__main__":
    main()
