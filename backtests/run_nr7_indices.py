"""Cross-validate NR7 breakout across US500, DE40, JP225, UK100.

If the US500 result (PF 5.46, 14y) is real, the strategy should produce
positive edge on other developed-market indices too. If it works on 1
index only, it's curve-fit. If it works on 3+, it's likely a real edge.

Also stress-tests friction assumption: runs each index at three different
round-trip cost levels.
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

STARTING_EQUITY = 10000.0
RISK_PCT = 1.0
DOLLAR_PER_POINT = 1.0

# (symbol, default round-trip cost in index points)
INDICES = [
    ("US500", 0.5),
    ("DE40",  1.0),   # DAX wider spreads typically
    ("JP225", 5.0),   # Nikkei wider still (smaller point unit but wider in points)
    ("UK100", 1.0),
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


def load_d1(symbol: str):
    df = pd.read_csv(ROOT / "data" / f"{symbol}_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"}).dropna()
    return d1[d1.index.weekday < 5]


def compute_atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def nr7_breakout(d1: pd.DataFrame, rt_cost: float, gap_fill: bool = True):
    """gap_fill=True models realistic stop-order fills: if the next bar gaps
    OPEN through the breakout level, the fill is at the open (worse), not the
    exact stop level. This is the main optimism in the original sim — index
    futures gap overnight, so a buy-stop at yesterday's high often fills above
    it. gap_fill=False reproduces the old exact-stop-fill assumption."""
    df = d1.copy()
    df["range"] = df["high"] - df["low"]
    df["atr"] = compute_atr(df).shift(1)
    df["nr7"] = df["range"] == df["range"].rolling(7).min()

    trades = []
    open_trade = None
    equity = STARTING_EQUITY
    rows = list(df.iterrows())
    for i in range(7, len(rows) - 1):
        t, row = rows[i]
        nr_day = row["nr7"] and not pd.isna(row["atr"])
        next_t, next_row = rows[i + 1]

        if open_trade is not None:
            if open_trade.direction == "LONG":
                if row["low"] <= open_trade.stop:
                    open_trade.exit_time = t
                    open_trade.exit_price = open_trade.stop
                    open_trade.pnl_pts = (open_trade.stop - open_trade.entry_price) - rt_cost
                else:
                    exit_idx = max(0, i - 10)
                    trail = df["low"].iloc[exit_idx:i].max()
                    if not pd.isna(trail):
                        open_trade.stop = max(open_trade.stop, trail)
            else:
                if row["high"] >= open_trade.stop:
                    open_trade.exit_time = t
                    open_trade.exit_price = open_trade.stop
                    open_trade.pnl_pts = (open_trade.entry_price - open_trade.stop) - rt_cost
                else:
                    exit_idx = max(0, i - 10)
                    trail = df["high"].iloc[exit_idx:i].min()
                    if not pd.isna(trail):
                        open_trade.stop = min(open_trade.stop, trail)
            if open_trade.exit_time is not None:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_trade.initial_stop_dist * DOLLAR_PER_POINT, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pts * lots * DOLLAR_PER_POINT
                equity += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        if open_trade is None and nr_day:
            buy_stop = row["high"]
            sell_stop = row["low"]
            atr = row["atr"]
            n_open = next_row["open"]
            # Realistic stop-order fill: a buy-stop fills at max(level, open)
            # (gap-up opens above the level → fill at the worse open price);
            # a sell-stop fills at min(level, open).
            long_fill = max(buy_stop, n_open) if gap_fill else buy_stop
            short_fill = min(sell_stop, n_open) if gap_fill else sell_stop
            if next_row["high"] >= buy_stop and next_row["low"] <= sell_stop:
                if next_row["close"] > next_row["open"]:
                    direction, entry, stop = "LONG", long_fill, buy_stop - atr
                else:
                    direction, entry, stop = "SHORT", short_fill, sell_stop + atr
            elif next_row["high"] >= buy_stop:
                direction, entry, stop = "LONG", long_fill, buy_stop - atr
            elif next_row["low"] <= sell_stop:
                direction, entry, stop = "SHORT", short_fill, sell_stop + atr
            else:
                continue
            open_trade = Trade(
                direction=direction, entry_time=next_t, entry_price=entry,
                stop=stop, initial_stop_dist=abs(entry - stop),
            )

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
    dd_pct = (dd.max() / np.maximum.accumulate(eq).max() * 100) if dd.max() > 0 else 0
    cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    return {"n": n, "wr": wins/n*100, "pf": pf,
            "total": usd.sum(), "cagr": cagr, "dd_pct": dd_pct,
            "mar": cagr/dd_pct if dd_pct > 0 else 0}


def main():
    print("NR7 cross-validation across 4 major equity indices\n")
    print(f"{'Index':<8} {'Years':>6} {'N':>5} {'WR':>5} {'PF':>5} {'CAGR':>7} {'DD':>5} {'MAR':>5}")
    print("-" * 60)
    full_results = {}
    for sym, rt in INDICES:
        d1 = load_d1(sym)
        years = (d1.index[-1] - d1.index[0]).days / 365.25
        trades, final_eq = nr7_breakout(d1, rt)
        s = stats(trades, final_eq, years)
        if s:
            print(f"{sym:<8} {years:>6.1f} {s['n']:>5d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['cagr']:>+6.2f}% {s['dd_pct']:>4.1f}% {s['mar']:>5.2f}")
            full_results[sym] = (trades, s)
        else:
            print(f"{sym:<8} 0 trades")
    print()

    # Friction stress-test (US500 only)
    print("=" * 70)
    print("Friction stress-test on US500 — what if real costs are higher?")
    print("=" * 70)
    print(f"{'RT cost':<10} {'N':>5} {'WR':>5} {'PF':>5} {'CAGR':>7} {'DD':>5} {'MAR':>5}")
    print("-" * 70)
    d1 = load_d1("US500")
    years = (d1.index[-1] - d1.index[0]).days / 365.25
    for rt in [0.5, 1.0, 2.0, 3.0, 5.0]:
        trades, final_eq = nr7_breakout(d1, rt)
        s = stats(trades, final_eq, years)
        if s:
            print(f"{rt:<10.1f} {s['n']:>5d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['cagr']:>+6.2f}% {s['dd_pct']:>4.1f}% {s['mar']:>5.2f}")
    print()

    # Walk-forward per index
    print("=" * 70)
    print("Walk-forward (3-year windows) per index")
    print("=" * 70)
    windows = [
        ("2013-15", "2013-01-01", "2016-01-01"),
        ("2016-18", "2016-01-01", "2019-01-01"),
        ("2019-21", "2019-01-01", "2022-01-01"),
        ("2022-25", "2022-01-01", "2026-01-01"),
    ]
    for sym, rt in INDICES:
        print(f"\n  {sym} (rt={rt}):")
        print(f"  {'Window':<10} {'N':>4} {'WR':>5} {'PF':>5} {'CAGR':>7} {'DD':>5} {'MAR':>5}")
        d1_full = load_d1(sym)
        for label, start, end in windows:
            sub = d1_full[(d1_full.index >= start) & (d1_full.index < end)]
            if len(sub) < 100:
                continue
            sub_years = (sub.index[-1] - sub.index[0]).days / 365.25
            trades, final_eq = nr7_breakout(sub, rt)
            s = stats(trades, final_eq, sub_years)
            if s:
                print(f"  {label:<10} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                      f"{s['cagr']:>+6.2f}% {s['dd_pct']:>4.1f}% {s['mar']:>5.2f}")

    # Chart
    fig, axes = plt.subplots(len(full_results), 1, figsize=(14, 3.5 * len(full_results)))
    if len(full_results) == 1:
        axes = [axes]
    for ax, (sym, (trades, s)) in zip(axes, full_results.items()):
        if not trades:
            continue
        times = [trades[0].entry_time] + [t.exit_time for t in trades]
        eq = np.concatenate([[STARTING_EQUITY],
                              STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
        ax.plot(times, eq, color="steelblue", linewidth=1.5)
        ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        ax.set_title(f"{sym} NR7 breakout — N={s['n']}, PF {s['pf']:.2f}, "
                     f"CAGR {s['cagr']:+.1f}%, DD {s['dd_pct']:.1f}%, MAR {s['mar']:.2f}",
                     fontsize=11, fontweight="bold")
        ax.set_ylabel("Equity ($)")
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = ROOT / "charts" / "nr7_indices.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out}")


if __name__ == "__main__":
    main()
