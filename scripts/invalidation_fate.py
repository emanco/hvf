"""
Invalidation Fate Analysis: What would have happened to the 19 invalidation-closed trades
if the invalidation logic had NOT closed them?

For each trade, fetches H1 price data after the close and checks whether price
would have hit T1/T2 (winner) or SL (loser) first.
"""
import sqlite3
import json
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 not available")
    exit(1)

DB_PATH = r"C:\hvf_trader\hvf_trader.db"
LOOKAHEAD_HOURS = 72  # Check up to 72 hours after invalidation close


def get_invalidation_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss, target_1, target_2,
               close_price, pnl, pnl_pips, closed_at, opened_at
        FROM trade_records
        WHERE close_reason = 'INVALIDATION'
          AND opened_at >= '2026-03-25'
        ORDER BY id
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def check_fate(trade):
    """Check what would have happened if the trade stayed open."""
    closed_at = datetime.strptime(trade["closed_at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    end_time = closed_at + timedelta(hours=LOOKAHEAD_HOURS)

    rates = mt5.copy_rates_range(trade["symbol"], mt5.TIMEFRAME_H1, closed_at, end_time)
    if rates is None or len(rates) == 0:
        return {"fate": "NO_DATA", "bars_checked": 0}

    direction = trade["direction"]
    sl = trade["stop_loss"]
    t1 = trade["target_1"]
    t2 = trade["target_2"]

    for i, bar in enumerate(rates):
        high = bar["high"]
        low = bar["low"]

        if direction == "LONG":
            if low <= sl:
                return {"fate": "SL_HIT", "bars": i + 1, "note": "Invalidation SAVED us"}
            if high >= t2:
                return {"fate": "T2_HIT", "bars": i + 1, "note": "Invalidation KILLED a full winner"}
            if high >= t1:
                # Would have hit T1 (partial), check if SL or T2 next
                return {"fate": "T1_HIT", "bars": i + 1, "note": "Invalidation KILLED a partial winner"}
        else:  # SHORT
            if high >= sl:
                return {"fate": "SL_HIT", "bars": i + 1, "note": "Invalidation SAVED us"}
            if low <= t2:
                return {"fate": "T2_HIT", "bars": i + 1, "note": "Invalidation KILLED a full winner"}
            if low <= t1:
                return {"fate": "T1_HIT", "bars": i + 1, "note": "Invalidation KILLED a partial winner"}

    return {"fate": "NEITHER", "bars": len(rates), "note": "Neither SL nor T1/T2 hit in 72h"}


def main():
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}")
        return

    trades = get_invalidation_trades()
    print(f"Found {len(trades)} invalidation-closed trades\n")

    results = {"SL_HIT": 0, "T1_HIT": 0, "T2_HIT": 0, "NEITHER": 0, "NO_DATA": 0}
    saved_pnl = 0.0  # PnL saved by invalidation (would-be SL losses avoided)
    killed_pnl = 0.0  # Potential PnL killed by invalidation

    for trade in trades:
        fate = check_fate(trade)
        results[fate["fate"]] += 1

        actual_pnl = trade["pnl"] or 0
        print(f"  #{trade['id']:3d} {trade['symbol']:7s} {trade['direction']:5s} "
              f"PnL=${actual_pnl:+8.2f} ({trade['pnl_pips']:+6.1f}p) -> {fate['fate']:8s} "
              f"in {fate.get('bars', '?'):>3} bars | {fate.get('note', '')}")

        if fate["fate"] == "SL_HIT":
            # Invalidation saved us from a full SL loss
            # Estimate: SL loss would have been worse than invalidation PnL
            pip_val = 0.0001
            if trade["direction"] == "LONG":
                sl_pips = (trade["entry_price"] - trade["stop_loss"]) / pip_val
            else:
                sl_pips = (trade["stop_loss"] - trade["entry_price"]) / pip_val
            saved_pnl += sl_pips  # pips saved

        elif fate["fate"] in ("T1_HIT", "T2_HIT"):
            # Invalidation killed a potential winner
            pip_val = 0.0001
            if fate["fate"] == "T1_HIT":
                if trade["direction"] == "LONG":
                    would_pips = (trade["target_1"] - trade["entry_price"]) / pip_val
                else:
                    would_pips = (trade["entry_price"] - trade["target_1"]) / pip_val
            else:
                if trade["direction"] == "LONG":
                    would_pips = (trade["target_2"] - trade["entry_price"]) / pip_val
                else:
                    would_pips = (trade["entry_price"] - trade["target_2"]) / pip_val
            killed_pnl += would_pips  # pips killed

    print(f"\n{'='*60}")
    print(f"FATE SUMMARY ({len(trades)} invalidation trades)")
    print(f"{'='*60}")
    print(f"  SL would have hit:    {results['SL_HIT']:3d} ({results['SL_HIT']/len(trades)*100:.0f}%) — invalidation SAVED these")
    print(f"  T1 would have hit:    {results['T1_HIT']:3d} ({results['T1_HIT']/len(trades)*100:.0f}%) — invalidation KILLED partial winners")
    print(f"  T2 would have hit:    {results['T2_HIT']:3d} ({results['T2_HIT']/len(trades)*100:.0f}%) — invalidation KILLED full winners")
    print(f"  Neither in 72h:       {results['NEITHER']:3d} ({results['NEITHER']/len(trades)*100:.0f}%)")
    print(f"  No data:              {results['NO_DATA']:3d}")
    killed = results["T1_HIT"] + results["T2_HIT"]
    saved = results["SL_HIT"]
    print(f"\n  Invalidation verdict: SAVED {saved} trades, KILLED {killed} potential winners")
    print(f"  Pips saved (SL avoided):     {saved_pnl:+.1f}")
    print(f"  Pips killed (T1/T2 missed):  {killed_pnl:+.1f}")
    print(f"  Net impact:                  {saved_pnl - killed_pnl:+.1f} pips")

    if killed > saved:
        print(f"\n  **RECOMMENDATION: DISABLE invalidation — it's destroying more edge than it protects")
    elif killed == saved:
        print(f"\n  **RECOMMENDATION: NEUTRAL — investigate individual trades more closely")
    else:
        print(f"\n  **RECOMMENDATION: KEEP invalidation — it's protecting the portfolio")

    # Output JSON for further analysis
    output = {
        "total": len(trades),
        "sl_hit": results["SL_HIT"],
        "t1_hit": results["T1_HIT"],
        "t2_hit": results["T2_HIT"],
        "neither": results["NEITHER"],
        "pips_saved": round(saved_pnl, 1),
        "pips_killed": round(killed_pnl, 1),
        "net_pips": round(saved_pnl - killed_pnl, 1),
    }
    print(f"\nJSON: {json.dumps(output)}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
