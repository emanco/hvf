"""Test the BTC Donchian 55/20/1.0 setup on other crypto pairs available
at IC Markets.

Asset universe (with available H1 history):
  BTCUSD  — 9 years (already deployed)
  ETHUSD  — 10 years
  LTCUSD  — 15 years
  ADAUSD  — 5 years
  DOGUSD  — 5 years
  BNBUSD  — 5 years
  SOLUSD  — 1.5 years (TOO SHORT for walk-forward, skipped)

For each: run full-period backtest + walk-forward windows + per-day
signal-overlap with BTC (does adding it diversify, or just leverage the
same edge?).
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent

# (symbol, dollar_per_point_per_lot, round-trip cost in price units, vol_min)
INSTRUMENTS = [
    ("BTCUSD",  1.0,   12.0,    0.01),
    ("ETHUSD",  1.0,    5.0,    0.01),   # ~$5 spread typical
    ("LTCUSD",  1.0,    0.5,    0.05),   # tighter spreads
    ("ADAUSD",  100.0,  0.001,  100.0),  # contract 10, tick val 0.0001
    ("DOGUSD",  1000.0, 0.0005, 100.0),  # contract 100, tick val 0.001
    ("BNBUSD",  1.0,    0.2,    0.01),
]

# Same params as the BTC live config — validated by walk-forward
ENTRY_LB, EXIT_LB, ATR_PERIOD, ATR_MULT = 55, 20, 20, 1.0
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0


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
    return d1


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(symbol: str, d1: pd.DataFrame, dpp: float, rt_cost: float):
    df = d1.copy()
    df["entry_high"] = df["high"].rolling(ENTRY_LB).max().shift(1)
    df["entry_low"] = df["low"].rolling(ENTRY_LB).min().shift(1)
    df["exit_high"] = df["high"].rolling(EXIT_LB).max().shift(1)
    df["exit_low"] = df["low"].rolling(EXIT_LB).min().shift(1)
    df["atr"] = compute_atr(df, ATR_PERIOD).shift(1)

    trades = []
    signals_per_day = []
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
                signals_per_day.append((t.date(), "LONG"))
            elif row["close"] < row["entry_low"]:
                ep = row["close"]
                stop = ep + ATR_MULT * atr
                open_trade = Trade(symbol, "SHORT", t, ep, stop, stop - ep)
                signals_per_day.append((t.date(), "SHORT"))

    return trades, equity, signals_per_day


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
    max_dd = dd.max() if len(dd) > 1 else 0
    max_dd_pct = (max_dd / np.maximum.accumulate(eq).max()) * 100 if max_dd > 0 else 0
    ret = (final_eq / STARTING_EQUITY - 1) * 100
    cagr = ((final_eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    return {"n": n, "wr": wins / n * 100, "pf": pf,
            "ret": ret, "cagr": cagr, "dd_pct": max_dd_pct,
            "mar": cagr / max_dd_pct if max_dd_pct > 0 else 0}


def main():
    print(f"Crypto Donchian {ENTRY_LB}/{EXIT_LB}/{ATR_MULT}N — full-period backtest\n")
    print(f"{'Symbol':<8} {'Years':>6} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
    print("-" * 75)
    all_signals = {}
    full_results = {}
    for sym, dpp, rt, vmin in INSTRUMENTS:
        try:
            d1 = load_d1(sym)
        except FileNotFoundError:
            print(f"{sym:<8}  no data file")
            continue
        years = (d1.index[-1] - d1.index[0]).days / 365.25
        trades, final_eq, signals = simulate(sym, d1, dpp, rt)
        all_signals[sym] = set((d, dr) for d, dr in signals)
        s = stats(trades, final_eq, years)
        if s:
            print(f"{sym:<8} {years:>6.1f} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")
            full_results[sym] = s
        else:
            print(f"{sym:<8} 0 trades")

    # ─── Walk-forward 2023-25 (the regime test) on each ─────────────
    print()
    print("=" * 75)
    print("Walk-forward 2023-01 to 2025-12 (the regime that killed 20/10 on BTC)")
    print("=" * 75)
    print(f"{'Symbol':<8} {'N':>4} {'WR':>5} {'PF':>5} {'Ret':>8} {'CAGR':>7} {'DD':>6} {'MAR':>5}")
    print("-" * 75)
    for sym, dpp, rt, vmin in INSTRUMENTS:
        try:
            d1 = load_d1(sym)
        except FileNotFoundError:
            continue
        window = d1[(d1.index >= "2023-01-01") & (d1.index < "2026-01-01")]
        if len(window) < 100:
            print(f"{sym:<8}  insufficient data in window")
            continue
        years = (window.index[-1] - window.index[0]).days / 365.25
        trades, final_eq, _ = simulate(sym, window, dpp, rt)
        s = stats(trades, final_eq, years)
        if s:
            print(f"{sym:<8} {s['n']:>4d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}% {s['dd_pct']:>5.1f}% {s['mar']:>5.2f}")
        else:
            print(f"{sym:<8} 0 trades in window")

    # ─── Signal overlap with BTC ─────────────────────────────────────
    print()
    print("=" * 75)
    print("Signal overlap with BTCUSD (same-day same-direction)")
    print("=" * 75)
    btc_signals = all_signals.get("BTCUSD", set())
    if btc_signals:
        print(f"{'Symbol':<8} {'Total':>8} {'Overlap':>9} {'Pct':>6}  (lower pct = more diversification)")
        print("-" * 75)
        for sym in all_signals:
            if sym == "BTCUSD":
                continue
            sigs = all_signals[sym]
            overlap = len(sigs & btc_signals)
            pct = (overlap / len(sigs) * 100) if sigs else 0
            print(f"{sym:<8} {len(sigs):>8d} {overlap:>9d} {pct:>5.1f}%")

    # ─── Equity-curve chart per asset ─────────────────────────────────
    fig, axes = plt.subplots(len(full_results), 1, figsize=(13, 2.5 * len(full_results)),
                             sharex=False)
    if len(full_results) == 1:
        axes = [axes]
    deployed = {"BTCUSD", "ETHUSD"}
    for ax, (sym, _, _, _) in zip(axes, [i for i in INSTRUMENTS if i[0] in full_results]):
        d1 = load_d1(sym)
        dpp = next(i[1] for i in INSTRUMENTS if i[0] == sym)
        rt = next(i[2] for i in INSTRUMENTS if i[0] == sym)
        trades, _, _ = simulate(sym, d1, dpp, rt)
        if not trades:
            continue
        times = [trades[0].entry_time] + [t.exit_time for t in trades]
        usd_series = np.array([t.pnl_usd for t in trades])
        eq = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(usd_series)])
        s = full_results[sym]
        color = "darkgreen" if sym in deployed else "steelblue"
        lw = 1.8 if sym in deployed else 1.2
        ax.plot(times, eq, color=color, linewidth=lw)
        ax.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color=color)
        ax.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
        # Shade the 2023-25 walk-forward window
        ax.axvspan(pd.Timestamp("2023-01-01", tz="UTC"),
                   pd.Timestamp("2026-01-01", tz="UTC"),
                   alpha=0.08, color="orange", label="2023-25 regime test")
        marker = " ★ DEPLOYED" if sym in deployed else ""
        ax.set_title(
            f"{sym}{marker} — N={s['n']}, PF {s['pf']:.2f}, "
            f"${STARTING_EQUITY:,.0f}→${STARTING_EQUITY*(1+s['ret']/100):,.0f} "
            f"({s['ret']:+.0f}%), CAGR {s['cagr']:+.1f}%, DD {s['dd_pct']:.1f}%, MAR {s['mar']:.2f}",
            fontsize=10, fontweight="bold",
        )
        ax.set_ylabel("Equity ($)")
        ax.grid(True, alpha=0.3)
    plt.suptitle(f"Crypto Daily Donchian {ENTRY_LB}/{EXIT_LB}/{ATR_MULT}N — per-asset equity curves",
                 fontsize=13, fontweight="bold", y=0.995)
    plt.tight_layout()
    out = ROOT / "charts" / "crypto_donchian_per_asset.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart saved: {out}")


if __name__ == "__main__":
    main()
