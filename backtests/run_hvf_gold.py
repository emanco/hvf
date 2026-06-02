"""HVF (Hunt Volatility Funnel) backtest on gold and silver.

The natural habitat for HVF per Francis Hunt's original work. Tests
XAUUSD (28 years of H1 data) and XAGUSD (24 years) across D1, H4, and
H1 timeframes, with walk-forward windows.

Asset config (IC Markets):
  XAUUSD: contract=100 oz, point=0.01, tick_value=$1. So 1 lot = $100 per $1 move.
  XAGUSD: contract=1000 oz, point=0.001, tick_value=$1. 1 lot = $1000 per $1 move.
  Spread: 20 points = $0.20 round-trip price = $20 per lot.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path

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
PARTIAL_PCT = 0.50
MAX_HOLD_BARS = 30
SCORE_THRESHOLD = 50.0

# (symbol, dollar_per_unit_of_price_per_lot, round_trip_cost_in_price, vol_min)
ASSETS = [
    ("XAUUSD", 100.0, 0.40, 0.01),   # gold: 1 lot = 100 oz, ~$0.40 spread at 20p
    ("XAGUSD", 1000.0, 0.04, 0.01),  # silver: 1 lot = 1000 oz, ~$0.04 spread at 40p
]


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()
    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_w = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_w.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_w.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    if "tick_volume" not in df.columns and "volume" in df.columns:
        df["tick_volume"] = df["volume"]
    elif "tick_volume" not in df.columns:
        df["tick_volume"] = 1
    return df


def load_tf(symbol: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    if tf == "H1":
        return compute_indicators(df)
    rule = {"D1": "1D", "H4": "4h", "H8": "8h", "W1": "1W"}[tf]
    res = df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "tick_volume": "sum" if "tick_volume" in df.columns else "size",
    }).dropna()
    return compute_indicators(res)


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
    detect_idx = pattern.l3.index if pattern.direction == "LONG" else pattern.h3.index
    if detect_idx >= len(df) - 1:
        return None

    trade = HVFTrade(
        symbol=symbol, direction=pattern.direction,
        detect_time=df.index[detect_idx], score=score,
        entry_price=pattern.entry_price, stop=pattern.stop_loss,
        t1=pattern.target_1, t2=pattern.target_2,
    )

    armed_window = min(detect_idx + 20, len(df))
    entry_idx = None
    for i in range(detect_idx + 1, armed_window):
        bar = df.iloc[i]
        if pattern.direction == "LONG" and bar["high"] >= pattern.entry_price:
            entry_idx = i; trade.entry_time = df.index[i]; break
        if pattern.direction == "SHORT" and bar["low"] <= pattern.entry_price:
            entry_idx = i; trade.entry_time = df.index[i]; break
    if entry_idx is None:
        return None

    initial_stop_dist = abs(trade.entry_price - trade.stop)
    if initial_stop_dist <= 0:
        return None

    partial_taken = False
    eff_pnl_pts = 0.0
    for i in range(entry_idx + 1, min(entry_idx + 1 + MAX_HOLD_BARS, len(df))):
        bar = df.iloc[i]
        if pattern.direction == "LONG":
            if bar["low"] <= trade.stop:
                if partial_taken:
                    eff_pnl_pts += (trade.stop - trade.entry_price) * (1 - PARTIAL_PCT)
                    trade.pnl_pts = eff_pnl_pts
                else:
                    trade.pnl_pts = trade.stop - trade.entry_price
                trade.exit_time = df.index[i]; trade.exit_price = trade.stop
                trade.exit_reason = "STOP" if not partial_taken else "BE"
                break
            if not partial_taken and bar["high"] >= trade.t1:
                eff_pnl_pts += (trade.t1 - trade.entry_price) * PARTIAL_PCT
                trade.stop = trade.entry_price
                partial_taken = True
            if bar["high"] >= trade.t2:
                if partial_taken:
                    eff_pnl_pts += (trade.t2 - trade.entry_price) * (1 - PARTIAL_PCT)
                else:
                    eff_pnl_pts += (trade.t2 - trade.entry_price)
                trade.pnl_pts = eff_pnl_pts
                trade.exit_time = df.index[i]; trade.exit_price = trade.t2
                trade.exit_reason = "TP2"
                break
        else:
            if bar["high"] >= trade.stop:
                if partial_taken:
                    eff_pnl_pts += (trade.entry_price - trade.stop) * (1 - PARTIAL_PCT)
                else:
                    eff_pnl_pts += (trade.entry_price - trade.stop)
                trade.pnl_pts = eff_pnl_pts
                trade.exit_time = df.index[i]; trade.exit_price = trade.stop
                trade.exit_reason = "STOP" if not partial_taken else "BE"
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
                trade.exit_time = df.index[i]; trade.exit_price = trade.t2
                trade.exit_reason = "TP2"
                break

    if trade.exit_time is None:
        last_bar = df.iloc[min(entry_idx + MAX_HOLD_BARS, len(df) - 1)]
        if pattern.direction == "LONG":
            remaining_pnl = last_bar["close"] - trade.entry_price
        else:
            remaining_pnl = trade.entry_price - last_bar["close"]
        if partial_taken:
            eff_pnl_pts += remaining_pnl * (1 - PARTIAL_PCT)
            trade.pnl_pts = eff_pnl_pts
        else:
            trade.pnl_pts = remaining_pnl
        trade.exit_time = last_bar.name; trade.exit_price = last_bar["close"]
        trade.exit_reason = "TIME"

    trade.pnl_pts -= rt_cost
    risk_usd = STARTING_EQUITY * RISK_PCT / 100.0
    lots = risk_usd / max(initial_stop_dist * dpp, 0.01)
    lots = max(min(round(lots, 2), 100.0), 0.01)
    trade.pnl_usd = trade.pnl_pts * lots * dpp
    return trade


def run_asset(symbol: str, dpp: float, rt_cost: float, timeframe: str,
              start=None, end=None, score_min: float = 0):
    df = load_tf(symbol, timeframe)
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index < end]
    if len(df) < 250:
        return [], 0, 0
    df = df.dropna(subset=["atr"]).reset_index().rename(columns={"index": "time"})
    if "time" not in df.columns:
        df = df.rename(columns={"t": "time"})

    pivots = compute_zigzag(df, atr_multiplier=config.ZIGZAG_ATR_MULTIPLIER)
    patterns = detect_hvf_patterns(df, symbol, timeframe, pivots=pivots)

    trades = []
    scored = 0
    for p in patterns:
        try:
            s = score_pattern(p, df)
        except Exception:
            s = 50.0
        if s < score_min:
            continue
        scored += 1
        t = simulate_pattern(p, df, symbol, dpp, rt_cost, s)
        if t is not None:
            trades.append(t)
    trades.sort(key=lambda t: t.entry_time)
    return trades, len(patterns), scored


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
    dd_pct = ((np.maximum.accumulate(eq) - eq).max() /
              np.maximum.accumulate(eq).max() * 100) if len(eq) > 1 else 0
    avg_win = usd[usd > 0].mean() if wins else 0
    avg_loss = usd[usd <= 0].mean() if (usd <= 0).sum() else 0
    return {"n": n, "wr": wins/n*100, "pf": pf, "total": usd.sum(),
            "dd_pct": dd_pct, "avg_win": avg_win, "avg_loss": avg_loss}


def main():
    print(f"HVF backtest on gold/silver — multi-timeframe\n")

    full_results_d1 = {}
    for tf in ["D1", "H4", "H1"]:
        print(f"=== Timeframe {tf} (all patterns, no score filter) ===")
        for sym, dpp, rt, vmin in ASSETS:
            trades, n_pat, n_scored = run_asset(sym, dpp, rt, tf)
            s = stats(trades)
            if s:
                print(f"  {sym}: patterns={n_pat:>4} armed={s['n']:>3} "
                      f"WR={s['wr']:>4.0f}% PF={s['pf']:>5.2f} "
                      f"total=${s['total']:>+,.0f} DD={s['dd_pct']:>4.1f}% "
                      f"avg_win=${s['avg_win']:>+,.0f} avg_loss=${s['avg_loss']:>+,.0f}")
                if tf == "D1":
                    full_results_d1[sym] = (trades, s)
            else:
                print(f"  {sym}: patterns={n_pat} → 0 armed")
        print()

    print("=" * 80)
    print("Walk-forward on D1 (where patterns fire most often)")
    print("=" * 80)
    windows = [
        ("1999 → 2004",  "1999-01-01", "2005-01-01"),
        ("2005 → 2009",  "2005-01-01", "2010-01-01"),
        ("2010 → 2014",  "2010-01-01", "2015-01-01"),
        ("2015 → 2019",  "2015-01-01", "2020-01-01"),
        ("2020 → 2025",  "2020-01-01", "2026-01-01"),
    ]
    for label, start, end in windows:
        print(f"\n  Window {label}:")
        print(f"  {'Sym':<8} {'pat':>4} {'N':>3} {'WR':>5} {'PF':>5} {'Total':>9} {'DD':>6}")
        for sym, dpp, rt, vmin in ASSETS:
            trades, n_pat, _ = run_asset(sym, dpp, rt, "D1",
                                         start=pd.Timestamp(start, tz="UTC"),
                                         end=pd.Timestamp(end, tz="UTC"))
            s = stats(trades)
            if s:
                print(f"  {sym:<8} {n_pat:>4} {s['n']:>3} {s['wr']:>4.0f}% "
                      f"{s['pf']:>5.2f} {s['total']:>+8.0f} {s['dd_pct']:>5.1f}%")
            else:
                print(f"  {sym:<8} {n_pat:>4} 0 armed")

    if full_results_d1:
        fig, axes = plt.subplots(len(full_results_d1), 1, figsize=(14, 4 * len(full_results_d1)))
        if len(full_results_d1) == 1:
            axes = [axes]
        for ax, (sym, (trades, s)) in zip(axes, full_results_d1.items()):
            if not trades:
                continue
            times = [trades[0].entry_time] + [t.exit_time for t in trades]
            eq = np.concatenate([[STARTING_EQUITY],
                                  STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
            ax.plot(times, eq, color="goldenrod", linewidth=1.5)
            ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="goldenrod")
            ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
            ax.set_title(
                f"{sym} HVF D1 — N={s['n']}, WR {s['wr']:.0f}%, PF {s['pf']:.2f}, "
                f"${STARTING_EQUITY:,.0f}→${STARTING_EQUITY+s['total']:,.0f}, "
                f"DD {s['dd_pct']:.1f}%",
                fontsize=11, fontweight="bold",
            )
            ax.set_ylabel("Equity ($)")
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        out = ROOT / "charts" / "hvf_gold_silver.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\nChart saved: {out}")


if __name__ == "__main__":
    main()
