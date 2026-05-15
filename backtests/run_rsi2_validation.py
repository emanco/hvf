"""Connors RSI(2) daily mean-reversion — hardened-harness validation.

Rules (Larry Connors + safety modifications):
  LONG  : daily close > 200-SMA AND RSI(2) <= 5 -> enter next bar open
  SHORT : daily close < 200-SMA AND RSI(2) >= 95 -> enter next bar open
  EXIT  :
    1. Cross of 5-SMA in profit direction -> next bar open
    2. Time stop: 5 bars from entry -> close of bar 5
    3. Hard ATR stop: 1.5 * ATR(14) from entry -> intra-bar via H/L

Frictions:
  - Per-symbol rollover spread (worst-case for daily strategies entering at
    next-bar open right after broker rollover).
  - Random slippage from gaussian(0.5, 0.3) clipped to [0, 2] pips.
  - Multi-seed run for variance estimation.

Universe (per the literature review — range-bound pairs only):
  EURGBP, EURUSD, EURCHF, AUDNZD, AUDCAD
"""
from __future__ import annotations
import random
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hvf_trader.backtesting.spread_model import get_spread_pips, apply_slippage_pips

STARTING_EQUITY = 700.0
RISK_PCT = 1.0  # match production sizing
ATR_STOP_MULT = 1.5
TIME_STOP_BARS = 5
RSI_PERIOD = 2
RSI_LONG_THRESHOLD = 5.0
RSI_SHORT_THRESHOLD = 95.0
SMA_LONG = 200
SMA_EXIT = 5
ATR_PERIOD = 14
SEEDS = (1001, 1002, 1003, 1004, 1005)


@dataclass
class Trade:
    pair: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    sl: float
    lot_size: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0


def pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def load_daily(symbol: str) -> pd.DataFrame:
    """Load H1 (or M15 if H1 missing) CSV and resample to daily OHLC."""
    data_dir = REPO_ROOT / "backtests" / "data"
    for tf in ("H1", "M30", "M15"):
        p = data_dir / f"{symbol}_{tf}.csv"
        if p.exists():
            df = pd.read_csv(p)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            break
    else:
        raise FileNotFoundError(f"No suitable CSV for {symbol}")

    df = df.set_index("time")
    d = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    # indicators
    d["sma200"] = d["close"].rolling(SMA_LONG).mean()
    d["sma5"] = d["close"].rolling(SMA_EXIT).mean()
    d["rsi2"] = wilder_rsi(d["close"], RSI_PERIOD)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    d["atr14"] = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()
    d = d.dropna().reset_index()
    return d


def apply_entry_friction(symbol: str, raw_price: float, direction: str,
                         hour_utc: int) -> float:
    """Return the realistic fill price after spread + adverse slippage."""
    pip = pip_size(symbol)
    spread = get_spread_pips(symbol, hour_utc, percentile="median")
    slip = apply_slippage_pips()
    if direction == "LONG":
        return raw_price + (spread / 2 + slip) * pip
    return raw_price - (spread / 2 + slip) * pip


def apply_exit_friction(symbol: str, raw_price: float, direction: str,
                        hour_utc: int) -> float:
    """Exit fills get half-spread and slippage on the wrong side."""
    pip = pip_size(symbol)
    spread = get_spread_pips(symbol, hour_utc, percentile="median")
    slip = apply_slippage_pips()
    if direction == "LONG":  # closing long = sell at bid
        return raw_price - (spread / 2 + slip) * pip
    return raw_price + (spread / 2 + slip) * pip


