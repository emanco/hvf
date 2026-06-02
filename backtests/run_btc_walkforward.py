"""Walk-forward validation + variant sweep for BTCUSD Daily Donchian.

Part 1 — Walk-forward: split 9 years into 3 non-overlapping 3-year windows.
Run the base 20/10/2N strategy on each, report PF/MAR per window. Confirms
the edge isn't concentrated in a single regime.

Part 2 — Variant sweep on full 9-year data:
  - Entry/exit lookback combos: (20,10), (20,20), (30,10), (30,15), (40,15),
    (55,20). Fixed ATR=2.0.
  - ATR multiplier sweep: 1.0, 1.5, 2.0, 2.5, 3.0. Fixed entry/exit=20/10.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
SYMBOL = "BTCUSD"
DOLLAR_PER_POINT = 1.0
ROUND_TRIP_COST = 12.0
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0


@dataclass
class Trade:
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    initial_stop_dist: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pts: float = 0.0
    pnl_usd: float = 0.0


def load_d1():
    df = pd.read_csv(ROOT / "data" / f"{SYMBOL}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    return d1


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(d1: pd.DataFrame, entry_lb: int, exit_lb: int, atr_mult: float,
             atr_period: int = 20) -> tuple[list[Trade], float]:
    df = d1.copy()
    df["entry_high"] = df["high"].rolling(entry_lb).max().shift(1)
    df["entry_low"] = df["low"].rolling(entry_lb).min().shift(1)
    df["exit_high"] = df["high"].rolling(exit_lb).max().shift(1)
    df["exit_low"] = df["low"].rolling(exit_lb).min().shift(1)
    df["atr"] = compute_atr(df, atr_period).shift(1)

    trades: list[Trade] = []
    open_trade: Trade | None = None
    equity = STARTING_EQUITY
    for t, row in df.iterrows():
        if pd.isna(row["entry_high"]) or pd.isna(row["atr"]):
            continue

        if open_trade is not None:
            if open_trade.direction == "LONG":
                if row["low"] <= open_trade.stop:
                    exit_price = min(row["open"], open_trade.stop)
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (exit_price - open_trade.entry_price) - ROUND_TRIP_COST
                else:
                    new_stop = max(open_trade.stop, row["exit_low"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop
            else:
                if row["high"] >= open_trade.stop:
                    exit_price = max(row["open"], open_trade.stop)
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.entry_price - exit_price) - ROUND_TRIP_COST
                else:
                    new_stop = min(open_trade.stop, row["exit_high"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop

            if open_trade.exit_reason:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_trade.initial_stop_dist * DOLLAR_PER_POINT, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pts * lots * DOLLAR_PER_POINT
                equity += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        if open_trade is None:
            atr = row["atr"]
            if row["close"] > row["entry_high"]:
                ep = row["close"]
                stop = ep - atr_mult * atr
                open_trade = Trade("LONG", t, ep, stop, ep - stop)
            elif row["close"] < row["entry_low"]:
                ep = row["close"]
                stop = ep + atr_mult * atr
                open_trade = Trade("SHORT", t, ep, stop, stop - ep)

    if open_trade is not None:
        last = df.iloc[-1]
        if open_trade.direction == "LONG":
            raw = last["close"] - open_trade.entry_price
        else:
            raw = open_trade.entry_price - last["close"]
        open_trade.exit_time = last.name
        open_trade.exit_price = last["close"]
        open_trade.exit_reason = "OPEN_END"
        open_trade.pnl_pts = raw - ROUND_TRIP_COST
        risk_usd = equity * RISK_PCT / 100.0
        lots = risk_usd / max(open_trade.initial_stop_dist * DOLLAR_PER_POINT, 0.01)
        lots = max(min(round(lots, 2), 100.0), 0.01)
        open_trade.pnl_usd = open_trade.pnl_pts * lots * DOLLAR_PER_POINT
        equity += open_trade.pnl_usd
        trades.append(open_trade)

    return trades, equity


def summary(trades: list[Trade], final_eq: float, years: float) -> dict:
    if not trades:
        return {"n": 0}
    usd = np.array([t.pnl_usd for t in trades])
    n = len(trades)
    wins = (usd > 0).sum()
    gp = usd[usd > 0].sum()
    gl = abs(usd[usd <= 0].sum())
    pf = gp / gl if gl else float("inf")
    eq_curve = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(usd)])
    dd = np.maximum.accumulate(eq_curve) - eq_curve
    max_dd = dd.max() if len(dd) > 1 else 0
    max_dd_pct = (max_dd / np.maximum.accumulate(eq_curve).max()) * 100 if max_dd > 0 else 0
    ret = (final_eq / STARTING_EQUITY - 1) * 100
    cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    mar = cagr / max_dd_pct if max_dd_pct > 0 else 0
    return {
        "n": n, "wr": wins / n * 100, "pf": pf,
        "ret": ret, "cagr": cagr, "dd_pct": max_dd_pct, "mar": mar,
        "avg_win": usd[usd > 0].mean() if wins else 0,
        "avg_loss": usd[usd <= 0].mean() if (usd <= 0).sum() else 0,
    }


def main():
    d1 = load_d1()
    print(f"{SYMBOL} D1 data: {len(d1)} bars  {d1.index[0]} to {d1.index[-1]}\n")

    # ─── Part 1 — Walk-forward (3-year windows) ───
    print("=" * 90)
    print("PART 1 — Walk-forward (non-overlapping 3-year windows, base 20/10/2N)")
    print("=" * 90)
    print(f"{'Window':<22} {'Years':>6} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
    print("-" * 90)

    windows = [
        ("2017-05 → 2019-12", "2017-05-01", "2020-01-01"),
        ("2020-01 → 2022-12", "2020-01-01", "2023-01-01"),
        ("2023-01 → 2025-12", "2023-01-01", "2026-01-01"),
        ("2026-01 → present",  "2026-01-01", "2027-01-01"),
    ]
    wf_results = []
    for label, start, end in windows:
        win = d1[(d1.index >= start) & (d1.index < end)]
        if len(win) < 30:
            continue
        years = (win.index[-1] - win.index[0]).days / 365.25
        trades, final_eq = simulate(win, 20, 10, 2.0)
        s = summary(trades, final_eq, years)
        if s["n"]:
            print(f"{label:<22} {years:>6.1f} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")
        else:
            print(f"{label:<22} {years:>6.1f}   0 trades")
        wf_results.append((label, s))

    # ─── Part 2a — Lookback combo sweep (full data) ───
    print()
    print("=" * 90)
    print("PART 2a — Entry/exit lookback sweep (full 9y, fixed ATR=2.0)")
    print("=" * 90)
    print(f"{'Entry/Exit':<14} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
    print("-" * 90)
    years_full = (d1.index[-1] - d1.index[0]).days / 365.25
    lookback_combos = [(20, 10), (20, 20), (30, 10), (30, 15), (40, 15), (55, 20)]
    for el, xl in lookback_combos:
        trades, final_eq = simulate(d1, el, xl, 2.0)
        s = summary(trades, final_eq, years_full)
        if s["n"]:
            print(f"{el}/{xl:<10} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")

    # ─── Part 2b — ATR multiplier sweep ───
    print()
    print("=" * 90)
    print("PART 2b — ATR stop multiplier sweep (full 9y, fixed 20/10)")
    print("=" * 90)
    print(f"{'ATR mult':<10} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
    print("-" * 90)
    for am in (1.0, 1.5, 2.0, 2.5, 3.0):
        trades, final_eq = simulate(d1, 20, 10, am)
        s = summary(trades, final_eq, years_full)
        if s["n"]:
            print(f"{am:<10.1f} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")

    # ─── Part 3 — Walk-forward the BEST variant (55/20/1.0) ───
    print()
    print("=" * 90)
    print("PART 3 — Walk-forward 55/20/2.0 AND 55/20/1.0 (does the better variant survive?)")
    print("=" * 90)
    for entry_lb, exit_lb, atr_mult in [(55, 20, 2.0), (55, 20, 1.0), (40, 15, 1.5)]:
        print(f"\n  Variant {entry_lb}/{exit_lb}/{atr_mult}N:")
        print(f"  {'Window':<22} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
        print(f"  {'-'*86}")
        for label, start, end in windows:
            win = d1[(d1.index >= start) & (d1.index < end)]
            if len(win) < 60:
                continue
            years = (win.index[-1] - win.index[0]).days / 365.25
            trades, final_eq = simulate(win, entry_lb, exit_lb, atr_mult)
            s = summary(trades, final_eq, years)
            if s["n"]:
                print(f"  {label:<22} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                      f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")
            else:
                print(f"  {label:<22}    0 trades")


if __name__ == "__main__":
    main()
