"""Daily Donchian breakout on BTCUSD (9y) and US500 (14y).

Same strategy as run_daily_donchian.py — 20-day breakout, 10-day trail, 2N
ATR initial stop, 1% risk per trade. Friction adjusted per-asset based on
IC Markets broker spec:

  BTCUSD: 1 lot = 1 BTC, $1/point P&L per lot, ~$12 round-trip spread.
          BTC weekend gaps possible but instrument trades 24/7.
  US500:  1 lot = 1 contract, $1/index-point P&L per lot, ~$1 round-trip.
          Equity-hours only (CME open ~22:00 UTC Sun → 21:00 UTC Fri).

Crypto separately filtered to drop weekend bars-with-no-volume if any.
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

# Asset-specific config: (symbol, dollar_per_point_per_lot, round_trip_price_cost, weekday_filter)
INSTRUMENTS = [
    # symbol,     $/point/lot, round-trip cost (in price units), weekday_filter
    ("BTCUSD",    1.0,         12.0,                              False),  # 24/7
    ("US500",     1.0,         1.0,                               True),   # Mon-Fri
]

ENTRY_LOOKBACK = 20
EXIT_LOOKBACK = 10
ATR_PERIOD = 20
ATR_STOP_MULT = 2.0

STARTING_EQUITY = 10000.0
RISK_PCT = 1.0


@dataclass
class Trade:
    pair: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    initial_stop_dist: float  # price-unit distance from entry to stop
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pts: float = 0.0
    pnl_usd: float = 0.0


def load_d1(symbol: str, weekday_filter: bool) -> pd.DataFrame:
    """Resample H1 → D1."""
    df = pd.read_csv(ROOT / "data" / f"{symbol}_H1.csv")
    if "time" in df.columns and df["time"].dtype != object:
        df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t")
    d1 = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    if weekday_filter:
        d1 = d1[d1.index.weekday < 5]
    return d1


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(symbol: str, d1: pd.DataFrame, dollar_per_point: float,
             round_trip_cost: float, equity_ref: list[float]) -> list[Trade]:
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

        if open_trade is not None:
            if open_trade.direction == "LONG":
                if row["low"] <= open_trade.stop:
                    exit_price = min(row["open"], open_trade.stop)
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (exit_price - open_trade.entry_price) - round_trip_cost
                else:
                    new_stop = max(open_trade.stop, row["exit_low"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop
            else:  # SHORT
                if row["high"] >= open_trade.stop:
                    exit_price = max(row["open"], open_trade.stop)
                    open_trade.exit_time = t
                    open_trade.exit_price = exit_price
                    open_trade.exit_reason = "STOP"
                    open_trade.pnl_pts = (open_trade.entry_price - exit_price) - round_trip_cost
                else:
                    new_stop = min(open_trade.stop, row["exit_high"])
                    if not pd.isna(new_stop):
                        open_trade.stop = new_stop

            if open_trade.exit_reason:
                # Lot sizing from initial stop distance and risk%
                risk_usd = equity_ref[0] * RISK_PCT / 100.0
                lots = risk_usd / max(open_trade.initial_stop_dist * dollar_per_point, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                open_trade.pnl_usd = open_trade.pnl_pts * lots * dollar_per_point
                equity_ref[0] += open_trade.pnl_usd
                trades.append(open_trade)
                open_trade = None

        if open_trade is None:
            atr = row["atr"]
            if row["close"] > row["entry_high"]:
                entry_price = row["close"]  # no extra slippage; round_trip_cost absorbs it
                initial_stop = entry_price - ATR_STOP_MULT * atr
                open_trade = Trade(
                    pair=symbol, direction="LONG",
                    entry_time=t, entry_price=entry_price,
                    stop=initial_stop,
                    initial_stop_dist=entry_price - initial_stop,
                )
            elif row["close"] < row["entry_low"]:
                entry_price = row["close"]
                initial_stop = entry_price + ATR_STOP_MULT * atr
                open_trade = Trade(
                    pair=symbol, direction="SHORT",
                    entry_time=t, entry_price=entry_price,
                    stop=initial_stop,
                    initial_stop_dist=initial_stop - entry_price,
                )

    if open_trade is not None:
        last_row = d1.iloc[-1]
        if open_trade.direction == "LONG":
            raw = last_row["close"] - open_trade.entry_price
        else:
            raw = open_trade.entry_price - last_row["close"]
        open_trade.exit_time = last_row.name
        open_trade.exit_price = last_row["close"]
        open_trade.exit_reason = "OPEN_END"
        open_trade.pnl_pts = raw - round_trip_cost
        risk_usd = equity_ref[0] * RISK_PCT / 100.0
        lots = risk_usd / max(open_trade.initial_stop_dist * dollar_per_point, 0.01)
        lots = max(min(round(lots, 2), 100.0), 0.01)
        open_trade.pnl_usd = open_trade.pnl_pts * lots * dollar_per_point
        equity_ref[0] += open_trade.pnl_usd
        trades.append(open_trade)

    return trades


def stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    usd = np.array([t.pnl_usd for t in trades])
    pts = np.array([t.pnl_pts for t in trades])
    n = len(trades)
    wins = (usd > 0).sum()
    gp = usd[usd > 0].sum()
    gl = abs(usd[usd <= 0].sum())
    pf = gp / gl if gl else float("inf")
    return {
        "n": n,
        "wr": wins / n * 100,
        "pf": pf,
        "usd": usd.sum(),
        "pts": pts.sum(),
        "avg_win_usd": usd[usd > 0].mean() if wins else 0,
        "avg_loss_usd": usd[usd <= 0].mean() if (usd <= 0).sum() else 0,
    }


def main():
    print(f"Daily Donchian {ENTRY_LOOKBACK}/{EXIT_LOOKBACK} on BTCUSD + US500")
    print(f"  Risk: {RISK_PCT}% per trade; initial stop: {ATR_STOP_MULT}x ATR({ATR_PERIOD})\n")

    results = {}
    for symbol, dpp, rt_cost, wkday_filter in INSTRUMENTS:
        d1 = load_d1(symbol, weekday_filter=wkday_filter)
        years = (d1.index[-1] - d1.index[0]).days / 365.25
        equity_ref = [STARTING_EQUITY]
        trades = simulate(symbol, d1, dpp, rt_cost, equity_ref)
        s = stats(trades)
        final_eq = equity_ref[0]
        ret = (final_eq / STARTING_EQUITY - 1) * 100
        cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
        usd_series = np.array([t.pnl_usd for t in trades])
        eq_curve = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(usd_series)])
        dd = np.maximum.accumulate(eq_curve) - eq_curve
        max_dd = dd.max() if len(dd) > 1 else 0
        max_dd_pct = (max_dd / np.maximum.accumulate(eq_curve).max()) * 100 if max_dd > 0 else 0
        mar = (cagr / max_dd_pct) if max_dd_pct > 0 else 0

        print(f"=== {symbol} ({years:.1f} years, {len(d1)} D1 bars) ===")
        print(f"  Trades: {s['n']}  WR: {s['wr']:.1f}%  PF: {s['pf']:.2f}")
        print(f"  Total points: {s['pts']:+,.0f}")
        print(f"  Avg win:  ${s['avg_win_usd']:+,.2f}")
        print(f"  Avg loss: ${s['avg_loss_usd']:+,.2f}")
        print(f"  Equity:   ${STARTING_EQUITY:,.0f} → ${final_eq:,.2f}  ({ret:+.1f}%)")
        print(f"  CAGR:     {cagr:+.2f}%")
        print(f"  Max DD:   ${max_dd:,.2f} ({max_dd_pct:.1f}%)")
        print(f"  MAR:      {mar:.2f}")
        print()
        results[symbol] = {
            "trades": trades, "stats": s, "eq_curve": eq_curve,
            "years": years, "cagr": cagr, "dd_pct": max_dd_pct, "mar": mar,
            "final": final_eq,
        }

    # Combined-portfolio equity (assume independent capital pools sized so each gets
    # equal $10k start — this is just to visualize both curves; portfolio behavior
    # would need a joint sim).
    fig, axes = plt.subplots(len(INSTRUMENTS), 1, figsize=(14, 4 * len(INSTRUMENTS)),
                             sharex=False)
    if len(INSTRUMENTS) == 1:
        axes = [axes]
    for (sym, _, _, _), ax in zip(INSTRUMENTS, axes):
        r = results[sym]
        trades = r["trades"]
        if not trades:
            continue
        times = [trades[0].entry_time] + [t.exit_time for t in trades]
        ax.plot(times, r["eq_curve"], color="steelblue", linewidth=1.5)
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        ax.fill_between(times, STARTING_EQUITY, r["eq_curve"], alpha=0.15, color="steelblue")
        ax.set_title(
            f"{sym} — {r['years']:.1f}y, N={r['stats']['n']}, "
            f"PF {r['stats']['pf']:.2f}, "
            f"${STARTING_EQUITY:,.0f}→${r['final']:,.2f} ({(r['final']/STARTING_EQUITY-1)*100:+.0f}%), "
            f"CAGR {r['cagr']:+.1f}%, DD {r['dd_pct']:.0f}%, MAR {r['mar']:.2f}",
            fontsize=11, fontweight="bold",
        )
        ax.set_ylabel("Equity ($)")
        ax.grid(True, alpha=0.3)
    out = ROOT / "charts" / "daily_donchian_btc_us500.png"
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Chart: {out}")


if __name__ == "__main__":
    main()
