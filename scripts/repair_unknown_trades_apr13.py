"""Repair 6 UNKNOWN/0.0 PnL trades from Apr 10-13."""
import sys, os
sys.path.insert(0, "C:/")
os.chdir("C:\\hvf_trader")

from dotenv import load_dotenv
load_dotenv("C:\\hvf_trader\\.env")

import MetaTrader5 as mt5
import sqlite3
from datetime import datetime, timezone, timedelta

path = os.getenv("MT5_PATH")
login = int(os.getenv("MT5_LOGIN"))
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

if not mt5.initialize(path=path):
    print("MT5 init failed:", mt5.last_error())
    sys.exit(1)
if not mt5.login(login, password=password, server=server):
    print("MT5 login failed:", mt5.last_error())
    sys.exit(1)
print("MT5 connected")

PIP_VALUES = {
    "EURUSD": 0.0001, "NZDUSD": 0.0001, "EURGBP": 0.0001,
    "USDCHF": 0.0001, "EURAUD": 0.0001, "GBPJPY": 0.01,
    "EURJPY": 0.01, "CHFJPY": 0.01,
}

# Trades to repair: (id, symbol, direction, entry_price, stop_loss, opened_at, closed_at)
TRADES = [
    (92, "EURGBP", "SHORT", 0.87097, 0.87178, "2026-04-10 15:36:51", "2026-04-12 21:01:44"),
    (93, "USDCHF", "SHORT", 0.78936, 0.79114, "2026-04-10 17:16:17", "2026-04-12 21:01:45"),
    (96, "CHFJPY", "SHORT", 201.67, 201.88, "2026-04-13 03:00:15", "2026-04-13 07:00:40"),
    (98, "EURAUD", "SHORT", 1.65703, 1.65891, "2026-04-13 08:03:34", "2026-04-13 09:39:19"),
    (99, "USDCHF", "SHORT", 0.78935, 0.79111, "2026-04-13 11:15:23", "2026-04-13 12:00:43"),
    (101, "EURAUD", "SHORT", 1.65715, 1.65893, "2026-04-13 14:21:59", "2026-04-13 16:08:22"),
]

conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()

# Get lot sizes for these trades
for trade_id, sym, direction, entry, sl, opened, closed in TRADES:
    cur.execute("SELECT lot_size, mt5_ticket, partial_closed FROM trade_records WHERE id = ?", (trade_id,))
    row = cur.fetchone()
    lot_size = row[0] if row else 0.0
    mt5_ticket = row[1] if row else None
    partial_closed = row[2] if row and len(row) > 2 else False

    # Search deals around close time
    close_dt = datetime.strptime(closed, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    search_from = close_dt - timedelta(hours=2)
    search_to = close_dt + timedelta(hours=2)

    deals = mt5.history_deals_get(search_from, search_to)
    if deals is None:
        deals = []

    # Filter for this symbol
    sym_deals = [d for d in deals if d.symbol == sym]

    # For SHORT: close deal is type 0 (BUY)
    close_type = 0 if direction == "SHORT" else 1
    close_deals = [d for d in sym_deals if d.type == close_type and d.entry == 1]  # entry=1 means exit deal

    print("\n--- Trade #%d: %s %s entry=%.5f SL=%.5f ---" % (trade_id, sym, direction, entry, sl))
    print("  Opened: %s  Closed: %s" % (opened, closed))
    print("  Lot size: %.2f  MT5 ticket: %s  Partial: %s" % (lot_size, mt5_ticket, partial_closed))
    print("  Deals found for %s around close time: %d total, %d exit deals" % (sym, len(sym_deals), len(close_deals)))

    for d in close_deals:
        deal_time = datetime.fromtimestamp(d.time, tz=timezone.utc)
        print("    Deal: ticket=%d time=%s price=%.5f volume=%.2f profit=%.2f comment=%s position=%d" % (
            d.ticket, deal_time.strftime("%Y-%m-%d %H:%M:%S"), d.price, d.volume, d.profit, d.comment, d.position_id))

    # Try to match by ticket
    matched_deal = None
    if mt5_ticket:
        ticket_deals = [d for d in close_deals if d.position_id == mt5_ticket]
        if ticket_deals:
            matched_deal = ticket_deals[-1]  # Last exit deal
            print("  -> Matched by position_id=%d" % mt5_ticket)

    # If no ticket match, find closest by time
    if not matched_deal and close_deals:
        close_deals.sort(key=lambda d: abs(d.time - close_dt.timestamp()))
        matched_deal = close_deals[0]
        print("  -> Matched by closest time")

    if matched_deal:
        close_price = matched_deal.price
        pip_val = PIP_VALUES.get(sym, 0.0001)

        if direction == "SHORT":
            pnl_pips = (entry - close_price) / pip_val
        else:
            pnl_pips = (close_price - entry) / pip_val

        # Use MT5 profit if available
        mt5_profit = matched_deal.profit

        # Determine close reason from SL proximity
        sl_dist_pips = abs(close_price - sl) / pip_val
        entry_dist_pips = abs(close_price - entry) / pip_val

        if sl_dist_pips < 2.0:
            close_reason = "STOP_LOSS"
        elif entry_dist_pips < 2.0:
            close_reason = "BREAKEVEN"
        elif pnl_pips > 5:
            close_reason = "TRAILING_STOP"
        elif pnl_pips < -3:
            close_reason = "STOP_LOSS"
        else:
            close_reason = "INVALIDATION"

        print("  REPAIR: close_price=%.5f pnl_pips=%+.1f mt5_profit=%.2f reason=%s" % (
            close_price, pnl_pips, mt5_profit, close_reason))

        # Check for partial close deals (to get total PnL)
        all_exit_deals = [d for d in sym_deals if d.entry == 1 and (not mt5_ticket or d.position_id == mt5_ticket)]
        total_mt5_profit = sum(d.profit for d in all_exit_deals) if mt5_ticket and all_exit_deals else mt5_profit
        if len(all_exit_deals) > 1:
            print("  Multiple exit deals (split order): %d deals, total profit=%.2f" % (len(all_exit_deals), total_mt5_profit))

        cur.execute(
            "UPDATE trade_records SET close_price = ?, pnl = ?, pnl_pips = ?, close_reason = ? WHERE id = ?",
            (close_price, total_mt5_profit if total_mt5_profit != 0 else mt5_profit, pnl_pips, close_reason, trade_id)
        )
        print("  -> UPDATED")
    else:
        # Estimate from SL (all these are SHORT, SL above entry)
        # If closed quickly, likely invalidation or SL
        duration_hours = (close_dt - datetime.strptime(opened, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        print("  NO DEAL FOUND. Duration: %.1f hours" % duration_hours)
        print("  Will estimate at SL price as worst case")

        close_price = sl
        pip_val = PIP_VALUES.get(sym, 0.0001)
        pnl_pips = (entry - close_price) / pip_val if direction == "SHORT" else (close_price - entry) / pip_val

        print("  ESTIMATE: close_price=%.5f pnl_pips=%+.1f reason=STOP_LOSS (estimated)" % (close_price, pnl_pips))

        cur.execute(
            "UPDATE trade_records SET close_price = ?, pnl_pips = ?, close_reason = ? WHERE id = ?",
            (close_price, pnl_pips, "STOP_LOSS", trade_id)
        )
        print("  -> UPDATED (estimated)")

conn.commit()
conn.close()
mt5.shutdown()

print("\n=== Done. Repaired %d trades ===" % len(TRADES))
