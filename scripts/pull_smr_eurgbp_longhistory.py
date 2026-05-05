"""Dump 5y of EURGBP M5 from IC Markets MT5 to CSV.

Run on VPS. Output: C:/hvf_trader/_export_m5/EURGBP_M5_long.csv
Pattern mirrors scripts/pull_m30_vps.py which is known to work.
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
END = datetime.now(timezone.utc)
START = END - timedelta(days=365 * 5)
OUT_DIR = "C:/hvf_trader/_export_m5"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = f"{OUT_DIR}/{SYMBOL}_M5_long.csv"

if not mt5.symbol_select(SYMBOL, True):
    print(f"symbol_select failed: {mt5.last_error()}")

bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, START, END)
if bars is None or len(bars) == 0:
    print(f"copy_rates_range returned nothing: {mt5.last_error()}")
    raise SystemExit(1)

print(f"Pulled {len(bars)} M5 bars for {SYMBOL}")
with open(OUT_PATH, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
    for b in bars:
        w.writerow([b["time"], b["open"], b["high"], b["low"], b["close"],
                    b["tick_volume"], b["spread"]])

print(f"First bar broker-time: {datetime.fromtimestamp(bars[0]['time'], tz=timezone.utc)}")
print(f"Last  bar broker-time: {datetime.fromtimestamp(bars[-1]['time'], tz=timezone.utc)}")
print(f"Saved: {OUT_PATH}")
mt5.shutdown()
