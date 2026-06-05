"""Test three equity-index strategy candidates on US500 (14 years D1).

We already know Daily Donchian doesn't work on US500 (PF 0.89). Test three
different strategy archetypes that DO have academic support on indices:

  1. Overnight gap fade — open-vs-prior-close gap mean-reverts during session
  2. NR7 breakout — narrowest range of last 7 days → next-day breakout
  3. Pullback to MA in uptrend — D1 trend filter + pullback entry

US500 broker spec (IC Markets): 1 lot = $1/index-point P&L, spread ~0.30
points. Sized at 1% risk per trade. 14-year data 2012-2026.
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
RT_COST = 0.5  # round-trip spread in index points


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
    df = pd.read_csv(ROOT / "data" / "US500_H1.csv")
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"}).dropna()
    d1 = d1[d1.index.weekday < 5]
    d1["prev_close"] = d1["close"].shift(1)
    return d1


def compute_atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


# ─── Strategy 1: Overnight gap fade ──────────────────────────────────────
def gap_fade(d1: pd.DataFrame):
    """
    Each day:
      - Compute gap = open - prev_close (in index points)
      - If abs(gap) > min_gap_pts and abs(gap) < max_gap_pts: FADE the gap
      - Entry: at open price
      - Stop: opposite side of the gap by 1× ATR
      - Exit: at session close (D1 close)
    """
    MIN_GAP, MAX_GAP = 10, 60  # only fade meaningful gaps; skip huge news gaps
    df = d1.copy()
    df["gap"] = df["open"] - df["prev_close"]
    df["atr"] = compute_atr(df).shift(1)

    trades = []
    equity = STARTING_EQUITY
    for t, row in df.iterrows():
        gap = row["gap"]
        atr = row["atr"]
        if pd.isna(gap) or pd.isna(atr) or atr <= 0:
            continue
        if abs(gap) < MIN_GAP or abs(gap) > MAX_GAP:
            continue

        entry = row["open"]
        if gap > 0:  # gap up → fade short
            direction = "SHORT"
            stop = entry + atr
            exit_pnl = entry - row["close"] - RT_COST
        else:  # gap down → fade long
            direction = "LONG"
            stop = entry - atr
            exit_pnl = row["close"] - entry - RT_COST

        # Check if stop hit intraday
        if direction == "SHORT" and row["high"] >= stop:
            pnl_pts = entry - stop - RT_COST
        elif direction == "LONG" and row["low"] <= stop:
            pnl_pts = stop - entry - RT_COST
        else:
            pnl_pts = exit_pnl

        initial_stop_dist = abs(entry - stop)
        risk_usd = equity * RISK_PCT / 100.0
        lots = risk_usd / max(initial_stop_dist * DOLLAR_PER_POINT, 0.01)
        lots = max(min(round(lots, 2), 100.0), 0.01)
        pnl_usd = pnl_pts * lots * DOLLAR_PER_POINT
        equity += pnl_usd

        trades.append(Trade(
            direction=direction, entry_time=t, entry_price=entry,
            stop=stop, initial_stop_dist=initial_stop_dist,
            exit_time=t, exit_price=row["close"],
            exit_reason="SESSION_CLOSE" if pnl_pts == exit_pnl else "STOP",
            pnl_pts=pnl_pts, pnl_usd=pnl_usd,
        ))

    return trades


# ─── Strategy 2: NR7 breakout ─────────────────────────────────────────────
def nr7_breakout(d1: pd.DataFrame):
    """
    If today's range is the narrowest of the last 7 days (NR7):
      - Tomorrow: place BUY_STOP at today's H, SELL_STOP at today's L
      - Whichever fires first; opposite cancels
      - Stop: ATR-based
      - Exit: 10-day opposite extreme trail, OR 10-bar time stop
    """
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
            # Manage open trade on each day
            if open_trade.direction == "LONG":
                if row["low"] <= open_trade.stop:
                    open_trade.exit_time = t
                    open_trade.exit_price = open_trade.stop
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.stop - open_trade.entry_price) - RT_COST
                else:
                    # Trail to 10-day low
                    exit_low_idx = max(0, i - 10)
                    trail = df["low"].iloc[exit_low_idx:i].max()
                    open_trade.stop = max(open_trade.stop, trail)
            else:
                if row["high"] >= open_trade.stop:
                    open_trade.exit_time = t
                    open_trade.exit_price = open_trade.stop
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.entry_price - open_trade.stop) - RT_COST
                else:
                    exit_high_idx = max(0, i - 10)
                    trail = df["high"].iloc[exit_high_idx:i].min()
                    open_trade.stop = min(open_trade.stop, trail)
            if open_trade.exit_time is not None:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_trade.initial_stop_dist * DOLLAR_PER_POINT, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pts * lots * DOLLAR_PER_POINT
                equity += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        # NR7 signal — set up tomorrow's brackets, fire if either is hit
        if open_trade is None and nr_day:
            buy_stop = row["high"]
            sell_stop = row["low"]
            atr = row["atr"]
            if next_row["high"] >= buy_stop and next_row["low"] <= sell_stop:
                # Both hit same day — pick based on close direction
                if next_row["close"] > next_row["open"]:
                    direction, entry, stop = "LONG", buy_stop, buy_stop - atr
                else:
                    direction, entry, stop = "SHORT", sell_stop, sell_stop + atr
            elif next_row["high"] >= buy_stop:
                direction, entry, stop = "LONG", buy_stop, buy_stop - atr
            elif next_row["low"] <= sell_stop:
                direction, entry, stop = "SHORT", sell_stop, sell_stop + atr
            else:
                continue
            open_trade = Trade(
                direction=direction, entry_time=next_t, entry_price=entry,
                stop=stop, initial_stop_dist=abs(entry - stop),
            )

    return trades


# ─── Strategy 3: Pullback to MA in uptrend ────────────────────────────────
def pullback_to_ma(d1: pd.DataFrame):
    """
    Uptrend: D1 close > 50-day SMA AND 50-SMA > 200-SMA
    Downtrend: opposite
    Pullback (uptrend): 3+ consecutive lower closes
    Entry: close > prev close (reversal bar), in trend direction
    Stop: 1× ATR below pullback low (or above for shorts)
    Exit: 20-day trailing extreme, or 1.5x ATR profit, or stop
    """
    df = d1.copy()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["atr"] = compute_atr(df).shift(1)
    df["lower_close"] = df["close"] < df["close"].shift(1)
    df["consec_down"] = df["lower_close"].astype(int).groupby(
        (df["lower_close"] != df["lower_close"].shift()).cumsum()
    ).cumsum()
    df["consec_up"] = (~df["lower_close"]).astype(int).groupby(
        (df["lower_close"] != df["lower_close"].shift()).cumsum()
    ).cumsum()

    trades = []
    open_trade = None
    equity = STARTING_EQUITY
    rows = list(df.iterrows())
    for i in range(200, len(rows)):
        t, row = rows[i]
        if open_trade is not None:
            # Manage open trade
            if open_trade.direction == "LONG":
                if row["low"] <= open_trade.stop:
                    open_trade.exit_time = t
                    open_trade.exit_price = open_trade.stop
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.stop - open_trade.entry_price) - RT_COST
                else:
                    trail = df["low"].iloc[max(0, i-20):i].max()
                    open_trade.stop = max(open_trade.stop, trail)
            else:
                if row["high"] >= open_trade.stop:
                    open_trade.exit_time = t
                    open_trade.exit_price = open_trade.stop
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.entry_price - open_trade.stop) - RT_COST
                else:
                    trail = df["high"].iloc[max(0, i-20):i].min()
                    open_trade.stop = min(open_trade.stop, trail)
            if open_trade.exit_time is not None:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_trade.initial_stop_dist * DOLLAR_PER_POINT, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pts * lots * DOLLAR_PER_POINT
                equity += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        if open_trade is None and not pd.isna(row["sma50"]) and not pd.isna(row["sma200"]):
            atr = row["atr"]
            if pd.isna(atr) or atr <= 0:
                continue
            prev_row = rows[i-1][1]
            in_uptrend = row["close"] > row["sma50"] and row["sma50"] > row["sma200"]
            in_downtrend = row["close"] < row["sma50"] and row["sma50"] < row["sma200"]

            # Uptrend: look for pullback (>=3 lower closes) then bullish reversal
            if in_uptrend and prev_row["consec_down"] >= 3 and row["close"] > prev_row["close"]:
                # Pullback low = prior bar's low (the end of the down sequence)
                pb_low = prev_row["low"]
                stop = pb_low - atr * 0.5
                entry = row["close"]
                if entry > stop:
                    open_trade = Trade(
                        direction="LONG", entry_time=t, entry_price=entry,
                        stop=stop, initial_stop_dist=entry - stop,
                    )
            # Downtrend: mirror
            elif in_downtrend and prev_row["consec_up"] >= 3 and row["close"] < prev_row["close"]:
                pb_high = prev_row["high"]
                stop = pb_high + atr * 0.5
                entry = row["close"]
                if entry < stop:
                    open_trade = Trade(
                        direction="SHORT", entry_time=t, entry_price=entry,
                        stop=stop, initial_stop_dist=stop - entry,
                    )

    return trades


def stats(trades, years):
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
    total = usd.sum()
    final = STARTING_EQUITY + total
    ret = (final / STARTING_EQUITY - 1) * 100
    cagr = ((final / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    return {"n": n, "wr": wins/n*100, "pf": pf, "total": total,
            "ret": ret, "cagr": cagr, "dd_pct": dd_pct,
            "mar": cagr/dd_pct if dd_pct > 0 else 0}


def main():
    d1 = load_d1()
    years = (d1.index[-1] - d1.index[0]).days / 365.25
    print(f"US500 D1: {len(d1)} bars, {years:.1f} years\n")

    results = {}
    for name, fn in [
        ("Gap fade", gap_fade),
        ("NR7 breakout", nr7_breakout),
        ("Pullback to MA", pullback_to_ma),
    ]:
        trades = fn(d1)
        s = stats(trades, years)
        if s:
            print(f"{name:<18} N={s['n']:>4} WR={s['wr']:>4.0f}% PF={s['pf']:>5.2f} "
                  f"Ret={s['ret']:>+7.1f}% CAGR={s['cagr']:>+5.2f}% DD={s['dd_pct']:>4.1f}% MAR={s['mar']:>5.2f}")
            results[name] = (trades, s)
        else:
            print(f"{name:<18} 0 trades")
    print()

    # Walk-forward
    print("=" * 80)
    print("Walk-forward (3-year windows)")
    print("=" * 80)
    windows = [
        ("2013-15", "2013-01-01", "2016-01-01"),
        ("2016-18", "2016-01-01", "2019-01-01"),
        ("2019-21", "2019-01-01", "2022-01-01"),
        ("2022-25", "2022-01-01", "2026-01-01"),
    ]
    for name, fn in [("Gap fade", gap_fade), ("NR7 breakout", nr7_breakout),
                     ("Pullback to MA", pullback_to_ma)]:
        print(f"\n  {name}:")
        print(f"  {'Window':<10} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>5} {'MAR':>5}")
        for label, start, end in windows:
            sub = d1[(d1.index >= start) & (d1.index < end)]
            if len(sub) < 100:
                continue
            sub_years = (sub.index[-1] - sub.index[0]).days / 365.25
            sub_trades = fn(sub)
            s = stats(sub_trades, sub_years)
            if s:
                print(f"  {label:<10} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                      f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>4.1f}% {s['mar']:>5.2f}")

    # Chart equity curves
    fig, axes = plt.subplots(len(results), 1, figsize=(14, 4 * len(results)))
    if len(results) == 1:
        axes = [axes]
    for ax, (name, (trades, s)) in zip(axes, results.items()):
        if not trades:
            continue
        times = [trades[0].entry_time] + [t.exit_time for t in trades]
        eq = np.concatenate([[STARTING_EQUITY],
                              STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
        ax.plot(times, eq, color="steelblue", linewidth=1.5)
        ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        ax.set_title(f"US500 {name} — N={s['n']}, PF {s['pf']:.2f}, "
                     f"CAGR {s['cagr']:+.1f}%, DD {s['dd_pct']:.1f}%, MAR {s['mar']:.2f}",
                     fontsize=11, fontweight="bold")
        ax.set_ylabel("Equity ($)")
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = ROOT / "charts" / "us500_strategies.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out}")


if __name__ == "__main__":
    main()
