"""Why does the geometry emit against the trend? (spec 8.18)

The mirror test settled that `mef_candidates` is symmetric, so the 17:1 short skew
on gold has to come from the price series itself. The proposed mechanism:

  a funnel is enumerated inside the window its anchor's WALLS define, and a wall is
  the nearest same-kind pivot that is MORE extreme. In an uptrend a low is rarely
  undercut, so a low's walls sit far apart; a high is exceeded constantly, so a
  high's walls sit close together. Short funnels anchor on lows. Hence the skew.

Measured here as the wall span per pivot kind, next to the realised skew.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import numpy as np
import pandas as pd
from hvf_trader.detector.hvf_v2 import zigzag_pct
from hvf_v2_charts import CHARTS
from hvf_v2_mef import load_frame, mef_candidates, build_index

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
CASES = [("GoldCFD 2h", 0.6153, 0), ("BTCUSD 1h", 1.8822, None),
         ("USDJPY 4h", 0.4652, 1), ("HYG 4h", 0.7076, 0)]

print("=" * 96)
print("WALL SPAN BY PIVOT KIND -- how much room does each kind give an enumerator?")
print("=" * 96)
print(f"{'chart':<11}{'kind':>5}{'med':>7}{'mean':>8}{'p90':>7}{'p99':>8}{'max':>8}"
      f"{'sum span^3':>14}{'live funnels':>14}")
print("-" * 96)

for name, box, off in CASES:
    c0 = next(x for x in CHARTS if x["name"] == name)
    piv = zigzag_pct(load_frame(c0, off), box)
    idx = build_index(piv)
    prev_beyond, next_beyond = idx["prev_beyond"], idx["next_beyond"]
    n = len(piv)
    span = {"H": [], "L": []}
    for i, p in enumerate(piv):
        lo = max(prev_beyond[i], 0)
        hi = min(next_beyond[i], n - 1)
        span[p.kind].append(hi - lo)
    cnt = {}
    for d in (1, -1):
        cnt[d] = len({tuple(piv[j].ts.value for j in ix)
                      for ix in mef_candidates(piv, d)
                      if piv[ix[-1]].ts >= LIVE_FROM})

    # A short funnel anchors on a low, a long funnel on a high; the cube is a
    # crude stand-in for how the count grows with the room the anchor is given.
    for k, d in (("H", 1), ("L", -1)):
        a = np.array(span[k], dtype=float)
        print(f"{name if k == 'H' else '':<11}{k:>5}{np.median(a):>7.0f}{a.mean():>8.1f}"
              f"{np.percentile(a, 90):>7.0f}{np.percentile(a, 99):>8.0f}{a.max():>8.0f}"
              f"{(a ** 3).sum():>14,.0f}{cnt[d]:>14,}", flush=True)
    print(f"{'':<11}{'ratio L/H':>5}", end="")
    ah, al = np.array(span["H"], float), np.array(span["L"], float)
    print(f"{'':>7}{al.mean() / ah.mean():>8.2f}{'':>7}"
          f"{np.percentile(al, 99) / np.percentile(ah, 99):>8.2f}"
          f"{al.max() / ah.max():>8.2f}{(al ** 3).sum() / (ah ** 3).sum():>14.2f}"
          f"{cnt[-1] / cnt[1] if cnt[1] else float('nan'):>14.1f}")
    print("-" * 96)
