"""Build the 8.46 confirmatory universe: IC Markets single-stock CFDs. Read-only.

Selection is deterministic and made BEFORE any return is computed: symbols are sorted
alphabetically inside each exchange and sampled at a fixed stride, so the set cannot be
steered by performance. Everything with a `-24` suffix is dropped (those are 2026
relistings with weeks of history), as is anything failing the depth floor.
"""
import collections
import datetime as dt
import json

import numpy as np
import MetaTrader5 as m

OUT = r"C:/hvf_research"
EXCHANGES = ["NYSE", "Nasdaq", "EU", "UK"]
PER_EXCHANGE = 120        # probed
MIN_D1 = 1200             # ~5 years; the harness needs 600 bars plus trend lookback
HDR = "time,open,high,low,close,tick_volume,spread"
FMT = ["%d", "%.5f", "%.5f", "%.5f", "%.5f", "%d", "%d"]

assert m.initialize(), m.last_error()
end = dt.datetime.now() + dt.timedelta(days=2)

by_ex = collections.defaultdict(list)
for s in m.symbols_get():
    parts = s.path.split("\\")
    if parts[0] != "Stock CFD's" or len(parts) < 2:
        continue
    if "-24" in s.name:
        continue
    if parts[1] in EXCHANGES:
        by_ex[parts[1]].append(s.name)

cands = []
for ex in EXCHANGES:
    names = sorted(by_ex[ex])
    stride = max(1, len(names) // PER_EXCHANGE)
    picked = names[::stride][:PER_EXCHANGE]
    cands += [(ex, n) for n in picked]
    print(f"{ex:8s} {len(names):5d} symbols -> probing {len(picked)}")

print(f"\nprobing {len(cands)} symbols for >= {MIN_D1} D1 bars...")
kept, terms = [], {}
for i, (ex, nm) in enumerate(cands):
    if i % 50 == 0:
        print(f"  ...{i}/{len(cands)}, kept {len(kept)}", flush=True)
    if not m.symbol_select(nm, True):
        continue
    r = m.copy_rates_range(nm, m.TIMEFRAME_D1, end - dt.timedelta(days=365 * 25), end)
    if r is None or len(r) < MIN_D1:
        continue
    px = np.column_stack([r["open"], r["high"], r["low"], r["close"]])
    if (px <= 0).any() or not np.isfinite(px).all():
        continue
    info = m.symbol_info(nm)
    tick = m.symbol_info_tick(nm)
    if info is None or tick is None or not tick.bid:
        continue
    safe = nm.replace(".", "_")
    np.savetxt(f"{OUT}/{safe}_D1_mt5.csv", np.column_stack(
        [r["time"], r["open"], r["high"], r["low"], r["close"],
         r["tick_volume"], r["spread"]]),
        delimiter=",", header=HDR, comments="", fmt=FMT)
    terms[safe] = dict(symbol=nm, exchange=ex, digits=info.digits, point=info.point,
                       contract=info.trade_contract_size, swap_mode=info.swap_mode,
                       swap_long=info.swap_long, swap_short=info.swap_short,
                       spread=info.spread, price=tick.bid, bars=len(r),
                       first=int(r[0]["time"]), last=int(r[-1]["time"]))
    kept.append(nm)

json.dump(terms, open(f"{OUT}/stock_terms.json", "w"), indent=1)
print(f"\nkept {len(kept)} symbols")
print("by exchange:", dict(collections.Counter(t["exchange"] for t in terms.values())))
modes = collections.Counter(t["swap_mode"] for t in terms.values())
print("swap modes:", dict(modes))
sl = [t["swap_long"] for t in terms.values()]
ss = [t["swap_short"] for t in terms.values()]
print(f"swap_long  median {np.median(sl):+.3f}   swap_short median {np.median(ss):+.3f}")
m.shutdown()
