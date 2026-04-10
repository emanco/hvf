"""
Quick backtest: Mar 25 - Apr 10 only, with 250-bar warmup.
Output is immediate per pair (no buffering issues).
"""
import sys, os, io
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
sys.path.insert(0, "C:/")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from dotenv import load_dotenv
load_dotenv("C:/hvf_trader/.env")

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone, timedelta

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.backtest_engine import BacktestEngine

import logging
logging.basicConfig(level=logging.WARNING)

path = os.getenv("MT5_PATH")
login = int(os.getenv("MT5_LOGIN"))
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

if not mt5.initialize(path=path):
    print(f"MT5 init failed: {mt5.last_error()}", flush=True)
    sys.exit(1)
if not mt5.login(login, password=password, server=server):
    print(f"MT5 login failed: {mt5.last_error()}", flush=True)
    sys.exit(1)

print("MT5 connected", flush=True)

symbols = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
live_start = datetime(2026, 3, 25, tzinfo=timezone.utc)
live_end = datetime(2026, 4, 10, 23, 59, tzinfo=timezone.utc)
# 300 bars warmup before live period
data_start = live_start - timedelta(hours=500)

all_bt = []

for symbol in symbols:
    print(f"\nProcessing {symbol}...", flush=True)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, data_start, live_end)
    if rates is None or len(rates) == 0:
        print(f"  {symbol}: NO DATA", flush=True)
        continue

    print(f"  {symbol}: {len(rates)} bars loaded", flush=True)
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    print(f"  {symbol}: {len(df)} bars after indicators", flush=True)

    engine = BacktestEngine(starting_equity=10000.0, enabled_patterns=["KZ_HUNT"])
    result = engine.run(df, symbol)

    period_trades = [t for t in result.trades
                     if t.entry_time >= live_start and t.entry_time <= live_end]
    all_bt.extend(period_trades)

    if period_trades:
        wins = sum(1 for t in period_trades if t.pnl_pips > 0)
        pips = sum(t.pnl_pips for t in period_trades)
        gw = sum(t.pnl_pips for t in period_trades if t.pnl_pips > 0)
        gl = abs(sum(t.pnl_pips for t in period_trades if t.pnl_pips <= 0))
        pf = gw / gl if gl > 0 else float('inf')
        inv = sum(1 for t in period_trades if t.exit_reason == "INVALIDATION")
        print(f"  {symbol}: {len(period_trades)}T, {wins}W, WR={wins/len(period_trades)*100:.0f}%, "
              f"PF={pf:.2f}, Pips={pips:+.1f}, Inval={inv}", flush=True)
        for t in period_trades:
            print(f"    {t.entry_time.strftime('%m-%d %H:%M')} {t.direction:5s} "
                  f"entry={t.entry_price:.5f} sl={t.stop_loss:.5f} "
                  f"exit={t.exit_price:.5f} pips={t.pnl_pips:+6.1f} {t.exit_reason} "
                  f"score={t.score:.0f}", flush=True)
    else:
        print(f"  {symbol}: 0 trades in live period", flush=True)

# Summary
print(f"\n{'='*60}", flush=True)
print("BACKTEST SUMMARY: Mar 25 - Apr 10, 2026", flush=True)
print(f"{'='*60}", flush=True)
total = len(all_bt)
if total > 0:
    wins = sum(1 for t in all_bt if t.pnl_pips > 0)
    pips = sum(t.pnl_pips for t in all_bt)
    gw = sum(t.pnl_pips for t in all_bt if t.pnl_pips > 0)
    gl = abs(sum(t.pnl_pips for t in all_bt if t.pnl_pips <= 0))
    pf = gw / gl if gl > 0 else float('inf')
    inv = sum(1 for t in all_bt if t.exit_reason == "INVALIDATION")
    print(f"Total: {total}T, {wins}W/{total-wins}L, WR={wins/total*100:.0f}%, "
          f"PF={pf:.2f}, Pips={pips:+.1f}", flush=True)
    print(f"Invalidation exits: {inv} ({inv/total*100:.0f}%)", flush=True)
    print(f"Avg win: {gw/wins:.1f}p, Avg loss: {gl/(total-wins):.1f}p" if wins > 0 and total > wins else "", flush=True)

    # By exit reason
    reasons = {}
    for t in all_bt:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    print("\nExit reasons:", flush=True)
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:15s}: {c}", flush=True)
else:
    print("NO TRADES IN PERIOD", flush=True)

# Live comparison
print(f"\n{'='*60}", flush=True)
print("LIVE vs BACKTEST (same period)", flush=True)
print(f"{'='*60}", flush=True)
import sqlite3
conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()
cur.execute("""
    SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
           SUM(pnl), SUM(pnl_pips)
    FROM trade_records
    WHERE status='CLOSED' AND pattern_type='KZ_HUNT' AND opened_at >= '2026-03-25'
""")
row = cur.fetchone()
conn.close()

lt, lw, lpnl, lpips = row
lwr = (lw / lt * 100) if lt and lw else 0
print(f"Live:     {lt}T, {lw}W, WR={lwr:.0f}%, PnL=${lpnl:.2f}, Pips={lpips:.1f}", flush=True)
if total > 0:
    print(f"Backtest: {total}T, {wins}W, WR={wins/total*100:.0f}%, Pips={pips:+.1f}, PF={pf:.2f}", flush=True)
    if wins/total*100 > 50 and lwr < 40:
        print("\n** BACKTEST PROFITABLE, LIVE NOT -> structural live-vs-backtest gap **", flush=True)
    elif wins/total*100 < 40:
        print("\n** BACKTEST ALSO POOR -> bad regime, not implementation bug **", flush=True)
    else:
        print("\n** Results comparable **", flush=True)

mt5.shutdown()
print("\nDone.", flush=True)
