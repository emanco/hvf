"""Probe ONE symbol and write its CSV + terms fragment. Read-only.

Runs as a subprocess so the driver can impose a hard timeout: copy_rates_range blocks in C
with no timeout of its own and never returns on some symbols, which cost the first two
attempts ~30 minutes between them.
"""
import datetime as dt
import json
import sys

import numpy as np
import MetaTrader5 as m

OUT = r"C:/hvf_research"
MIN_D1 = 1200
HDR = "time,open,high,low,close,tick_volume,spread"
FMT = ["%d", "%.5f", "%.5f", "%.5f", "%.5f", "%d", "%d"]

nm, ex = sys.argv[1], sys.argv[2]
if not m.initialize():
    sys.exit(2)
end = dt.datetime.now() + dt.timedelta(days=2)
m.symbol_select(nm, True)
r = m.copy_rates_range(nm, m.TIMEFRAME_D1, end - dt.timedelta(days=365 * 25), end)
if r is None or len(r) < MIN_D1:
    print(f"REJECT {nm} bars={0 if r is None else len(r)}")
    sys.exit(1)
px = np.column_stack([r["open"], r["high"], r["low"], r["close"]])
if (px <= 0).any() or not np.isfinite(px).all():
    print(f"REJECT {nm} bad prices")
    sys.exit(1)
info, tick = m.symbol_info(nm), m.symbol_info_tick(nm)
if info is None or tick is None or not tick.bid:
    print(f"REJECT {nm} no quote")
    sys.exit(1)
safe = nm.replace(".", "_")
np.savetxt(f"{OUT}/{safe}_D1_mt5.csv", np.column_stack(
    [r["time"], r["open"], r["high"], r["low"], r["close"],
     r["tick_volume"], r["spread"]]), delimiter=",", header=HDR, comments="", fmt=FMT)
json.dump(dict(symbol=nm, exchange=ex, digits=info.digits, point=info.point,
               contract=info.trade_contract_size, swap_mode=info.swap_mode,
               swap_long=info.swap_long, swap_short=info.swap_short,
               spread=info.spread, price=tick.bid, bars=len(r),
               first=int(r[0]["time"]), last=int(r[-1]["time"])),
          open(f"{OUT}/terms/{safe}.json", "w"))
print(f"KEEP {nm} bars={len(r)}")
