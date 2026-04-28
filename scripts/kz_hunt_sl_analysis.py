"""Unpack KZ_HUNT STOP_LOSS trades since go-live.

For each of the 40 SL closures, look for patterns:
- Per-pair distribution
- Time-to-SL (fast = immediate reversal, slow = grind out)
- Time-of-day clustering
- Pattern score distribution (were these low-confidence signals?)
- SL distance vs entry (were SLs too tight?)
- Slippage at entry
- Whether the trade ever showed positive PnL before stopping out
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")

if not mt5.initialize(path=os.getenv("MT5_PATH")):
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
if not mt5.login(int(os.getenv("MT5_LOGIN")),
                password=os.getenv("MT5_PASSWORD"),
                server=os.getenv("MT5_SERVER")):
    raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

PIP_VALUES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "EURGBP": 0.0001, "EURAUD": 0.0001,
    "USDJPY": 0.01, "GBPJPY": 0.01, "EURJPY": 0.01, "CHFJPY": 0.01,
}

conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()
cur.execute("""
SELECT t.id, t.symbol, t.direction, t.opened_at, t.closed_at,
       t.entry_price, t.stop_loss, t.target_1, t.target_2, t.lot_size,
       t.pnl, t.pnl_pips, t.intended_entry, t.intended_sl, t.slippage,
       p.score, p.h1_price, p.l1_price
FROM trade_records t
LEFT JOIN pattern_records p ON p.id = t.pattern_id
WHERE t.pattern_type = 'KZ_HUNT'
  AND t.close_reason = 'STOP_LOSS'
  AND t.opened_at >= '2026-03-25'
ORDER BY t.opened_at
""")
rows = cur.fetchall()
conn.close()

print(f"Analyzing {len(rows)} STOP_LOSS trades")
print("=" * 110)
print(f"{'ID':>4} {'SYM':<7} {'DIR':<4} {'Score':>5} {'SL_pips':>7} {'Held(h)':>7} {'MaxFavor':>8} {'$PnL':>8}")
print("-" * 110)

per_pair = defaultdict(list)
per_hour = defaultdict(list)
per_score_band = defaultdict(list)
fast_slow = defaultdict(list)
favorable_excursion = []   # max profit before SL
sl_distances = []
slippage = []

for r in rows:
    (tid, sym, direction, opened_at, closed_at, entry, sl, tp1, tp2, lots,
     pnl, pp, intended_entry, intended_sl, slip, score, h1p, l1p) = r
    pip = PIP_VALUES.get(sym, 0.0001)
    sl_pips = abs(entry - sl) / pip
    sl_distances.append(sl_pips)
    slippage.append(abs(slip or 0) / pip)

    def parse_dt(s):
        if not s:
            return None
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

    op = parse_dt(opened_at)
    cl = parse_dt(closed_at)
    if op is None:
        continue
    if cl is None:
        cl = op + timedelta(hours=8)  # fallback for missing closed_at
    held_hours = (cl - op).total_seconds() / 3600

    # Pull M5 bars between opened_at and closed_at to compute max favorable excursion
    bars = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M5, op, cl)
    max_fav_pips = 0.0
    if bars is not None and len(bars) > 0:
        for b in bars:
            if direction == "LONG":
                fav = (b["high"] - entry) / pip
            else:
                fav = (entry - b["low"]) / pip
            if fav > max_fav_pips:
                max_fav_pips = fav

    pnl_d = pnl or 0
    print(f"{tid:>4} {sym:<7} {direction:<4} {(score or 0):>5.0f} {sl_pips:>7.1f} {held_hours:>7.2f} {max_fav_pips:>+8.1f} ${pnl_d:>+7.2f}")

    per_pair[sym].append({"pnl": pnl_d, "held": held_hours, "max_fav": max_fav_pips, "score": score or 0})
    per_hour[op.hour].append(pnl_d)

    band = "lo(<60)" if (score or 0) < 60 else "mid(60-75)" if (score or 0) < 75 else "hi(>=75)"
    per_score_band[band].append(pnl_d)

    if held_hours < 2:
        fast_slow["fast(<2h)"].append({"pnl": pnl_d, "max_fav": max_fav_pips})
    elif held_hours < 6:
        fast_slow["mid(2-6h)"].append({"pnl": pnl_d, "max_fav": max_fav_pips})
    else:
        fast_slow["slow(>6h)"].append({"pnl": pnl_d, "max_fav": max_fav_pips})

    favorable_excursion.append(max_fav_pips)

print("-" * 110)
print()
print("=== Per pair ===")
for sym in sorted(per_pair, key=lambda s: -len(per_pair[s])):
    arr = per_pair[sym]
    n = len(arr)
    tot = sum(a["pnl"] for a in arr)
    avg_held = sum(a["held"] for a in arr) / n
    avg_fav = sum(a["max_fav"] for a in arr) / n
    avg_score = sum(a["score"] for a in arr) / n
    print(f"  {sym}: n={n:2d}  tot=${tot:+8.2f}  avgHeld={avg_held:.1f}h  avgMaxFav={avg_fav:+.1f}p  avgScore={avg_score:.0f}")

print()
print("=== Held duration buckets ===")
for k in ["fast(<2h)", "mid(2-6h)", "slow(>6h)"]:
    arr = fast_slow.get(k, [])
    if not arr:
        continue
    n = len(arr)
    tot = sum(a["pnl"] for a in arr)
    avg_fav = sum(a["max_fav"] for a in arr) / n
    print(f"  {k}: n={n:2d}  tot=${tot:+8.2f}  avgMaxFav={avg_fav:+.1f}p")

print()
print("=== Score band ===")
for band in ["lo(<60)", "mid(60-75)", "hi(>=75)"]:
    arr = per_score_band.get(band, [])
    if not arr:
        continue
    print(f"  {band}: n={len(arr):2d}  tot=${sum(arr):+8.2f}  avg=${sum(arr)/len(arr):+.2f}")

print()
print("=== Hour of entry (UTC) ===")
for h in sorted(per_hour):
    arr = per_hour[h]
    print(f"  {h:02d}: n={len(arr):2d}  tot=${sum(arr):+8.2f}")

print()
print("=== Favorable-excursion distribution ===")
fav_buckets = [(0, 5), (5, 10), (10, 20), (20, 50), (50, 999)]
for lo, hi in fav_buckets:
    in_bucket = [f for f in favorable_excursion if lo <= f < hi]
    if in_bucket:
        print(f"  Max favorable {lo}-{hi}p: {len(in_bucket)} trades")

print()
import statistics
print(f"=== SL distance: avg {statistics.mean(sl_distances):.1f}p  median {statistics.median(sl_distances):.1f}p  range [{min(sl_distances):.1f}, {max(sl_distances):.1f}]")
print(f"=== Slippage: avg {statistics.mean(slippage):.1f}p  max {max(slippage):.1f}p")

mt5.shutdown()
