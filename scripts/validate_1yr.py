"""
Run KZ_HUNT backtest on all 5 pairs for the last year with realistic
settings matching live bot behavior.
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

symbols = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
end_date = datetime(2026, 4, 2, tzinfo=timezone.utc)
# 1 year of test data + 250 bars warmup for indicators
start_date = end_date - timedelta(days=365 + 30)

print("=" * 70)
print("KZ_HUNT 1-YEAR VALIDATION (realistic backtest matching live)")
print(f"Period: {(end_date - timedelta(days=365)).strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
print(f"Scan: every bar | Spread: 1.5 pip simulated | Min stop: 8 pips")
print(f"RRR >= 1.0 | Same-symbol dedup: ON")
print("=" * 70)

all_trades = []
results_by_pair = {}

for symbol in symbols:
    rates = mt5.copy_rates_range(
        symbol, mt5.TIMEFRAME_H1,
        start_date,
        end_date + timedelta(days=1)
    )
    if rates is None or len(rates) == 0:
        print(f"\n{symbol}: NO DATA")
        continue

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)

    # Filter to last 1 year for reporting (engine needs warmup bars before)
    one_year_ago = end_date - timedelta(days=365)

    engine = BacktestEngine(starting_equity=10000.0, enabled_patterns=["KZ_HUNT"])
    result = engine.run(df, symbol)

    # Filter trades to last 1 year
    period_trades = [t for t in result.trades if t.entry_time >= one_year_ago]
    all_trades.extend(period_trades)

    wins = sum(1 for t in period_trades if t.pnl_pips > 0)
    losses = len(period_trades) - wins
    pnl_pips = sum(t.pnl_pips for t in period_trades)
    gross_win = sum(t.pnl_pips for t in period_trades if t.pnl_pips > 0)
    gross_loss = abs(sum(t.pnl_pips for t in period_trades if t.pnl_pips <= 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    wr = wins / len(period_trades) * 100 if period_trades else 0

    results_by_pair[symbol] = {
        "trades": len(period_trades), "wins": wins, "wr": wr,
        "pf": pf, "pips": pnl_pips, "gross_win": gross_win, "gross_loss": gross_loss,
    }

    print(f"\n{'='*50}")
    print(f"{symbol}: {len(period_trades)} trades, {wins}W/{losses}L, "
          f"WR={wr:.0f}%, PF={pf:.2f}, Pips={pnl_pips:+.1f}")

    # By direction
    longs = [t for t in period_trades if t.direction == "LONG"]
    shorts = [t for t in period_trades if t.direction == "SHORT"]
    for label, subset in [("LONG", longs), ("SHORT", shorts)]:
        if subset:
            sw = sum(1 for t in subset if t.pnl_pips > 0)
            sp = sum(t.pnl_pips for t in subset)
            print(f"  {label}: {len(subset)}T, {sw}W, WR={sw/len(subset)*100:.0f}%, Pips={sp:+.1f}")

    # By exit reason
    reasons = {}
    for t in period_trades:
        r = t.exit_reason
        if r not in reasons:
            reasons[r] = {"count": 0, "pips": 0}
        reasons[r]["count"] += 1
        reasons[r]["pips"] += t.pnl_pips
    print("  Exit reasons:")
    for r, v in sorted(reasons.items(), key=lambda x: x[1]["count"], reverse=True):
        print(f"    {r:15s}: {v['count']:3d}T, Pips={v['pips']:+.1f}")

    # Monthly breakdown
    monthly = {}
    for t in period_trades:
        m = t.entry_time.strftime("%Y-%m")
        if m not in monthly:
            monthly[m] = {"trades": 0, "wins": 0, "pips": 0}
        monthly[m]["trades"] += 1
        if t.pnl_pips > 0:
            monthly[m]["wins"] += 1
        monthly[m]["pips"] += t.pnl_pips
    print("  Monthly:")
    for m in sorted(monthly.keys()):
        v = monthly[m]
        mwr = v["wins"]/v["trades"]*100 if v["trades"] else 0
        print(f"    {m}: {v['trades']:3d}T, WR={mwr:.0f}%, Pips={v['pips']:+.1f}")

# Overall summary
print(f"\n{'='*70}")
print("OVERALL SUMMARY (all 5 pairs)")
print(f"{'='*70}")

total = len(all_trades)
total_wins = sum(1 for t in all_trades if t.pnl_pips > 0)
total_pips = sum(t.pnl_pips for t in all_trades)
total_gw = sum(t.pnl_pips for t in all_trades if t.pnl_pips > 0)
total_gl = abs(sum(t.pnl_pips for t in all_trades if t.pnl_pips <= 0))
total_pf = total_gw / total_gl if total_gl > 0 else float('inf')
total_wr = total_wins / total * 100 if total else 0

print(f"Total trades: {total}")
print(f"Wins: {total_wins}, Losses: {total - total_wins}")
print(f"Win Rate: {total_wr:.1f}%")
print(f"Profit Factor: {total_pf:.2f}")
print(f"Total Pips: {total_pips:+.1f}")
print(f"Avg Win: {total_gw/total_wins:.1f} pips" if total_wins else "Avg Win: N/A")
print(f"Avg Loss: {total_gl/(total-total_wins):.1f} pips" if total > total_wins else "Avg Loss: N/A")

# Per-pair summary table
print(f"\nPer-pair breakdown:")
print(f"  {'Pair':8s} {'Trades':>6s} {'WR':>5s} {'PF':>6s} {'Pips':>8s}")
for sym in symbols:
    if sym in results_by_pair:
        r = results_by_pair[sym]
        print(f"  {sym:8s} {r['trades']:6d} {r['wr']:4.0f}% {r['pf']:6.2f} {r['pips']:+8.1f}")

# Equity curve stats
equity = 10000.0
peak = equity
max_dd = 0
max_dd_pct = 0
for t in sorted(all_trades, key=lambda x: x.entry_time):
    # Approximate PnL currency from pips (simplified)
    pip_val = config.PIP_VALUES.get(t.symbol, 0.0001)
    pnl_currency = t.pnl_pips * pip_val * t.lot_size * 100000
    equity += pnl_currency
    if equity > peak:
        peak = equity
    dd = peak - equity
    dd_pct = dd / peak * 100 if peak > 0 else 0
    if dd_pct > max_dd_pct:
        max_dd_pct = dd_pct
        max_dd = dd

print(f"\nMax Drawdown: ${max_dd:.0f} ({max_dd_pct:.1f}%)")
print(f"Final Equity: ${equity:.0f} (started $10,000)")

# Consecutive losses
max_consec = 0
current_consec = 0
for t in sorted(all_trades, key=lambda x: x.entry_time):
    if t.pnl_pips <= 0:
        current_consec += 1
        max_consec = max(max_consec, current_consec)
    else:
        current_consec = 0
print(f"Max Consecutive Losses: {max_consec}")

# Compare to old backtest
print(f"\n{'='*70}")
print("vs PREVIOUS WALK-FORWARD (scan every 24 bars, no spread/RRR/dedup)")
print(f"{'='*70}")
print(f"  Old: PF=1.53, WR=61%, 4656 trades (11.3yr)")
print(f"  New: PF={total_pf:.2f}, WR={total_wr:.0f}%, {total} trades (1yr)")
if total_pf < 1.0:
    print(f"  VERDICT: Strategy is NOT profitable with realistic settings")
elif total_pf < 1.15:
    print(f"  VERDICT: Marginal edge, likely unprofitable after slippage/commissions")
else:
    print(f"  VERDICT: Edge survives realistic settings (degraded from {1.53:.2f} to {total_pf:.2f})")

mt5.shutdown()
print("\nDone.")
