"""
Re-validate KZ_HUNT strategy with fixed backtest engine.

Runs:
  1. 1-year backtest (Apr 2025 - Apr 2026) per pair
  2. Walk-forward validation (12m train / 3m test / 3m step) per pair
  3. Aggregate results across all pairs

Runs on VPS where MT5 data is available.
"""

import sys
import os
import logging

sys.path.insert(0, "C:/")
from dotenv import load_dotenv
load_dotenv("C:/hvf_trader/.env")

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader.backtesting.walk_forward import run_walk_forward

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SYMBOLS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
EQUITY = 10000.0


def fetch_history(symbol, timeframe_mt5, bars=20000):
    """Fetch historical H1 data from MT5."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, bars)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def run_1yr_backtest(all_data):
    """Run 1-year backtest (Apr 2025 - Apr 2026) for each pair."""
    print("\n" + "=" * 70)
    print("PART 1: 1-YEAR BACKTEST (Apr 2025 - Apr 2026)")
    print("=" * 70)

    one_year_ago = pd.Timestamp("2025-04-12", tz="UTC")
    now = pd.Timestamp("2026-04-12", tz="UTC")

    all_trades = []
    pair_results = {}

    for symbol, df_1h in all_data.items():
        mask = (df_1h["time"] >= one_year_ago) & (df_1h["time"] <= now)
        df_period = df_1h[mask].copy().reset_index(drop=True)

        if len(df_period) < 300:
            print(f"  {symbol}: SKIP (only {len(df_period)} bars)")
            continue

        engine = BacktestEngine(starting_equity=EQUITY, enabled_patterns=["KZ_HUNT"])
        result = engine.run(df_period, symbol)

        pair_results[symbol] = result
        all_trades.extend(result.trades)

        # Per-pair summary
        print(f"  {symbol}: {result.total_trades:3d} trades, "
              f"WR={result.win_rate:5.1f}%, "
              f"PF={result.profit_factor:5.2f}, "
              f"PnL={result.total_pnl_pips:+8.1f} pips, "
              f"MaxDD={result.max_drawdown_pct:5.1f}%")

    # Aggregate
    if all_trades:
        winners = [t for t in all_trades if t.pnl_pips > 0]
        losers = [t for t in all_trades if t.pnl_pips <= 0]
        total_pips = sum(t.pnl_pips for t in all_trades)
        gross_profit = sum(t.pnl_currency for t in winners) if winners else 0
        gross_loss = abs(sum(t.pnl_currency for t in losers)) if losers else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        wr = len(winners) / len(all_trades) * 100

        # Exit reason breakdown
        reasons = {}
        for t in all_trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

        # Max consecutive losses
        max_consec = 0
        current_consec = 0
        for t in sorted(all_trades, key=lambda x: x.entry_time):
            if t.pnl_pips <= 0:
                current_consec += 1
                max_consec = max(max_consec, current_consec)
            else:
                current_consec = 0

        print(f"\n  {'-' * 50}")
        print(f"  AGGREGATE (all pairs):")
        print(f"    Trades: {len(all_trades)}")
        print(f"    Win Rate: {wr:.1f}%")
        print(f"    Profit Factor: {pf:.2f}")
        print(f"    Total PnL: {total_pips:+.1f} pips")
        print(f"    Gross profit: {gross_profit:+.2f}")
        print(f"    Gross loss: {gross_loss:.2f}")
        print(f"    Max consecutive losses: {max_consec}")
        print(f"    Exit reasons: {reasons}")

    return pair_results


def run_walkforward(all_data):
    """Run walk-forward validation for each pair."""
    print("\n" + "=" * 70)
    print("PART 2: WALK-FORWARD VALIDATION (12m train / 3m test / 3m step)")
    print("=" * 70)

    all_oos_trades = []
    pair_wf = {}

    for symbol, df_1h in all_data.items():
        print(f"\n  {symbol} ({len(df_1h)} bars, "
              f"{df_1h['time'].iloc[0].strftime('%Y-%m-%d')} to "
              f"{df_1h['time'].iloc[-1].strftime('%Y-%m-%d')}):")

        wf_result = run_walk_forward(
            df_1h, symbol,
            train_months=12,
            test_months=3,
            step_months=3,
            starting_equity=EQUITY,
            enabled_patterns=["KZ_HUNT"],
        )

        pair_wf[symbol] = wf_result

        # Collect all OOS trades
        for w in wf_result.windows:
            if w.test_result:
                all_oos_trades.extend(w.test_result.trades)

        print(f"    Windows: {len(wf_result.windows)}")
        print(f"    OOS trades: {wf_result.total_oos_trades}")
        print(f"    OOS WR: {wf_result.oos_win_rate:.1f}%")
        print(f"    OOS PF: {wf_result.oos_profit_factor:.2f}")
        print(f"    OOS PnL: {wf_result.oos_total_pnl_pips:+.1f} pips")
        print(f"    Positive windows: {wf_result.oos_positive_windows}/{len(wf_result.windows)} "
              f"({wf_result.oos_positive_window_pct:.0f}%)")

    # Aggregate across all pairs
    if all_oos_trades:
        winners = [t for t in all_oos_trades if t.pnl_pips > 0]
        losers = [t for t in all_oos_trades if t.pnl_pips <= 0]
        total_pips = sum(t.pnl_pips for t in all_oos_trades)
        gross_profit = sum(t.pnl_currency for t in winners) if winners else 0
        gross_loss = abs(sum(t.pnl_currency for t in losers)) if losers else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        wr = len(winners) / len(all_oos_trades) * 100

        total_windows = sum(len(r.windows) for r in pair_wf.values())
        positive_windows = sum(r.oos_positive_windows for r in pair_wf.values())

        print(f"\n  {'-' * 50}")
        print(f"  AGGREGATE WALK-FORWARD (all pairs):")
        print(f"    Total OOS trades: {len(all_oos_trades)}")
        print(f"    OOS Win Rate: {wr:.1f}%")
        print(f"    OOS Profit Factor: {pf:.2f}")
        print(f"    OOS Total PnL: {total_pips:+.1f} pips")
        print(f"    Positive windows: {positive_windows}/{total_windows} "
              f"({positive_windows/total_windows*100:.0f}%)" if total_windows > 0 else "")

    return pair_wf


def main():
    path = os.getenv("MT5_PATH")
    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not mt5.initialize(path=path):
        print(f"MT5 init failed: {mt5.last_error()}")
        return
    if not mt5.login(login, password=password, server=server):
        print(f"MT5 login failed: {mt5.last_error()}")
        return
    print("MT5 connected")

    # Fetch all data upfront
    all_data = {}
    for symbol in SYMBOLS:
        print(f"  Fetching {symbol}...", end=" ", flush=True)
        df = fetch_history(symbol, mt5.TIMEFRAME_H1, bars=20000)
        if df is None:
            print("FAILED")
            continue
        df = add_indicators(df)
        df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        all_data[symbol] = df
        span_years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
        print(f"{len(df)} bars ({span_years:.1f} years)")

    mt5.shutdown()

    # Run both validations
    yr_results = run_1yr_backtest(all_data)
    wf_results = run_walkforward(all_data)

    # ── Final comparison table ──
    print("\n" + "=" * 70)
    print("OLD vs NEW BACKTEST COMPARISON")
    print("=" * 70)
    print("\n  OLD (bugged scorer, included forming bar):")
    print("    1-Year:      743 trades, WR=52.9%, PF=1.73, +2932 pips")
    print("    Walk-Forward: 4656 trades, WR=61%, PF=1.53, +13483 pips, 79% windows +ve")
    print("\n  NEW (fixed scorer, correct bar handling):")

    # 1-year aggregate
    all_1yr = []
    for r in yr_results.values():
        all_1yr.extend(r.trades)
    if all_1yr:
        w = [t for t in all_1yr if t.pnl_pips > 0]
        l = [t for t in all_1yr if t.pnl_pips <= 0]
        gp = sum(t.pnl_currency for t in w) if w else 0
        gl = abs(sum(t.pnl_currency for t in l)) if l else 0
        pf = gp / gl if gl > 0 else float("inf")
        wr = len(w) / len(all_1yr) * 100
        pips = sum(t.pnl_pips for t in all_1yr)
        print(f"    1-Year:      {len(all_1yr)} trades, WR={wr:.1f}%, PF={pf:.2f}, {pips:+.1f} pips")

    # Walk-forward aggregate
    all_wf = []
    total_w = 0
    pos_w = 0
    for r in wf_results.values():
        total_w += len(r.windows)
        pos_w += r.oos_positive_windows
        for w in r.windows:
            if w.test_result:
                all_wf.extend(w.test_result.trades)
    if all_wf:
        w = [t for t in all_wf if t.pnl_pips > 0]
        l = [t for t in all_wf if t.pnl_pips <= 0]
        gp = sum(t.pnl_currency for t in w) if w else 0
        gl = abs(sum(t.pnl_currency for t in l)) if l else 0
        pf = gp / gl if gl > 0 else float("inf")
        wr = len(w) / len(all_wf) * 100
        pips = sum(t.pnl_pips for t in all_wf)
        pct = pos_w / total_w * 100 if total_w > 0 else 0
        print(f"    Walk-Forward: {len(all_wf)} trades, WR={wr:.1f}%, PF={pf:.2f}, "
              f"{pips:+.1f} pips, {pct:.0f}% windows +ve")

    print("\n  VERDICT:", end=" ")
    if all_wf:
        w = [t for t in all_wf if t.pnl_pips > 0]
        l = [t for t in all_wf if t.pnl_pips <= 0]
        gp = sum(t.pnl_currency for t in w) if w else 0
        gl = abs(sum(t.pnl_currency for t in l)) if l else 0
        pf = gp / gl if gl > 0 else float("inf")
        if pf >= 1.3:
            print(f"STRATEGY HAS EDGE (PF={pf:.2f})")
        elif pf >= 1.0:
            print(f"MARGINAL EDGE (PF={pf:.2f}) — may not survive slippage/spread")
        else:
            print(f"NO EDGE (PF={pf:.2f}) — strategy is flawed")


if __name__ == "__main__":
    main()
