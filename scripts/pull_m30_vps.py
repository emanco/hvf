"""Pull M30 data for KZ_HUNT pairs from MT5 on VPS, write to /tmp.

Run on VPS. Output: C:/hvf_trader/_export_m30/m30_{SYM}.csv per pair, ~3 years of M30 bars each.
"""
import os
from datetime import datetime, timezone, timedelta
import csv

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")

if not mt5.initialize(path=os.getenv("MT5_PATH")):
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
if not mt5.login(int(os.getenv("MT5_LOGIN")),
                password=os.getenv("MT5_PASSWORD"),
                server=os.getenv("MT5_SERVER")):
    raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

SYMBOLS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]
os.makedirs("C:/hvf_trader/_export_m30", exist_ok=True)
END = datetime.now(timezone.utc)
START = END - timedelta(days=365 * 3)   # 3 years

for sym in SYMBOLS:
    if not mt5.symbol_select(sym, True):
        print(f"  WARN: {sym} symbol_select failed")
        continue
    bars = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M30, START, END)
    if bars is None or len(bars) == 0:
        print(f"  {sym}: no bars returned")
        continue
    out = f"C:/hvf_trader/_export_m30/m30_{sym}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
        for b in bars:
            w.writerow([b["time"], b["open"], b["high"], b["low"], b["close"],
                        b["tick_volume"], b["spread"]])
    print(f"  {sym}: {len(bars)} bars to {out}")

mt5.shutdown()
print("Done.")
