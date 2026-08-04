"""Does an ATR-scale band do the selecting that the prior-trend gate cannot?

Hunt's eight funnels are 1.9 - 10.2 x ATR14 tall at H1 (measured 2026-08-04,
`hvf_v2_mef_trendref`), a 5.4x spread -- by far the tightest of the four
shape metrics, and the only one not contaminated by the prior-trend definition
failing on USDJPY 4h and WTI. The MEF rule is scale-free, so a scale band should
bite hard. Band taken from the SIX calibration charts only; the two held-out
values (3.5, 4.1) sit inside it and are not used to set it.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import pandas as pd
from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct, prior_trend_extreme_of_m
from hvf_v2_charts import CHARTS, reference_prices
from hvf_v2_mef import PASS_FIB, load_frame, mef_candidates, score

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
LO, HI = 1.882, 10.196            # calibration-only band
GATE = prior_trend_extreme_of_m(50)
CASES = [("GoldCFD 2h", 0.6153, 0), ("USDJPY 4h", 0.4652, 1),
         ("HYG 4h", 0.7076, 0), ("XAUEUR 1h", 0.9358, None),
         ("BTCUSD 1h", 1.8822, None)]

print(f"{'chart':<13}{'stage':<24}{'funnels':>10}{'per month':>12}{'Hunt?':>8}")
print("-" * 70)
for name, box, off in CASES:
    c0 = next(x for x in CHARTS if x["name"] == name)
    frame = load_frame(c0, off)
    _, _, _, ra, rb = reference_prices(c0)
    atr = _atr(frame, 14).to_numpy(float)
    piv = zigzag_pct(frame, box)
    span = (frame["dt"].iloc[-1] - max(frame["dt"].iloc[0], LIVE_FROM)).days / 30.44
    stages = {"geometry only": (set(), None), "+ extreme_of_m(50)": (set(), None),
              "+ ATR band 1.9-10.2": (set(), None)}
    keep = {k: [set(), None] for k in stages}
    for idx in mef_candidates(piv, c0["dir"]):
        w = [piv[j] for j in idx]
        if w[-1].ts < LIVE_FROM:
            continue
        s = score(w, c0, ra, rb)
        key = tuple(p.ts.value for p in w)
        passed = ["geometry only"]
        if GATE(frame, w[0].index, c0["dir"]):
            passed.append("+ extreme_of_m(50)")
            a = atr[w[0].index]
            if a and LO <= abs(w[0].price - w[1].price) / a <= HI:
                passed.append("+ ATR band 1.9-10.2")
        for k in passed:
            keep[k][0].add(key)
            if s and (keep[k][1] is None or s[0] < keep[k][1]):
                keep[k][1] = s[0]
    for k in stages:
        n, best = len(keep[k][0]), keep[k][1]
        hunt = "yes" if best is not None and best <= PASS_FIB else "NO"
        print(f"{name if k == 'geometry only' else '':<13}{k:<24}{n:>10,}"
              f"{n / span:>12.1f}{hunt:>8}", flush=True)
print("-" * 70)
print("v8.7 detector rates: gold 1.1, USDJPY 4h 0.4, HYG 4h 0.2 per month")