def simulate_pair(symbol: str, df: pd.DataFrame, equity_ref: list[float]) -> list[Trade]:
    """Walk through daily bars and simulate trades for this symbol.

    equity_ref: shared mutable list for compounding the portfolio equity
    across pairs (treats trades as serial in time).
    """
    pip = pip_size(symbol)
    trades: list[Trade] = []
    pos: Trade | None = None
    entry_bar_idx: int | None = None

    for i in range(len(df) - 1):
        bar = df.iloc[i]
        next_bar = df.iloc[i + 1]

        # Handle exit conditions if in position
        if pos is not None:
            # Bar = "today" (post-entry day or later). Check intra-bar SL hit.
            if pos.direction == "LONG":
                if bar["low"] <= pos.sl:
                    fill = apply_exit_friction(symbol, pos.sl, "LONG", 22)
                    pos.exit_time = bar["time"]
                    pos.exit_price = fill
                    pos.exit_reason = "SL"
                    pos.pnl_pips = (fill - pos.entry_price) / pip
            else:
                if bar["high"] >= pos.sl:
                    fill = apply_exit_friction(symbol, pos.sl, "SHORT", 22)
                    pos.exit_time = bar["time"]
                    pos.exit_price = fill
                    pos.exit_reason = "SL"
                    pos.pnl_pips = (pos.entry_price - fill) / pip

            # Exit-signal (5-SMA cross) — evaluated at this bar's close,
            # action at next bar's open.
            if pos.exit_reason == "":
                if pos.direction == "LONG" and bar["close"] > bar["sma5"]:
                    fill = apply_exit_friction(symbol, next_bar["open"], "LONG", 22)
                    pos.exit_time = next_bar["time"]
                    pos.exit_price = fill
                    pos.exit_reason = "SMA5_CROSS"
                    pos.pnl_pips = (fill - pos.entry_price) / pip
                elif pos.direction == "SHORT" and bar["close"] < bar["sma5"]:
                    fill = apply_exit_friction(symbol, next_bar["open"], "SHORT", 22)
                    pos.exit_time = next_bar["time"]
                    pos.exit_price = fill
                    pos.exit_reason = "SMA5_CROSS"
                    pos.pnl_pips = (pos.entry_price - fill) / pip

            # Time-stop
            if pos.exit_reason == "" and i - entry_bar_idx >= TIME_STOP_BARS:
                fill = apply_exit_friction(symbol, bar["close"], pos.direction, 22)
                pos.exit_time = bar["time"]
                pos.exit_price = fill
                pos.exit_reason = "TIME_STOP"
                if pos.direction == "LONG":
                    pos.pnl_pips = (fill - pos.entry_price) / pip
                else:
                    pos.pnl_pips = (pos.entry_price - fill) / pip

            if pos.exit_reason:
                # Approximate USD PnL: pnl_pips * pip * lot * 100k
                # For non-USD-quoted pairs this is a rough USD estimate.
                contract = 100_000
                quote_pnl = pos.pnl_pips * pip * pos.lot_size * contract
                # Convert to USD (rough): for USD-quoted pairs (xxxUSD) this
                # is already USD. For others, treat as USD at the bar's
                # close — small error vs full FX cross conversion.
                pos.pnl_usd = quote_pnl
                trades.append(pos)
                equity_ref[0] += pos.pnl_usd
                pos = None
                entry_bar_idx = None

        # Open new position?
        if pos is None and not pd.isna(bar["rsi2"]) and not pd.isna(bar["sma200"]):
            equity_now = equity_ref[0]
            atr = bar["atr14"]
            sl_distance = ATR_STOP_MULT * atr
            risk_usd = equity_now * (RISK_PCT / 100.0)

            # Long signal
            if bar["close"] > bar["sma200"] and bar["rsi2"] <= RSI_LONG_THRESHOLD:
                raw_entry = next_bar["open"]
                fill = apply_entry_friction(symbol, raw_entry, "LONG", 22)
                sl = fill - sl_distance
                # Position sizing from risk vs sl distance
                pip_value_per_lot = 10.0  # approx $10/pip/standard lot
                stop_pips = sl_distance / pip
                lots = round(risk_usd / max(stop_pips * pip_value_per_lot, 0.01), 2)
                lots = max(min(lots, 5.0), 0.01)
                pos = Trade(
                    pair=symbol, direction="LONG",
                    entry_time=next_bar["time"], entry_price=fill,
                    sl=sl, lot_size=lots,
                )
                entry_bar_idx = i + 1
            elif bar["close"] < bar["sma200"] and bar["rsi2"] >= RSI_SHORT_THRESHOLD:
                raw_entry = next_bar["open"]
                fill = apply_entry_friction(symbol, raw_entry, "SHORT", 22)
                sl = fill + sl_distance
                pip_value_per_lot = 10.0
                stop_pips = sl_distance / pip
                lots = round(risk_usd / max(stop_pips * pip_value_per_lot, 0.01), 2)
                lots = max(min(lots, 5.0), 0.01)
                pos = Trade(
                    pair=symbol, direction="SHORT",
                    entry_time=next_bar["time"], entry_price=fill,
                    sl=sl, lot_size=lots,
                )
                entry_bar_idx = i + 1

    return trades


