"""
Repair 4 trades with close_reason=UNKNOWN and pnl=0.0.
Queries MT5 deal history for actual close prices and updates the DB.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 not available")
    exit(1)

DB_PATH = r"C:\hvf_trader\hvf_trader.db"

PIP_VALUES = {
    "EURUSD": 0.0001,
    "NZDUSD": 0.0001,
    "EURGBP": 0.0001,
    "USDCHF": 0.0001,
    "EURAUD": 0.0001,
}

TRADES_TO_REPAIR = [
    {"id": 77, "symbol": "EURAUD", "direction": "SHORT", "ticket": 1576264449, "entry": 1.6675,
     "opened": "2026-04-07 00:29:26", "closed": "2026-04-07 01:39:57"},
    {"id": 79, "symbol": "EURUSD", "direction": "SHORT", "ticket": 1577754225, "entry": 1.1559,
     "opened": "2026-04-07 13:29:48", "closed": "2026-04-07 14:34:50"},
    {"id": 86, "symbol": "EURUSD", "direction": "LONG", "ticket": 1582213934, "entry": 1.16669,
     "opened": "2026-04-09 05:00:03", "closed": "2026-04-09 06:17:28"},
    {"id": 88, "symbol": "USDCHF", "direction": "LONG", "ticket": 1583879245, "entry": 0.79056,
     "opened": "2026-04-09 18:33:58", "closed": "2026-04-09 21:01:38"},
]


def find_close_deal(trade):
    """Search MT5 deal history for the close deal matching this trade."""
    opened = datetime.strptime(trade["opened"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    search_from = opened - timedelta(minutes=5)
    search_to = opened + timedelta(hours=6)

    deals = mt5.history_deals_get(search_from, search_to)
    if not deals:
        # Broader search
        deals = mt5.history_deals_get(opened - timedelta(hours=1), opened + timedelta(hours=24))
    if not deals:
        return None

    # Expected close deal type: SELL for LONG (type=1), BUY for SHORT (type=0)
    expected_type = 1 if trade["direction"] == "LONG" else 0

    # Pass 1: exact position_id match
    for deal in deals:
        if deal.position_id == trade["ticket"] and deal.symbol == trade["symbol"]:
            if deal.type == expected_type:
                return deal

    # Pass 2: fallback — match by symbol, type, and time window
    for deal in deals:
        if deal.symbol != trade["symbol"]:
            continue
        if deal.type != expected_type:
            continue
        if deal.entry not in (0, 1):
            continue
        deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
        closed_approx = datetime.strptime(trade["closed"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if abs((deal_time - closed_approx).total_seconds()) < 120:
            return deal

    return None


def main():
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    repaired = 0

    for trade in TRADES_TO_REPAIR:
        print(f"\n--- Trade #{trade['id']} ({trade['symbol']} {trade['direction']}) ---")
        deal = find_close_deal(trade)

        if not deal:
            print(f"  NO MATCHING DEAL FOUND")
            continue

        close_price = deal.price
        pnl = deal.profit
        pip_value = PIP_VALUES.get(trade["symbol"], 0.0001)

        if trade["direction"] == "LONG":
            pnl_pips = (close_price - trade["entry"]) / pip_value
        else:
            pnl_pips = (trade["entry"] - close_price) / pip_value

        close_reason = "STOP_LOSS" if pnl < 0 else "TAKE_PROFIT"

        print(f"  Deal found: ticket={deal.ticket}, position_id={deal.position_id}")
        print(f"  Close price: {close_price} (was {trade['entry']})")
        print(f"  PnL: ${pnl:.2f} ({pnl_pips:+.1f} pips)")
        print(f"  Close reason: {close_reason}")

        cur.execute(
            "UPDATE trade_records SET close_price=?, pnl=?, pnl_pips=?, close_reason=? WHERE id=?",
            (close_price, pnl, pnl_pips, close_reason, trade["id"]),
        )
        repaired += 1

    conn.commit()
    conn.close()
    mt5.shutdown()
    print(f"\n=== Repaired {repaired}/{len(TRADES_TO_REPAIR)} trades ===")


if __name__ == "__main__":
    main()
