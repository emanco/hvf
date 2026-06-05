"""Daily Donchian 55/20/1.0 on gold and silver — same params as deployed BTC config.

Reuses the same approach as run_crypto_donchian.py. Gold has 28 years of
broker data (1998-2026), silver 24 years (2002-2026). Both have multiple
distinct regimes — bull runs, bear markets, mid-cycle consolidations.

Asset config (IC Markets):
  XAUUSD: 1 lot = 100 oz, $100 per $1 move, ~$0.40 round-trip spread
  XAGUSD: 1 lot = 1000 oz, $1000 per $1 move, ~$0.04 round-trip spread
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

# Same params as deployed BTC/ETH
ENTRY_LB, EXIT_LB, ATR_PERIOD, ATR_MULT = 55, 20, 20, 1.0
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0

INSTRUMENTS = [
    # (symbol, $/point/lot, round-trip cost in PRICE units)
    ("XAUUSD", 100.0,  0.40),
    ("XAGUSD", 1000.0, 0.04),
]


@dataclass
class Trade:
    symbol: str
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


def load_d1(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    return d1[d1.index.weekday < 5]  # Mon-Fri only (commodities)


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(symbol: str, d1: pd.DataFrame, dpp: float, rt_cost: float):
    df = d1.copy()
    df["entry_high"] = df["high"].rolling(ENTRY_LB).max().shift(1)
    df["entry_low"] = df["low"].rolling(ENTRY_LB).min().shift(1)
    df["exit_high"] = df["high"].rolling(EXIT_LB).max().shift(1)
    df["exit_low"] = df["low"].rolling(EXIT_LB).min().shift(1)
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
                    open_trade.exit_reason = "STOP"
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
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.entry_price - exit_price) - rt_cost
                else:
                    new_stop = min(open_trade.stop, row["exit_high"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop

            if open_trade.exit_reason:
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
                open_trade = Trade(symbol, "LONG", t, ep, stop, ep - stop)
            elif row["close"] < row["entry_low"]:
                ep = row["close"]
                stop = ep + ATR_MULT * atr
                open_trade = Trade(symbol, "SHORT", t, ep, stop, stop - ep)

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
    dd = np.maximum.accumulate(eq) - eq
    max_dd_pct = (dd.max() / np.maximum.accumulate(eq).max() * 100) if dd.max() > 0 else 0
    ret = (final_eq / STARTING_EQUITY - 1) * 100
    cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    return {"n": n, "wr": wins/n*100, "pf": pf, "ret": ret,
            "cagr": cagr, "dd_pct": max_dd_pct,
            "mar": cagr / max_dd_pct if max_dd_pct > 0 else 0}


def main():
    print(f"Daily Donchian {ENTRY_LB}/{EXIT_LB}/{ATR_MULT}N — gold + silver\n")
    print(f"{'Sym':<8} {'Years':>6} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>9} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
    print("-" * 75)
    full = {}
    for sym, dpp, rt in INSTRUMENTS:
        d1 = load_d1(sym)
        years = (d1.index[-1] - d1.index[0]).days / 365.25
        trades, final_eq = simulate(sym, d1, dpp, rt)
        s = stats(trades, final_eq, years)
        if s:
            print(f"{sym:<8} {years:>6.1f} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['ret']:>+8.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")
            full[sym] = (trades, s)

    print()
    print("=" * 75)
    print("Walk-forward (5-year windows)")
    print("=" * 75)
    windows = [
        ("1999 → 2004",  "1999-01-01", "2005-01-01"),
        ("2005 → 2009",  "2005-01-01", "2010-01-01"),
        ("2010 → 2014",  "2010-01-01", "2015-01-01"),
        ("2015 → 2019",  "2015-01-01", "2020-01-01"),
        ("2020 → 2025",  "2020-01-01", "2026-01-01"),
    ]
    for label, start, end in windows:
        print(f"\n  Window {label}:")
        print(f"  {'Sym':<8} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'MAR':>5}")
        for sym, dpp, rt in INSTRUMENTS:
            d1 = load_d1(sym)
            d1 = d1[(d1.index >= start) & (d1.index < end)]
            if len(d1) < 100:
                print(f"  {sym:<8}  insufficient data")
                continue
            years = (d1.index[-1] - d1.index[0]).days / 365.25
            trades, final_eq = simulate(sym, d1, dpp, rt)
            s = stats(trades, final_eq, years)
            if s:
                print(f"  {sym:<8} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                      f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['mar']:>5.2f}")
            else:
                print(f"  {sym:<8} 0 trades")

    # Equity-curve chart
    fig, axes = plt.subplots(len(full), 1, figsize=(14, 4 * len(full)))
    if len(full) == 1:
        axes = [axes]
    for ax, (sym, (trades, s)) in zip(axes, full.items()):
        if not trades:
            continue
        times = [trades[0].entry_time] + [t.exit_time for t in trades]
        eq = np.concatenate([[STARTING_EQUITY],
                              STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
        ax.plot(times, eq, color="goldenrod", linewidth=1.5)
        ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="goldenrod")
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        ax.set_title(
            f"{sym} Daily Donchian {ENTRY_LB}/{EXIT_LB}/{ATR_MULT}N — "
            f"N={s['n']}, PF {s['pf']:.2f}, "
            f"${STARTING_EQUITY:,.0f}→${STARTING_EQUITY+(s['ret']/100)*STARTING_EQUITY:,.0f} "
            f"({s['ret']:+.0f}%), CAGR {s['cagr']:+.1f}%, MAR {s['mar']:.2f}, DD {s['dd_pct']:.1f}%",
            fontsize=11, fontweight="bold",
        )
        ax.set_ylabel("Equity ($)")
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = ROOT / "charts" / "donchian_metals.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out}")


if __name__ == "__main__":
    main()