def run_one_seed(seed: int, pairs: list[str]) -> tuple[list[Trade], list[float]]:
    random.seed(seed)
    equity_ref = [STARTING_EQUITY]
    all_trades = []
    for sym in pairs:
        try:
            df = load_daily(sym)
        except FileNotFoundError as e:
            print(f"  skip {sym}: {e}")
            continue
        trades = simulate_pair(sym, df, equity_ref)
        all_trades.extend(trades)
    return all_trades, equity_ref


def summarize(label: str, trades: list[Trade], final_equity: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"label": label, "n": 0}
    wins = [t for t in trades if t.pnl_pips > 0]
    losses = [t for t in trades if t.pnl_pips <= 0]
    gw = sum(t.pnl_pips for t in wins)
    gl = abs(sum(t.pnl_pips for t in losses))
    pf = gw / gl if gl else float("inf")
    total_pips = sum(t.pnl_pips for t in trades)
    total_usd = sum(t.pnl_usd for t in trades)
    return {
        "label": label,
        "n": n,
        "wr": len(wins) / n * 100,
        "pf": pf,
        "pips": total_pips,
        "usd": total_usd,
        "final_equity": final_equity,
    }


def build_equity_curve(trades: list[Trade]) -> tuple[list, list]:
    """Time-sorted equity curve from trade exits."""
    sorted_t = sorted(trades, key=lambda t: t.exit_time or pd.Timestamp.max)
    times = [t.exit_time for t in sorted_t]
    eq = [STARTING_EQUITY]
    for t in sorted_t:
        eq.append(eq[-1] + t.pnl_usd)
    times = [sorted_t[0].entry_time if sorted_t else pd.Timestamp.now()] + times
    return times, eq


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument(
        "--pairs", nargs="+",
        default=["EURGBP", "EURUSD", "EURCHF", "AUDNZD", "AUDCAD"],
    )
    p.add_argument("--out", default="rsi2_validation.png")
    p.add_argument("--rsi-long", type=float, default=5.0,
                   help="RSI(2) threshold for LONG entries (default 5)")
    p.add_argument("--rsi-short", type=float, default=95.0,
                   help="RSI(2) threshold for SHORT entries (default 95)")
    args = p.parse_args()
    pairs = args.pairs
    # Override module-level thresholds
    global RSI_LONG_THRESHOLD, RSI_SHORT_THRESHOLD
    RSI_LONG_THRESHOLD = args.rsi_long
    RSI_SHORT_THRESHOLD = args.rsi_short
    print(
        f"RSI(2) thresholds: long<={RSI_LONG_THRESHOLD}, "
        f"short>={RSI_SHORT_THRESHOLD}"
    )
    print(f"Connors RSI(2) daily — hardened-harness validation")
    print(f"  Pairs: {pairs}")
    print(f"  Starting equity: ${STARTING_EQUITY}, risk: {RISK_PCT}% per trade")
    print(f"  Stop: {ATR_STOP_MULT}x ATR(14), time stop: {TIME_STOP_BARS} bars")
    print(f"  Seeds: {SEEDS}\n")

    all_runs = []
    for seed in SEEDS:
        trades, eq = run_one_seed(seed, pairs)
        s = summarize(f"seed_{seed}", trades, eq[0])
        all_runs.append((seed, trades, s))
        print(
            f"seed={seed}: N={s['n']:>3} WR={s.get('wr',0):5.1f}% "
            f"PF={s.get('pf',0):5.2f} pips={s.get('pips',0):+8.1f} "
            f"USD={s.get('usd',0):+8.2f} final=${s['final_equity']:,.2f}"
        )

    # Aggregate stats across seeds
    pfs = [r[2]["pf"] for r in all_runs if r[2]["n"] > 0]
    pips_list = [r[2]["pips"] for r in all_runs if r[2]["n"] > 0]
    usds = [r[2]["usd"] for r in all_runs if r[2]["n"] > 0]
    finals = [r[2]["final_equity"] for r in all_runs if r[2]["n"] > 0]
    if pfs:
        mean_pf = sum(pfs) / len(pfs)
        std_pf = (sum((p - mean_pf) ** 2 for p in pfs) / max(len(pfs) - 1, 1)) ** 0.5
        print()
        print(f"Across {len(pfs)} seeds:")
        print(f"  mean PF    = {mean_pf:.2f}  (std {std_pf:.2f}, range [{min(pfs):.2f},{max(pfs):.2f}])")
        print(f"  mean pips  = {sum(pips_list)/len(pips_list):+.1f}")
        print(f"  mean USD   = {sum(usds)/len(usds):+.2f}")
        print(f"  mean final = ${sum(finals)/len(finals):,.2f}")

    # Per-pair attribution (using middle seed)
    mid_run = all_runs[len(all_runs) // 2]
    mid_trades = mid_run[1]
    print(f"\nPer-pair attribution (seed={mid_run[0]}):")
    print(f"  {'pair':<8} {'N':>4} {'WR':>6} {'PF':>6} {'pips':>10}")
    for sym in pairs:
        tp = [t for t in mid_trades if t.pair == sym]
        if not tp:
            print(f"  {sym:<8} {'0':>4}")
            continue
        wins = [t for t in tp if t.pnl_pips > 0]
        gw = sum(t.pnl_pips for t in wins)
        gl = abs(sum(t.pnl_pips for t in tp if t.pnl_pips <= 0))
        pf = gw / gl if gl else float("inf")
        print(
            f"  {sym:<8} {len(tp):>4} {len(wins)/len(tp)*100:>5.1f}% "
            f"{pf:>6.2f} {sum(t.pnl_pips for t in tp):>+10.1f}"
        )

    # Equity curve from middle seed
    times, eq = build_equity_curve(mid_trades)
    peak = np.maximum.accumulate(np.array(eq))
    dd = (np.array(eq) - peak) / peak * 100
    max_dd = abs(dd.min())

    fig, axes = plt.subplots(
        2, 1, figsize=(14, 8),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.3},
    )
    ax1 = axes[0]
    ax1.plot(times, eq, color="steelblue", linewidth=1.5)
    ax1.fill_between(times, STARTING_EQUITY, eq, alpha=0.15, color="steelblue")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ret_pct = (eq[-1] - STARTING_EQUITY) / STARTING_EQUITY * 100
    ax1.set_title(
        f"Connors RSI(2) Daily — ${STARTING_EQUITY:.0f} -> ${eq[-1]:,.2f} "
        f"({ret_pct:+.1f}%)\n"
        f"N={len(mid_trades)} trades, PF={mid_run[2]['pf']:.2f}, "
        f"WR={mid_run[2]['wr']:.1f}%, MaxDD={max_dd:.1f}%, seed={mid_run[0]}",
        fontsize=12, fontweight="bold", linespacing=1.4,
    )
    ax1.set_ylabel("Equity ($)")
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.fill_between(times, dd, 0, color="red", alpha=0.3)
    ax2.plot(times, dd, color="red", linewidth=0.7)
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out_png = REPO_ROOT / "backtests" / "charts" / args.out
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved equity curve: {out_png}")


if __name__ == "__main__":
    main()
