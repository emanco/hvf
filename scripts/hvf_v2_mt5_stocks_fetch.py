"""Build the 8.46 confirmatory universe: IC Markets single-stock CFDs. Read-only.

Resumable. `copy_rates_range` blocks with no timeout while the terminal pulls history from
the server, and on some symbols it never returns -- the first attempt hung on one and made
no progress for 7 minutes. So the symbol being probed is written to `current.txt` BEFORE
the call; on restart that symbol is blacklisted and skipped. Kill and relaunch as often as
needed and the run advances one dead symbol per restart.

SELECTION IS UNCHANGED AND STILL PERFORMANCE-BLIND: sorted alphabetically inside each
exchange, fixed stride, `-24` relistings dropped, >= MIN_D1 bars. Nothing here can be
steered by returns -- no return has been computed, and the verdict rule is already
committed (558ff30). Skipping a symbol that hangs the terminal is an infrastructure
failure, independent of that symbol's price history.
"""
import collections
import datetime as dt
import json
import os

import numpy as np
import MetaTrader5 as m

OUT = r"C:/hvf_research"
EXCHANGES = ["NYSE", "Nasdaq", "EU", "UK"]
PER_EXCHANGE = 120
MIN_D1 = 1200
HDR = "time,open,high,low,close,tick_volume,spread"
FMT = ["%d", "%.5f", "%.5f", "%.5f", "%.5f", "%d", "%d"]

STATE = f"{OUT}/fetch_state.json"
CURRENT = f"{OUT}/current.txt"


def load_state():
    st = dict(done=[], bad=[], terms={})
    if os.path.exists(STATE):
        st.update(json.load(open(STATE)))
    # whatever was mid-probe when the process died is presumed to hang the terminal
    if os.path.exists(CURRENT):
        hung = open(CURRENT).read().strip()
        if hung and hung not in st["bad"]:
            st["bad"].append(hung)
            print(f"blacklisting hung symbol from previous run: {hung}")
        os.remove(CURRENT)
    return st


assert m.initialize(), m.last_error()
end = dt.datetime.now() + dt.timedelta(days=2)
st = load_state()
seen = set(st["done"]) | set(st["bad"])

by_ex = collections.defaultdict(list)
for s in m.symbols_get():
    parts = s.path.split("\\")
    if parts[0] != "Stock CFD's" or len(parts) < 2 or "-24" in s.name:
        continue
    if parts[1] in EXCHANGES:
        by_ex[parts[1]].append(s.name)

cands = []
for ex in EXCHANGES:
    names = sorted(by_ex[ex])
    stride = max(1, len(names) // PER_EXCHANGE)
    cands += [(ex, n) for n in names[::stride][:PER_EXCHANGE]]

# The first attempt wrote 128 CSVs but died before dumping terms, so adopt them: the bars
# are already on disk and `symbol_info` is a local lookup that cannot hang.
safe2nm = {nm.replace(".", "_"): (ex, nm) for ex, nm in cands}
adopted = 0
for fn in os.listdir(OUT):
    if not fn.endswith("_D1_mt5.csv"):
        continue
    safe = fn[: -len("_D1_mt5.csv")]
    if safe in st["terms"] or safe not in safe2nm:
        continue
    ex, nm = safe2nm[safe]
    m.symbol_select(nm, True)
    info, tick = m.symbol_info(nm), m.symbol_info_tick(nm)
    if info is None or tick is None or not tick.bid:
        continue
    a = np.genfromtxt(f"{OUT}/{fn}", delimiter=",", skip_header=1)
    st["terms"][safe] = dict(
        symbol=nm, exchange=ex, digits=info.digits, point=info.point,
        contract=info.trade_contract_size, swap_mode=info.swap_mode,
        swap_long=info.swap_long, swap_short=info.swap_short,
        spread=info.spread, price=tick.bid, bars=len(a),
        first=int(a[0][0]), last=int(a[-1][0]))
    st["done"].append(nm)
    adopted += 1
print(f"adopted {adopted} symbols already on disk", flush=True)
json.dump(st, open(STATE, "w"))

seen = set(st["done"]) | set(st["bad"])
todo = [(ex, nm) for ex, nm in cands if nm not in seen]

# Probe EU and UK before the remaining US names. Symbols the terminal has never cached
# take ~45s each to download, so the run is latency-bound and may be cut short; NYSE and
# Nasdaq already have 128 between them, and it is the non-US names that carry the
# cross-sectional independence the design effect depends on. This reorders WHICH symbols
# get fetched first, not which are eligible, and no return has been computed yet.
PRIORITY = {"EU": 0, "UK": 1, "NYSE": 2, "Nasdaq": 3}
todo.sort(key=lambda t: (PRIORITY[t[0]], t[1]))
print(f"{len(cands)} selected, {len(seen)} already attempted, {len(todo)} to go",
      flush=True)
print("  order:", dict(collections.Counter(ex for ex, _ in todo)), flush=True)

for i, (ex, nm) in enumerate(todo):
    open(CURRENT, "w").write(nm)          # so a hang here is skipped on restart
    try:
        if not m.symbol_select(nm, True):
            st["bad"].append(nm)
            continue
        r = m.copy_rates_range(nm, m.TIMEFRAME_D1,
                               end - dt.timedelta(days=365 * 25), end)
        if r is None or len(r) < MIN_D1:
            st["bad"].append(nm)
            continue
        px = np.column_stack([r["open"], r["high"], r["low"], r["close"]])
        if (px <= 0).any() or not np.isfinite(px).all():
            st["bad"].append(nm)
            continue
        info, tick = m.symbol_info(nm), m.symbol_info_tick(nm)
        if info is None or tick is None or not tick.bid:
            st["bad"].append(nm)
            continue
        safe = nm.replace(".", "_")
        np.savetxt(f"{OUT}/{safe}_D1_mt5.csv", np.column_stack(
            [r["time"], r["open"], r["high"], r["low"], r["close"],
             r["tick_volume"], r["spread"]]),
            delimiter=",", header=HDR, comments="", fmt=FMT)
        st["terms"][safe] = dict(
            symbol=nm, exchange=ex, digits=info.digits, point=info.point,
            contract=info.trade_contract_size, swap_mode=info.swap_mode,
            swap_long=info.swap_long, swap_short=info.swap_short,
            spread=info.spread, price=tick.bid, bars=len(r),
            first=int(r[0]["time"]), last=int(r[-1]["time"]))
        st["done"].append(nm)
    finally:
        os.remove(CURRENT)
    if i % 20 == 0:
        json.dump(st, open(STATE, "w"))
        print(f"  {i}/{len(todo)}  kept {len(st['done'])}", flush=True)

json.dump(st, open(STATE, "w"))
json.dump(st["terms"], open(f"{OUT}/stock_terms.json", "w"), indent=1)
print(f"\nCOMPLETE. kept {len(st['done'])}, rejected {len(st['bad'])}")
print("by exchange:", dict(collections.Counter(t["exchange"] for t in st["terms"].values())))
print("swap modes:", dict(collections.Counter(t["swap_mode"] for t in st["terms"].values())))
sl = [t["swap_long"] for t in st["terms"].values()]
ss = [t["swap_short"] for t in st["terms"].values()]
print(f"swap_long median {np.median(sl):+.3f}   swap_short median {np.median(ss):+.3f}")
m.shutdown()
