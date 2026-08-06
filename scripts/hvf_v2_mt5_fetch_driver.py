"""Fetch the remaining 8.46 candidates, one subprocess each with a hard timeout.

`copy_rates_range` blocks in C with no timeout and never returns on some symbols, which
cost three earlier attempts about 45 minutes between them. Isolating each probe in its own
process makes a hang cost TIMEOUT seconds instead of the run, so this can be left alone.

Selection is unchanged from the pre-registration and still performance-blind: alphabetical
inside each exchange, fixed stride, `-24` dropped, >= 1200 D1 bars. EU and UK go first
because NYSE and Nasdaq already have 131 between them (spec 8.46.1(a)). Logs to a file
because stdout over ssh is buffered until exit.
"""
import collections
import json
import os
import subprocess
import sys
import time

import MetaTrader5 as m

OUT = r"C:/hvf_research"
PY = r"C:/hvf_trader/venv/Scripts/python.exe"
TIMEOUT = 75
EXCHANGES = ["NYSE", "Nasdaq", "EU", "UK"]
PER_EXCHANGE = 120
PRIORITY = {"EU": 0, "UK": 1, "NYSE": 2, "Nasdaq": 3}
LOG = open(f"{OUT}/fetch.log", "a", buffering=1)


def log(s):
    LOG.write(f"{time.strftime('%H:%M:%S')} {s}\n")
    print(s, flush=True)


assert m.initialize(), m.last_error()
by_ex = collections.defaultdict(list)
for s in m.symbols_get():
    p = s.path.split("\\")
    if p[0] == "Stock CFD's" and len(p) > 1 and "-24" not in s.name and p[1] in EXCHANGES:
        by_ex[p[1]].append(s.name)
m.shutdown()

cands = []
for ex in EXCHANGES:
    names = sorted(by_ex[ex])
    stride = max(1, len(names) // PER_EXCHANGE)
    cands += [(ex, n) for n in names[::stride][:PER_EXCHANGE]]

os.makedirs(f"{OUT}/terms", exist_ok=True)
attempted = set()
if os.path.exists(f"{OUT}/attempted.json"):
    attempted = set(json.load(open(f"{OUT}/attempted.json")))
have = {f[:-5] for f in os.listdir(f"{OUT}/terms") if f.endswith(".json")}

todo = [(ex, nm) for ex, nm in cands
        if nm not in attempted and nm.replace(".", "_") not in have]
todo.sort(key=lambda t: (PRIORITY[t[0]], t[1]))
log(f"START {len(todo)} to probe  {dict(collections.Counter(e for e, _ in todo))}")

kept = to = rej = 0
for i, (ex, nm) in enumerate(todo, 1):
    t0 = time.time()
    try:
        r = subprocess.run([PY, f"{OUT}/probe_one.py", nm, ex],
                           capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode == 0:
            kept += 1
            log(f"[{i}/{len(todo)}] KEEP   {nm:16s} {time.time()-t0:5.1f}s")
        else:
            rej += 1
            log(f"[{i}/{len(todo)}] reject {nm:16s} {time.time()-t0:5.1f}s "
                f"{r.stdout.strip()}")
    except subprocess.TimeoutExpired:
        to += 1
        log(f"[{i}/{len(todo)}] TIMEOUT {nm:16s}")
    attempted.add(nm)
    if i % 10 == 0:
        json.dump(sorted(attempted), open(f"{OUT}/attempted.json", "w"))
        log(f"  -- progress kept={kept} rejected={rej} timeout={to}")

json.dump(sorted(attempted), open(f"{OUT}/attempted.json", "w"))
log(f"DONE kept={kept} rejected={rej} timeout={to}")

# stitch every terms fragment into the file the harness reads
terms = {}
for f in sorted(os.listdir(f"{OUT}/terms")):
    if f.endswith(".json"):
        terms[f[:-5]] = json.load(open(f"{OUT}/terms/{f}"))
json.dump(terms, open(f"{OUT}/stock_terms.json", "w"), indent=1)
log(f"stock_terms.json written with {len(terms)} symbols")
