"""Pull EURGBP M1 from IC Markets in monthly chunks.

Big copy_rates_range calls fail with 'Invalid params' because the broker
won't stream multi-year M1 in one shot. Chunking by month is more
reliable — each chunk is small enough that MT5 handles it.

Run on VPS. Output: C:/hvf_trader/_export_m1/EURGBP_M1_chunked.csv
"""
import os
import csv
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")

if not mt5.initialize(path=os.getenv("MT5_PATH")):
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
if not mt5.login(
    int(os.getenv("MT5_LOGIN")),
    password=os.getenv("MT5_PASSWORD"),
    server=os.getenv("MT5_SERVER"),
):
    raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

SYMBOL = "EURGBP"
mt5.symbol_select(SYMBOL, True)

OUT_DIR = "C:/hvf_trader/_export_m1"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = f"{OUT_DIR}/{SYMBOL}_M1_chunked.csv"

# Try last 3 years, month by month
end = datetime.now(timezone.utc)
target_start = end - timedelta(days=365 * 3)

all_bars = []
chunk_start = target_start
empty_streak = 0
while chunk_start < end:
    chunk_end = min(chunk_start + timedelta(days=30), end)
    bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, chunk_start, chunk_end)
    if bars is None or len(bars) == 0:
        print(f"  {chunk_start.date()} to {chunk_end.date()}: empty (err={mt5.last_error()})")
        empty_streak += 1
        if empty_streak >= 3:
            print(f"  3 empty chunks in a row — stopping")
            break
    else:
        print(f"  {chunk_start.date()} to {chunk_end.date()}: {len(bars)} bars")
        all_bars.extend(bars)
        empty_streak = 0
    chunk_start = chunk_end

if not all_bars:
    print("\nNo data pulled. The terminal cache is empty for M1.")
    raise SystemExit(1)

# Dedup by time (chunks may overlap)
seen = set()
unique = []
for b in all_bars:
    if b["time"] not in seen:
        seen.add(b["time"])
        unique.append(b)
unique.sort(key=lambda b: b["time"])

print(f"\nTotal unique bars: {len(unique)}")
print(f"  First: {datetime.fromtimestamp(unique[0]['time'], tz=timezone.utc)}")
print(f"  Last:  {datetime.fromtimestamp(unique[-1]['time'], tz=timezone.utc)}")

with open(OUT_PATH, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
    for b in unique:
        w.writerow([b["time"], b["open"], b["high"], b["low"], b["close"],
                    b["tick_volume"], b["spread"]])
print(f"Saved: {OUT_PATH}")
mt5.shutdown()
