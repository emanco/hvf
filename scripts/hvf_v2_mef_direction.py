"""Does the prior-trend gate actually DECIDE direction, or just permit it?

Spec 2.2 says direction follows the prior trend into the exhaustion point, and
calls that "the single rule the old implementation lacked". But detect_hvf:378
sets direction from window parity (`run[0].kind`) and only then gates on the
prior trend -- parity proposes, prior trend disposes. And every MEF measurement
so far passed `c["dir"]`, i.e. Hunt's known answer, so direction determination
has never been tested at all.

Two questions. How many funnels appear in the WRONG direction (against Hunt's),
and does the prior-trend gate remove them?
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import pandas as pd
from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct, prior_trend_extreme_of_m
from hvf_v2_charts import CHARTS
from hvf_v2_mef import load_frame, mef_candidates

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
LO, HI = 1.882, 10.196
GATE = prior_trend_extreme_of_m(50)
CASES = [("GoldCFD 2h", 0.6153, 0), ("USDJPY 4h", 0.4652, 1),
         ("HYG 4h", 0.7076, 0), ("BTCUSD 1h", 1.8822, None)]

print(f"{'chart':<13}{'Hunt':>6}{'stage':<24}{'longs':>9}{'shorts':>9}"
      f"{'both/mo':>10}{'wrong-way %':>13}")
print("-" * 84)
for name, box, off in CASES:
    c0 = next(x for x in CHARTS if x["name"] == name)
    frame = load_frame(c0, off)
    atr = _atr(frame, 14).to_numpy(float)
    piv = zigzag_pct(frame, box)
    span = (frame["dt"].iloc[-1] - max(frame["dt"].iloc[0], LIVE_FROM)).days / 30.44
    counts = {s: {1: set(), -1: set()} for s in ("geometry", "+trend", "+ATR")}
    for d in (1, -1):
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            if w[-1].ts < LIVE_FROM:
                continue
            key = tuple(p.ts.value for p in w)
            counts["geometry"][d].add(key)
            if not GATE(frame, w[0].index, d):
                continue
            counts["+trend"][d].add(key)
            a = atr[w[0].index]
            if a and LO <= abs(w[0].price - w[1].price) / a <= HI:
                counts["+ATR"][d].add(key)
    hunt = "long" if c0["dir"] > 0 else "short"
    for s in counts:
        nl, ns = len(counts[s][1]), len(counts[s][-1])
        wrong = ns if c0["dir"] > 0 else nl
        tot = nl + ns
        print(f"{name if s == 'geometry' else '':<13}{hunt if s == 'geometry' else '':>6}"
              f"  {s:<22}{nl:>9,}{ns:>9,}{tot / span:>10.1f}"
              f"{100 * wrong / tot if tot else 0:>12.1f}%", flush=True)
print("-" * 84)
