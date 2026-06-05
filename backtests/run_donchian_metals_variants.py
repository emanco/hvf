"""Compare Donchian variants on gold + silver: 55/20 vs 100/30 vs 200/50.

Tests the hypothesis that gold's cycle structure (5-10 year bull/bear, 2-3
year mid-cycle consolidations) demands a slower lookback than the 55/20
that works on crypto. 100/30 is Andreas Clenow's canonical commodity CTA
default; 200/50 is the very-slow / golden-cross variant.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent

ATR_PERIOD = 20
ATR_MULT = 1.0
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0

INSTRUMENTS = [
    ("XAUUSD", 100.0,  0.40),
    ("XAGUSD", 1000.0, 0.04),
]

VARIANTS = [
    ("55/20", 55, 20),
    ("100/30", 100, 30),
    ("200/50", 200, 50),
]


@dataclass
class Trade:
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    initial_stop_dist: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    pnl_pts: float = 0.0
    pnl_usd: float = 0.0


def load_d1(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"}).dropna()
    return d1[d1.index.weekday < 5]


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(d1: pd.DataFrame, entry_lb: int, exit_lb: int,
             dpp: float, rt_cost: float):
    df = d1.copy()
    df["entry_high"] = df["high"].rolling(entry_lb).max().shift(1)
    df["entry_low"] = df["low"].rolling(entry_lb).min().shift(1)
    df["exit_high"] = df["high"].rolling(exit_lb).max().shift(1)
    df["exit_low"] = df["low"].rolling(exit_lb).min().shift(1)
    df["atr"] = compute_atr(df, ATR_PERIOD).shift(1)

    trades = []
    open_trade = None
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
                    open_trade.pnl_pts = (exit_price - open_trade.entry_price) - rt_cost
                else:
                    new_stop = max(open_trade.stop, row["exit_low"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop
            else:
                if row["high"] >= open_trade.stop:
                    exit_price = max(row["open"], open_trade.stop)
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.pnl_pts = (open_trade.entry_price - exit_price) - rt_cost
                else:
                    new_stop = min(open_trade.stop, row["exit_high"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop

            if open_trade.exit_time is not None:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_trade.initial_stop_dist * dpp, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pts * lots * dpp
                equity += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        if open_trade is None:
            atr = row["atr"]
            if row["close"] > row["entry_high"]:
                ep = row["close"]
                stop = ep - ATR_MULT * atr
                open_trade = Trade("LONG", t, ep, stop, ep - stop)
            elif row["close"] < row["entry_low"]:
                ep = row["close"]
                stop = ep + ATR_MULT * atr
                open_trade = Trade("SHORT", t, ep, stop, stop - ep)

    return trades, equity


def stats(trades, final_eq, years):
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
              np.maximum.accumulate(eq).max() * 100) if (np.maximum.accumulate(eq) - eq).max() > 0 else 0
    ret = (final_eq / STARTING_EQUITY - 1) * 100
    cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    return {"n": n, "wr": wins/n*100, "pf": pf, "ret": ret,
            "cagr": cagr, "dd_pct": dd_pct,
            "mar": cagr / dd_pct if dd_pct > 0 else 0}


def main():
    print(f"Donchian variant comparison on metals — full history per asset\n")

    all_runs = {}
    for sym, dpp, rt in INSTRUMENTS:
        d1 = load_d1(sym)
        years = (d1.index[-1] - d1.index[0]).days / 365.25
        print(f"=== {sym} ({years:.1f} years) ===")
        print(f"  {'Variant':<10} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>9} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
        print(f"  {'-'*60}")
        for vname, el, xl in VARIANTS:
            trades, final_eq = simulate(d1, el, xl, dpp, rt)
            s = stats(trades, final_eq, years)
            if s:
                print(f"  {vname:<10} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                      f"{s['ret']:>+8.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")
                all_runs[(sym, vname)] = (trades, s)
            else:
                print(f"  {vname:<10} 0 trades")
        print()

    # Walk-forward (5-year windows) for the top-line variant comparison
    print("=" * 75)
    print("Walk-forward across 5-year windows — PF per (variant, window)")
    print("=" * 75)
    windows = [
        ("2000-04",  "2000-01-01", "2005-01-01"),
        ("2005-09",  "2005-01-01", "2010-01-01"),
        ("2010-14",  "2010-01-01", "2015-01-01"),
        ("2015-19",  "2015-01-01", "2020-01-01"),
        ("2020-25",  "2020-01-01", "2026-01-01"),
    ]
    for sym, dpp, rt in INSTRUMENTS:
        print(f"\n  {sym}:")
        header = "  Window  " + " ".join(f"{v[0]:>10}" for v in VARIANTS)
        print(header)
        d1_full = load_d1(sym)
        for label, start, end in windows:
            d1 = d1_full[(d1_full.index >= start) & (d1_full.index < end)]
            if len(d1) < 100:
                continue
            years = (d1.index[-1] - d1.index[0]).days / 365.25
            cells = [f"  {label:<7} "]
            for vname, el, xl in VARIANTS:
                trades, final_eq = simulate(d1, el, xl, dpp, rt)
                s = stats(trades, final_eq, years)
                if s:
                    cells.append(f"{s['pf']:5.2f}/{s['n']:>3}")
                else:
                    cells.append(f"     -/  -")
            print(" ".join(cells) + "")

    # Chart: per-asset, all three variants overlaid
    fig, axes = plt.subplots(len(INSTRUMENTS), 1, figsize=(14, 4.5 * len(INSTRUMENTS)))
    if len(INSTRUMENTS) == 1:
        axes = [axes]
    colors = {"55/20": "#1f77b4", "100/30": "goldenrod", "200/50": "#d62728"}
    for ax, (sym, _, _) in zip(axes, INSTRUMENTS):
        for vname, el, xl in VARIANTS:
            run = all_runs.get((sym, vname))
            if not run:
                continue
            trades, s = run
            if not trades:
                continue
            times = [trades[0].entry_time] + [t.exit_time for t in trades]
            eq = np.concatenate([[STARTING_EQUITY],
                                  STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
            ax.plot(times, eq, color=colors[vname], linewidth=1.5,
                    label=f"{vname} (N={s['n']}, PF {s['pf']:.2f}, CAGR {s['cagr']:+.1f}%, MAR {s['mar']:.2f})")
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        ax.set_title(f"{sym} — Donchian variant comparison", fontsize=12, fontweight="bold")
        ax.set_ylabel("Equity ($)")
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = ROOT / "charts" / "donchian_metals_variants.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out}")


if __name__ == "__main__":
    main()
