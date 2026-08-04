"""Is the skew concentrated in a few anchors, or spread across all of them?"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import numpy as np, pandas as pd
from collections import Counter
from hvf_trader.detector.hvf_v2 import zigzag_pct
from hvf_v2_charts import CHARTS
from hvf_v2_mef import load_frame, mef_candidates

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
for name, box, off in [("GoldCFD 2h", 0.6153, 0), ("BTCUSD 1h", 1.8822, None),
                       ("USDJPY 4h", 0.4652, 1)]:
    c0 = next(x for x in CHARTS if x["name"] == name)
    piv = zigzag_pct(load_frame(c0, off), box)
    print(f"\n{name}")
    print(f"{'dir':>6}{'anchors used':>14}{'funnels':>10}{'per anchor':>12}"
          f"{'top1 share':>12}{'top10 share':>13}")
    for d, lab in ((1, "long"), (-1, "short")):
        by = Counter()
        seen = set()
        for ix in mef_candidates(piv, d):
            if piv[ix[-1]].ts < LIVE_FROM:
                continue
            key = tuple(piv[j].ts.value for j in ix)
            if key in seen:
                continue
            seen.add(key)
            by[piv[ix[0]].ts.value] += 1
        tot = sum(by.values())
        c = np.array(sorted(by.values(), reverse=True)) if by else np.array([0])
        print(f"{lab:>6}{len(by):>14,}{tot:>10,}{tot / max(len(by), 1):>12.1f}"
              f"{c[0] / max(tot, 1):>12.1%}{c[:10].sum() / max(tot, 1):>13.1%}", flush=True)
