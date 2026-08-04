"""Is the edge that survives a universal box still real? (spec 8.29b)

8.29 found the honest, parameter-free box costs a third of the pooled return
(+0.76R -> +0.51R) and most of the held-out return (+0.98R -> +0.28R). Before
reading anything into what remains, it has to clear the same bar every other
claim in this study cleared: a shift-null that randomises where the funnel sits
while preserving direction, risk, R:R and trigger distance exactly.
"""
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import HELD_OUT, load_frame  # noqa: E402
from hvf_v2_mef_ablation import NSEED, RAND_HI, RAND_LO  # noqa: E402
from hvf_v2_mef_rank import offsets_for  # noqa: E402
from hvf_v2_mef_universalbox import CACHE, simulate, top  # noqa: E402

store = pickle.loads(CACHE.read_bytes())
LAB = "universal 0.50%"

print()
print("=" * 96)
print(f"SHIFT-NULL under {LAB} -- {NSEED} random shifts of +/-{RAND_LO}-{RAND_HI} bars")
print("=" * 96)
print(f"{'chart':<13}{'':<3}{'n':>6}{'real':>9}{'null mean':>11}{'null sd':>9}"
      f"{'pctile':>9}")
print("-" * 96)

reals, nulls_all = [], []
for c0 in CHARTS:
    name = c0["name"]
    c, offs = offsets_for(c0)
    frame = load_frame(c, offs[0] if offs[0] is not None else None)
    picks = top(store[(name, LAB)])
    a = simulate(frame, picks)
    if not a:
        continue
    real = float(np.mean(a))
    nulls = np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        sh = rng.integers(RAND_LO, RAND_HI) * rng.choice([-1, 1])
        t = simulate(frame, picks, shift=int(sh))
        nulls[s] = np.mean(t) if t else 0.0
    pct = float((nulls < real).mean() * 100)
    reals.append((name, real, len(a)))
    nulls_all.append(nulls)
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{len(a):>6}{real:>9.2f}"
          f"{nulls.mean():>11.2f}{nulls.std():>9.2f}{pct:>8.1f}%", flush=True)

print("-" * 96)
w = np.array([n for _, _, n in reals], float)
pooled_real = float(np.average([r for _, r, _ in reals], weights=w))
pooled_null = np.average(np.vstack(nulls_all), axis=0, weights=w)
pct = float((pooled_null < pooled_real).mean() * 100)
print(f"{'POOLED':<16}{int(w.sum()):>6}{pooled_real:>9.2f}"
      f"{pooled_null.mean():>11.2f}{pooled_null.std():>9.2f}{pct:>8.1f}%")
print("-" * 96)
print("Real must beat the null distribution, not zero. A high percentile means the")
print("edge comes from WHERE the funnel sits, not from direction or risk geometry.")
