"""Is the backtest's edge distinguishable from luck? (spec 8.22, part 2)

The first run of `hvf_v2_mef_backtest.py` compared the ranked shortlist against
ONE random draw from the same gated pool. At ~30 trades a chart that control is
far too noisy to carry the comparison -- on BTCUSD and WTI the single draw beat
the rank outright, which on its own means nothing either way.

Two things fix it:

  * the control is redrawn over many seeds, giving a null DISTRIBUTION of mean R
    that the ranked result can be placed against;
  * the ranked trades are bootstrapped, giving an interval rather than a point.

Neither is a significance test in the strict sense -- the trades overlap in time
and across nested funnels, so they are not independent draws and any p-value
here is optimistic. It is reported as a percentile against the null, which is
the weakest claim the data supports.
"""
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import HELD_OUT  # noqa: E402
from hvf_v2_mef_backtest import enumerate_chart, run  # noqa: E402

CACHE = ROOT / "scripts" / ".backtest_cache.pkl"
NSEED = 200
N = 3

store = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
POOL = {}
for c0 in CHARTS:
    if c0["name"] not in store:
        frame, cands = enumerate_chart(c0)
        store[c0["name"]] = (frame, cands)
        CACHE.write_bytes(pickle.dumps(store))
    frame, cands = store[c0["name"]]
    POOL[c0["name"]] = (c0, frame, cands)
print(f"pool loaded ({sum(len(v[2]) for v in POOL.values()):,} gated candidates)",
      flush=True)


def months_of(cands):
    by = defaultdict(list)
    for s in cands:
        by[s["month"]].append(s)
    return by


print()
print("=" * 100)
print(f"NULL DISTRIBUTION -- top {N}/month by rank vs {NSEED} random draws of {N}/month")
print("=" * 100)
print(f"{'chart':<13}{'set':<7}{'rank meanR':>12}{'null mean':>11}{'null sd':>9}"
      f"{'null p95':>10}{'pctile':>9}{'rank win%':>11}{'null win%':>11}")
print("-" * 100)

agg_rank, agg_null = [], np.zeros(NSEED)
agg_rank_w, agg_null_w = [], np.zeros(NSEED)
for name, (c0, frame, cands) in POOL.items():
    by = months_of(cands)
    top = []
    for m, g in by.items():
        top += sorted(g, key=lambda x: x["z"])[:N]
    tr = np.array(run(frame, top))
    if tr.size == 0:
        print(f"{name:<13}{'no trades':>20}")
        continue
    agg_rank.append(tr)

    nulls, nullw = np.empty(NSEED), np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        ctl = []
        for m, g in by.items():
            k = min(N, len(g))
            ctl += [g[i] for i in rng.choice(len(g), k, replace=False)]
        t = np.array(run(frame, ctl))
        nulls[s] = t.mean() if t.size else 0.0
        nullw[s] = (t > 0).mean() if t.size else 0.0
    agg_null += nulls
    agg_null_w += nullw

    pct = (nulls < tr.mean()).mean()
    print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
          f"{tr.mean():>12.2f}{nulls.mean():>11.2f}{nulls.std():>9.2f}"
          f"{np.percentile(nulls, 95):>10.2f}{pct:>9.1%}"
          f"{(tr > 0).mean():>11.1%}{nullw.mean():>11.1%}", flush=True)
print("-" * 100)

# Pooled across charts, weighting each chart equally -- pooling the raw trades
# would let gold and BTCUSD, which have the most, decide the answer alone.
rk = np.array([t.mean() for t in agg_rank])
nl = agg_null / len(agg_rank)
print(f"{'POOLED':<13}{'':<7}{rk.mean():>12.2f}{nl.mean():>11.2f}{nl.std():>9.2f}"
      f"{np.percentile(nl, 95):>10.2f}{(nl < rk.mean()).mean():>9.1%}")

print()
print("=" * 100)
print("BOOTSTRAP -- ranked trades resampled 10,000x, per chart and pooled")
print("=" * 100)
print(f"{'chart':<13}{'n':>7}{'mean R':>10}{'2.5%':>9}{'97.5%':>9}{'P(mean>0)':>12}")
print("-" * 100)
rng = np.random.default_rng(1)
for (name, (c0, frame, cands)), tr in zip(
        [(k, v) for k, v in POOL.items() if v[2]], agg_rank):
    bs = rng.choice(tr, (10000, tr.size)).mean(axis=1)
    print(f"{name:<13}{tr.size:>7}{tr.mean():>10.2f}"
          f"{np.percentile(bs, 2.5):>9.2f}{np.percentile(bs, 97.5):>9.2f}"
          f"{(bs > 0).mean():>12.1%}")
allt = np.concatenate(agg_rank)
bs = rng.choice(allt, (10000, allt.size)).mean(axis=1)
print("-" * 100)
print(f"{'ALL trades':<13}{allt.size:>7}{allt.mean():>10.2f}"
      f"{np.percentile(bs, 2.5):>9.2f}{np.percentile(bs, 97.5):>9.2f}"
      f"{(bs > 0).mean():>12.1%}")
print("=" * 100)
print("Trades overlap in time and across nested funnels, so these are NOT")
print("independent draws and every interval here is optimistic.")
