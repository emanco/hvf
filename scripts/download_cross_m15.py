"""Download M15 cross-pair data from Dukascopy for Quiet-Hours BB+RSI backtest."""

import os
from datetime import datetime
import dukascopy_python

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backtests", "data")
os.makedirs(DATA_DIR, exist_ok=True)

PAIRS = ["AUDNZD", "NZDCAD", "AUDCAD", "EURCHF"]
START = datetime(2021, 1, 1)
END = datetime(2026, 4, 15)

for pair in PAIRS:
    outfile = os.path.join(DATA_DIR, f"{pair}_M15.csv")
    if os.path.exists(outfile):
        print(f"{pair}: already downloaded ({outfile})")
        continue

    print(f"Downloading {pair} M15 data ({START.date()} to {END.date()})...")
    try:
        df = dukascopy_python.fetch(
            instrument=pair,
            interval=dukascopy_python.INTERVAL_MIN_15,
            offer_side=dukascopy_python.OFFER_SIDE_BID,
            start=START,
            end=END,
        )
        df.to_csv(outfile)
        print(f"  Saved: {len(df)} bars to {outfile}")
    except Exception as e:
        print(f"  Error: {e}")

print("Done.")
