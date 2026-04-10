"""
RRR Rejection Analysis: Analyze the patterns rejected by the RRR check.
Shows what RRR values were rejected and what would have happened if thresholds were lower.
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
LOOKAHEAD_HOURS = 72


def get_rejected_patterns():
    """Get patterns that were rejected (score >= threshold but failed risk checks)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Get REJECTED patterns that had a valid entry_price and stop_loss
    # (these passed detection but failed pre-trade checks)
    cur.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss, target_1, target_2,
               score, detected_at, pattern_type
        FROM pattern_records
        WHERE status = 'REJECTED'
          AND entry_price IS NOT NULL
          AND stop_loss IS NOT NULL
          AND target_1 IS NOT NULL
          AND target_2 IS NOT NULL
          AND entry_price > 0
          AND stop_loss > 0
          AND pattern_type = 'KZ_HUNT'
          AND detected_at >= '2026-03-25'
        ORDER BY id
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def calc_rrr(pattern):
    """Calculate risk-reward ratio for a pattern."""
    entry = pattern["entry_price"]
    sl = pattern["stop_loss"]
    t2 = pattern["target_2"]

    risk = abs(entry - sl)
    if risk == 0:
        return 0

    if pattern["direction"] == "LONG":
        reward = t2 - entry
    else:
        reward = entry - t2

    return reward / risk if risk > 0 else 0


def check_outcome(pattern):
    """Check what would have happened if this pattern had been traded."""
    detected = datetime.strptime(pattern["detected_at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    end_time = detected + timedelta(hours=LOOKAHEAD_HOURS)

    rates = mt5.copy_rates_range(pattern["symbol"], mt5.TIMEFRAME_H1, detected, end_time)
    if rates is None or len(rates) == 0:
        return "NO_DATA"

    direction = pattern["direction"]
    sl = pattern["stop_loss"]
    t1 = pattern["target_1"]
    entry = pattern["entry_price"]

    for bar in rates:
        high = bar["high"]
        low = bar["low"]

        if direction == "LONG":
            if low <= sl:
                return "SL_HIT"
            if high >= t1:
                return "T1_HIT"
        else:
            if high >= sl:
                return "SL_HIT"
            if low <= t1:
                return "T1_HIT"

    return "NEITHER"


def main():
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}")
        return

    patterns = get_rejected_patterns()
    print(f"Found {len(patterns)} rejected KZ_HUNT patterns since go-live\n")

    # Calculate RRR distribution
    rrr_values = []
    for p in patterns:
        rrr = calc_rrr(p)
        p["rrr"] = rrr
        rrr_values.append(rrr)

    # Group by RRR buckets
    below_08 = [p for p in patterns if p["rrr"] < 0.8]
    between_08_10 = [p for p in patterns if 0.8 <= p["rrr"] < 1.0]
    above_10 = [p for p in patterns if p["rrr"] >= 1.0]

    print(f"RRR Distribution of rejected patterns:")
    print(f"  RRR < 0.8:    {len(below_08):3d} patterns")
    print(f"  0.8 <= RRR < 1.0: {len(between_08_10):3d} patterns (would pass if threshold lowered to 0.8)")
    print(f"  RRR >= 1.0:   {len(above_10):3d} patterns (rejected for OTHER reasons, not RRR)")

    # Check outcomes for the 0.8-1.0 group (the ones we'd gain by lowering threshold)
    if between_08_10:
        print(f"\n--- Fate of {len(between_08_10)} patterns with 0.8 <= RRR < 1.0 ---")
        outcomes = {"SL_HIT": 0, "T1_HIT": 0, "NEITHER": 0, "NO_DATA": 0}
        for p in between_08_10:
            outcome = check_outcome(p)
            outcomes[outcome] += 1
            print(f"  #{p['id']:4d} {p['symbol']:7s} {p['direction']:5s} RRR={p['rrr']:.2f} → {outcome}")

        total_checked = len(between_08_10) - outcomes["NO_DATA"]
        if total_checked > 0:
            wr = outcomes["T1_HIT"] / total_checked * 100
            print(f"\n  Would-be WR: {wr:.0f}% ({outcomes['T1_HIT']}/{total_checked})")
            if wr > 40:
                print(f"  >>> RECOMMENDATION: Lower RRR threshold to 0.8 — these rejected trades had {wr:.0f}% WR")
            else:
                print(f"  >>> RECOMMENDATION: Keep RRR at 1.0 — rejected trades only had {wr:.0f}% WR")

    # Per-pair rejection counts
    print(f"\n--- Rejections by pair ---")
    by_pair = {}
    for p in patterns:
        pair = p["symbol"]
        if pair not in by_pair:
            by_pair[pair] = {"total": 0, "rrr_blocked": 0}
        by_pair[pair]["total"] += 1
        if p["rrr"] < 1.0:
            by_pair[pair]["rrr_blocked"] += 1

    for pair, counts in sorted(by_pair.items(), key=lambda x: -x[1]["total"]):
        print(f"  {pair}: {counts['total']} rejected ({counts['rrr_blocked']} by RRR)")

    mt5.shutdown()


if __name__ == "__main__":
    main()
