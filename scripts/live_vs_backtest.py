"""
Compare live trades (Mar 25 - Apr 2) against what the backtest engine
would have done on the exact same price data.
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, "C:/")

from dotenv import load_dotenv
load_dotenv("C:/hvf_trader/.env")

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timezone, timedelta

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.backtest_engine import BacktestEngine

import logging
logging.basicConfig(level=logging.WARNING)

# Connect MT5
path = os.getenv("MT5_PATH")
login = int(os.getenv("MT5_LOGIN"))
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

if not mt5.initialize(path=path):
    print(f"MT5 init failed: {mt5.last_error()}")
    sys.exit(1)
if not mt5.login(login, password=password, server=server):
    print(f"MT5 login failed: {mt5.last_error()}")
    sys.exit(1)

# Get live trades from DB
conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()
cur.execute("""
    SELECT id, symbol, direction, entry_price, stop_loss, close_price,
           pnl, pnl_pips, close_reason, opened_at, closed_at, lot_size
    FROM trade_records
    WHERE status='CLOSED' AND pattern_type='KZ_HUNT' AND opened_at >= '2026-03-25'
    ORDER BY opened_at
""")
live_trades = cur.fetchall()
conn.close()

symbols = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
live_start = datetime(2026, 3, 25, tzinfo=timezone.utc)
live_end = datetime(2026, 4, 2, tzinfo=timezone.utc)

print("=" * 70)
print("LIVE vs BACKTEST COMPARISON: Mar 25 - Apr 2, 2026")
print("=" * 70)

# Print live trades summary
print(f"\n--- LIVE TRADES (KZ_HUNT, {len(live_trades)} closed) ---")
for t in live_trades:
    tid, sym, dirn, entry, sl, close, pnl, pips, reason, opened, closed_at, lots = t
    print(f"  #{tid:3d} {sym:6s} {dirn:5s} entry={entry:.5f} sl={sl:.5f} "
          f"close={close or 0:.5f} pnl=${pnl or 0:8.2f} pips={pips or 0:6.1f} {reason}")

live_wins = sum(1 for t in live_trades if t[6] and t[6] > 0)
live_pnl = sum(t[6] or 0 for t in live_trades)
live_pips = sum(t[7] or 0 for t in live_trades)
print(f"\n  LIVE TOTAL: {len(live_trades)}T, {live_wins}W, "
      f"WR={live_wins/len(live_trades)*100:.0f}%, PnL=${live_pnl:.2f}, Pips={live_pips:.1f}")

# Run backtest on same period for each pair
print(f"\n--- BACKTEST ON SAME PERIOD ---")
all_bt_trades = []

for symbol in symbols:
    # Fetch enough history for warmup (indicators need ~250 bars)
    # Get data from Jan 2025 to ensure we have enough
    rates = mt5.copy_rates_range(
        symbol, mt5.TIMEFRAME_H1,
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        live_end + timedelta(days=1)
    )
    if rates is None or len(rates) == 0:
        print(f"  {symbol}: NO DATA")
        continue

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)

    engine = BacktestEngine(starting_equity=10000.0, enabled_patterns=["KZ_HUNT"])
    result = engine.run(df, symbol)

    # Filter to live period only
    period_trades = [t for t in result.trades
                     if t.entry_time >= live_start and t.entry_time <= live_end]
    all_bt_trades.extend(period_trades)

    if period_trades:
        wins = sum(1 for t in period_trades if t.pnl_pips > 0)
        pnl = sum(t.pnl_pips for t in period_trades)
        print(f"\n  {symbol}: {len(period_trades)} trades, {wins}W, "
              f"WR={wins/len(period_trades)*100:.0f}%, Pips={pnl:+.1f}")
        for t in period_trades:
            print(f"    {t.direction:5s} entry={t.entry_price:.5f} sl={t.stop_loss:.5f} "
                  f"exit={t.exit_price:.5f} pips={t.pnl_pips:+6.1f} {t.exit_reason} "
                  f"score={t.score:.0f} time={t.entry_time.strftime('%m-%d %H:%M')}")
    else:
        # Check ALL trades for this symbol to see if backtest found any at all
        all_sym = [t for t in result.trades if t.entry_time >= datetime(2026, 3, 1, tzinfo=timezone.utc)]
        print(f"\n  {symbol}: 0 trades in live period ({len(all_sym)} in March 2026 total)")

# Backtest totals
bt_wins = sum(1 for t in all_bt_trades if t.pnl_pips > 0)
bt_pips = sum(t.pnl_pips for t in all_bt_trades)
bt_total = len(all_bt_trades)
print(f"\n  BACKTEST TOTAL: {bt_total}T, {bt_wins}W, "
      f"WR={bt_wins/bt_total*100:.0f}% Pips={bt_pips:+.1f}" if bt_total > 0 else "\n  BACKTEST TOTAL: 0 trades")

# Key comparison
print(f"\n{'='*70}")
print("COMPARISON SUMMARY")
print(f"{'='*70}")
print(f"  Live:     {len(live_trades):3d} trades, WR={live_wins/len(live_trades)*100:.0f}%, "
      f"Pips={live_pips:+.1f}")
if bt_total > 0:
    print(f"  Backtest: {bt_total:3d} trades, WR={bt_wins/bt_total*100:.0f}%, "
          f"Pips={bt_pips:+.1f}")
else:
    print(f"  Backtest: 0 trades")

# Check scan frequency difference
print(f"\n{'='*70}")
print("SCAN FREQUENCY CHECK")
print(f"{'='*70}")
print(f"  Backtest KZ_HUNT scan: every 24 bars (24 hours)")
print(f"  Live bot scan: every 60 seconds (every bar)")
print(f"  Backtest may miss patterns the live bot catches due to coarser scan interval")

# Check backtest overall stats for this data (full history)
print(f"\n{'='*70}")
print("FULL BACKTEST STATS (all available history)")
print(f"{'='*70}")
for symbol in symbols:
    rates = mt5.copy_rates_range(
        symbol, mt5.TIMEFRAME_H1,
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        live_end + timedelta(days=1)
    )
    if rates is None:
        continue
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)

    engine = BacktestEngine(starting_equity=10000.0, enabled_patterns=["KZ_HUNT"])
    result = engine.run(df, symbol)

    if result.total_trades > 0:
        print(f"  {symbol}: {result.total_trades}T, WR={result.win_rate:.0f}%, "
              f"PF={result.profit_factor:.2f}, Pips={result.total_pnl_pips:+.1f}, "
              f"MaxDD={result.max_drawdown_pct:.1f}%")

mt5.shutdown()
print("\nDone.")
