"""
Entry gap analysis: Compare live entry prices vs what backtest would have entered.
Also compares SL placement, close reasons, and quantifies the pip gap sources.
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
sys.path.insert(0, "C:/")
from dotenv import load_dotenv
load_dotenv("C:/hvf_trader/.env")

import MetaTrader5 as mt5
import sqlite3
from datetime import datetime, timedelta, timezone
from hvf_trader import config

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

conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all KZ_HUNT trades with pattern data
cur.execute("""
    SELECT t.id, t.symbol, t.direction, t.entry_price, t.stop_loss,
           t.target_1, t.target_2, t.close_price, t.pnl, t.pnl_pips,
           t.close_reason, t.opened_at, t.closed_at,
           t.pattern_id, t.lot_size,
           p.h3_price as kz_high, p.l3_price as kz_low,
           p.detected_at as pattern_detected_at
    FROM trade_records t
    LEFT JOIN pattern_records p ON t.pattern_id = p.id
    WHERE t.status='CLOSED' AND t.pattern_type='KZ_HUNT'
      AND t.opened_at >= '2026-03-25'
    ORDER BY t.opened_at
""")
trades = [dict(r) for r in cur.fetchall()]
conn.close()

print(f"\n{len(trades)} live KZ_HUNT trades since go-live\n", flush=True)

# For each trade, get the H1 bar at entry time and compute what backtest would have done
print("=" * 100, flush=True)
print(f"{'ID':>3} {'SYM':7} {'DIR':5} {'LIVE_ENTRY':>10} {'BAR_CLOSE':>10} {'ENTRY_GAP':>9} "
      f"{'LIVE_SL':>10} {'BT_SL_EST':>10} {'SL_GAP':>8} {'LIVE_PnL':>8} {'REASON':15}", flush=True)
print("=" * 100, flush=True)

total_entry_gap_pips = 0
total_sl_gap_pips = 0
entry_gaps_by_pair = {}
trades_with_worse_entry = 0
trades_with_better_entry = 0

for t in trades:
    opened = datetime.strptime(t["opened_at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    # Get the H1 bar that contains the entry time
    bar_start = opened.replace(minute=0, second=0, microsecond=0)
    rates = mt5.copy_rates_range(t["symbol"], mt5.TIMEFRAME_H1,
                                  bar_start - timedelta(hours=2), bar_start + timedelta(hours=2))

    pip_val = config.PIP_VALUES.get(t["symbol"], 0.0001)
    bar_close = None
    bar_atr = None

    if rates is not None and len(rates) > 0:
        # Find the bar whose time matches (or is closest to) the entry
        import pandas as pd
        for r in rates:
            bar_time = datetime.fromtimestamp(r["time"], tz=timezone.utc)
            if bar_time <= opened < bar_time + timedelta(hours=1):
                bar_close = r["close"]
                break
        # If no exact match, use closest bar before entry
        if bar_close is None:
            for r in reversed(rates):
                bar_time = datetime.fromtimestamp(r["time"], tz=timezone.utc)
                if bar_time <= opened:
                    bar_close = r["close"]
                    break

    if bar_close is None:
        print(f"#{t['id']:3d} {t['symbol']:7s} {t['direction']:5s} NO BAR DATA", flush=True)
        continue

    # Entry gap: live entry vs bar close (what backtest uses)
    entry_gap = t["entry_price"] - bar_close
    entry_gap_pips = entry_gap / pip_val

    # For direction: positive gap = worse for trade
    if t["direction"] == "LONG":
        # LONG: higher entry = worse
        entry_gap_directional = entry_gap_pips
    else:
        # SHORT: lower entry = worse (negative gap = worse)
        entry_gap_directional = -entry_gap_pips

    total_entry_gap_pips += entry_gap_directional
    if entry_gap_directional > 0.1:
        trades_with_worse_entry += 1
    elif entry_gap_directional < -0.1:
        trades_with_better_entry += 1

    pair = t["symbol"]
    if pair not in entry_gaps_by_pair:
        entry_gaps_by_pair[pair] = []
    entry_gaps_by_pair[pair].append(entry_gap_directional)

    # Estimate what backtest SL would be
    # Backtest: spread_price = pip_val * 1.5
    spread_sim = pip_val * 1.5
    # We can't easily get the exact ATR at entry from here, but we can compare
    # live SL vs entry to see the risk taken
    live_risk = abs(t["entry_price"] - t["stop_loss"])
    bt_risk_est = live_risk  # rough estimate

    sl_gap = (abs(t["entry_price"] - t["stop_loss"]) - abs(bar_close - t["stop_loss"])) / pip_val

    print(f"#{t['id']:3d} {t['symbol']:7s} {t['direction']:5s} "
          f"{t['entry_price']:10.5f} {bar_close:10.5f} {entry_gap_directional:+8.1f}p "
          f"{t['stop_loss']:10.5f} {'':>10s} {'':>8s} "
          f"{t['pnl_pips'] or 0:+7.1f}p {t['close_reason']:15s}", flush=True)

print("=" * 100, flush=True)

# Summary
print(f"\n{'='*60}", flush=True)
print("ENTRY GAP ANALYSIS SUMMARY", flush=True)
print(f"{'='*60}", flush=True)
print(f"Total trades analyzed: {len(trades)}", flush=True)
print(f"Trades with worse entry (live): {trades_with_worse_entry}", flush=True)
print(f"Trades with better entry (live): {trades_with_better_entry}", flush=True)
print(f"Total entry gap (directional): {total_entry_gap_pips:+.1f} pips", flush=True)
print(f"Average entry gap per trade: {total_entry_gap_pips/len(trades):+.2f} pips", flush=True)
print(f"Entry gap as % of total 472-pip gap: {abs(total_entry_gap_pips)/472*100:.1f}%", flush=True)

print(f"\nPer-pair entry gap:", flush=True)
for pair in sorted(entry_gaps_by_pair.keys()):
    gaps = entry_gaps_by_pair[pair]
    avg = sum(gaps) / len(gaps)
    total = sum(gaps)
    print(f"  {pair}: {len(gaps)} trades, avg={avg:+.2f}p, total={total:+.1f}p", flush=True)

# Now analyze close reason differences
# Get pattern detection timestamps to check if live detected patterns earlier/later
print(f"\n{'='*60}", flush=True)
print("DETECTION TIMING ANALYSIS", flush=True)
print(f"{'='*60}", flush=True)

for t in trades:
    if t["pattern_detected_at"]:
        detected = datetime.strptime(t["pattern_detected_at"][:19], "%Y-%m-%d %H:%M:%S")
        opened = datetime.strptime(t["opened_at"][:19], "%Y-%m-%d %H:%M:%S")
        gap_hours = (opened - detected).total_seconds() / 3600
        if gap_hours > 24 or gap_hours < 0:
            print(f"  #{t['id']:3d} {t['symbol']:7s} detected-to-entry: {gap_hours:.1f}h (unusual)", flush=True)

# Analyze the 30s vs H1 bar management difference
# Check: for trades closed by INVALIDATION, how long were they open?
print(f"\n{'='*60}", flush=True)
print("INVALIDATION TIMING ANALYSIS", flush=True)
print(f"{'='*60}", flush=True)
inv_trades = [t for t in trades if t["close_reason"] == "INVALIDATION"]
for t in inv_trades:
    opened = datetime.strptime(t["opened_at"][:19], "%Y-%m-%d %H:%M:%S")
    closed = datetime.strptime(t["closed_at"][:19], "%Y-%m-%d %H:%M:%S")
    duration_h = (closed - opened).total_seconds() / 3600
    print(f"  #{t['id']:3d} {t['symbol']:7s} {t['direction']:5s} open={duration_h:.1f}h "
          f"pnl={t['pnl_pips'] or 0:+.1f}p close_price={t['close_price']:.5f} "
          f"kz_low={t.get('kz_low', 'N/A')} kz_high={t.get('kz_high', 'N/A')}", flush=True)

# Check for trades closed BETWEEN bars (intra-bar close)
print(f"\n{'='*60}", flush=True)
print("INTRA-BAR CLOSE ANALYSIS", flush=True)
print(f"{'='*60}", flush=True)
print("Trades where live closed mid-bar (minute != 0):", flush=True)
intra_bar_count = 0
for t in trades:
    closed = datetime.strptime(t["closed_at"][:19], "%Y-%m-%d %H:%M:%S")
    if closed.minute != 0 or closed.second != 0:
        intra_bar_count += 1
        opened = datetime.strptime(t["opened_at"][:19], "%Y-%m-%d %H:%M:%S")
        # Check: would this trade have been closed at this point in backtest?
        # Backtest only checks at bar boundaries
        print(f"  #{t['id']:3d} {t['symbol']:7s} {t['direction']:5s} "
              f"closed at {closed.strftime('%H:%M:%S')} ({t['close_reason']}) "
              f"pnl={t['pnl_pips'] or 0:+.1f}p", flush=True)

print(f"\nTotal intra-bar closes: {intra_bar_count}/{len(trades)} "
      f"({intra_bar_count/len(trades)*100:.0f}%)", flush=True)
print("These trades were closed at a sub-bar level that the backtest can't replicate.", flush=True)

mt5.shutdown()
print("\nDone.", flush=True)
