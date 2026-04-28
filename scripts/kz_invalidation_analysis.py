"""Analyze KZ_HUNT invalidation closures: would they have won, lost, or both?

For each INVALIDATION-closed trade, fetch the M5 bars from MT5 starting at
closed_at and walk forward. Determine what would have happened if we hadn't
closed: did price hit TP1, TP2, or SL — and in what order?

Outputs:
- Per-trade verdict (TP1_first / TP2_first / SL_first / NEITHER)
- Counterfactual PnL (what we would have earned/lost)
- Realized PnL (what we actually got from the early close)
- Net delta (counterfactual − realized): positive = invalidation cost us
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")

# Connect MT5
if not mt5.initialize(path=os.getenv("MT5_PATH")):
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
if not mt5.login(int(os.getenv("MT5_LOGIN")),
                password=os.getenv("MT5_PASSWORD"),
                server=os.getenv("MT5_SERVER")):
    raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

# Pull invalidation trades
conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()
cur.execute("""
SELECT id, symbol, direction, opened_at, closed_at,
       entry_price, stop_loss, target_1, target_2, lot_size,
       pnl, pnl_pips
FROM trade_records
WHERE pattern_type = 'KZ_HUNT'
  AND close_reason = 'INVALIDATION'
  AND opened_at >= '2026-03-25'
ORDER BY opened_at
""")
trades = cur.fetchall()
conn.close()

print(f"Analyzing {len(trades)} INVALIDATION trades")
print("=" * 100)

PIP_VALUES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "EURGBP": 0.0001, "EURAUD": 0.0001,
    "AUDNZD": 0.0001, "NZDCAD": 0.0001, "AUDCAD": 0.0001, "EURCHF": 0.0001,
    "USDJPY": 0.01, "GBPJPY": 0.01, "EURJPY": 0.01, "CHFJPY": 0.01,
}
def pip(sym): return PIP_VALUES.get(sym, 0.0001)

def walk_forward(symbol, direction, closed_at, entry, sl, tp1, tp2, max_hours=24):
    """Return (verdict, hit_time, hit_price) — what would have happened post-close."""
    # closed_at is ISO. Parse as UTC.
    dt = datetime.fromisoformat(closed_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, dt, dt + timedelta(hours=max_hours))
    if bars is None or len(bars) == 0:
        return ("NO_DATA", None, None)

    for b in bars:
        hi, lo = b["high"], b["low"]
        # Order checks: SL has priority if both hit in same bar (worst case)
        if direction == "LONG":
            if lo <= sl:
                return ("SL_first", b["time"], sl)
            if hi >= (tp2 or tp1):
                return ("TP2_first", b["time"], tp2 or tp1)
            if hi >= tp1:
                return ("TP1_first", b["time"], tp1)
        else:  # SHORT
            if hi >= sl:
                return ("SL_first", b["time"], sl)
            if lo <= (tp2 or tp1):
                return ("TP2_first", b["time"], tp2 or tp1)
            if lo <= tp1:
                return ("TP1_first", b["time"], tp1)
    return ("NEITHER", None, None)


def cf_pnl(direction, entry, exit_price, lots, sym):
    """Simple counterfactual PnL in dollars (~$10/pip/standard lot)."""
    p = pip(sym)
    pips = (exit_price - entry) / p if direction == "LONG" else (entry - exit_price) / p
    return pips * 10.0 * lots, pips


verdicts = defaultdict(list)
total_realized = 0.0
total_cf = 0.0

print(f"{'ID':>4} {'SYM':<7} {'DIR':<4} {'VERDICT':<10} {'Realized':>10} {'Counterfac':>10} {'Delta':>10}")
print("-" * 100)

for r in trades:
    tid, sym, direction, opened_at, closed_at, entry, sl, tp1, tp2, lots, pnl, pp = r
    pnl = pnl or 0
    verdict, _, hit_price = walk_forward(sym, direction, closed_at, entry, sl, tp1, tp2)
    if verdict == "TP2_first":
        cf, _ = cf_pnl(direction, entry, tp2 or tp1, lots, sym)
    elif verdict == "TP1_first":
        # Approximate KZ Hunt: TP1 partials 60%, then trail. For the
        # counterfactual, just use TP1 as exit (conservative).
        cf, _ = cf_pnl(direction, entry, tp1, lots, sym)
    elif verdict == "SL_first":
        cf, _ = cf_pnl(direction, entry, sl, lots, sym)
    elif verdict == "NEITHER":
        cf = pnl  # treat as same as realized
    else:
        cf = pnl

    delta = cf - pnl
    verdicts[verdict].append({"id": tid, "sym": sym, "realized": pnl, "cf": cf, "delta": delta})
    total_realized += pnl
    total_cf += cf
    print(f"{tid:>4} {sym:<7} {direction:<4} {verdict:<10} ${pnl:>+9.2f} ${cf:>+9.2f} ${delta:>+9.2f}")

print("-" * 100)
print()
print("Verdict summary:")
for v, items in sorted(verdicts.items(), key=lambda x: -len(x[1])):
    n = len(items)
    real = sum(i["realized"] for i in items)
    cf_sum = sum(i["cf"] for i in items)
    delta = sum(i["delta"] for i in items)
    print(f"  {v}: n={n:2d}  realized=${real:+8.2f}  counterfac=${cf_sum:+8.2f}  delta=${delta:+8.2f}")

print()
print(f"TOTAL realized: ${total_realized:+.2f}")
print(f"TOTAL counterfactual: ${total_cf:+.2f}")
print(f"NET DELTA (counterfactual - realized): ${total_cf - total_realized:+.2f}")
print()
if total_cf > total_realized:
    print(f">>> Invalidation COST us ${total_cf - total_realized:.2f} — closing trades too early")
else:
    print(f">>> Invalidation SAVED us ${total_realized - total_cf:.2f} — working as designed")

mt5.shutdown()
