"""How many YEARS of trend? And does the geometry's skew track it? (spec 8.18)

Two questions in one pass, because they share the same anchor dates.

1. Spec 8.17 tested the main trend over at most ONE year and got 3/7. But the
   claim under test was "up for several years", so measure 1y/2y/3y/5y and see
   whether a longer horizon recovers the charts a one-year window loses.

2. The mirror test shows the long:short skew is not a code defect and flips when
   the series is reflected. If it is trend-driven, the skew must ANTI-correlate
   with the trend sign: shorts dominate in uptrends. Measured directly here.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import numpy as np
import pandas as pd
from hvf_trader.detector.hvf_v2 import load_ohlc, ratio_series, zigzag_pct
from hvf_v2_charts import CHARTS
from hvf_v2_mef import load_frame, mef_candidates
from hvf_v2_mef_maintrend_htf import daily

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
YEARS = [1, 2, 3, 5]
BOXES = {"GoldCFD 2h": (0.6153, 0), "BTCUSD 1h": (1.8822, None),
         "USDJPY 4h": (0.4652, 1), "HYG 4h": (0.7076, 0)}

# Anchor pivot (H1 for a long, L1 for a short) of the funnel the MEF acceptance
# search matched, as recorded in spec 8.17. Reused rather than recomputed:
# best_match re-runs the whole box sweep and these are already committed facts.
ANCHOR = {"GoldCFD 2h": "2026-06-15", "BTCUSD 1h": "2026-03-10",
          "XAU/XAG 8h": "2026-02-05", "USDJPY 4h": "2026-07-01",
          "USDJPY 1W": "2024-06-27", "WTI 18h": "2026-03-10",
          "XAUEUR 1h": "2026-04-21", "HYG 4h": "2026-03-27"}


def anchor_ts(name):
    return pd.Timestamp(ANCHOR[name], tz="UTC")

def bar_index(d, ts):
    """Index of the last daily bar at or before ts, tz differences ironed out."""
    dt = pd.DatetimeIndex(d["dt"])
    if dt.tz is not None:
        dt = dt.tz_convert(None)
    return int(np.searchsorted(dt.to_numpy(), np.datetime64(ts.tz_convert(None)), "right")) - 1

print("=" * 104)
print("TREND HORIZON -- net move at the funnel anchor, 1 to 5 years back")
print("=" * 104)
print(f"{'chart':<13}{'Hunt':>6}{'anchor':>12}" +
      "".join(f"{str(y) + 'y':>17}" for y in YEARS))
print("-" * 104)

rows, recall = [], {y: [0, 0] for y in YEARS}
for c in CHARTS:
    ts = anchor_ts(c["name"])
    d = daily(c["name"])
    i = bar_index(d, ts)
    cl = d["close"].to_numpy(float)
    cells = []
    for y in YEARS:
        back = i - int(365.25 * y)
        if back < 0:
            cells.append(("--", np.nan))
            continue
        pct = 100.0 * (cl[i] / cl[back] - 1.0)
        agree = np.sign(pct) == np.sign(c["dir"])
        recall[y][0] += int(agree)
        recall[y][1] += 1
        cells.append((f"{pct:+.1f}% {'OK' if agree else 'XX'}", np.sign(pct)))
    print(f"{c['name']:<13}{'long' if c['dir'] > 0 else 'short':>6}"
          f"{ts:%Y-%m-%d:>12}" + "".join(f"{t:>17}" for t, _ in cells), flush=True)
    rows.append((c["name"], c["dir"], cells))

print("-" * 104)
print(f"{'recall':<13}{'':>6}{'':>12}" +
      "".join(f"{str(recall[y][0]) + '/' + str(recall[y][1]):>17}" for y in YEARS))

print()
print("=" * 104)
print("SKEW vs TREND -- does the geometry emit against the trend?")
print("=" * 104)
print(f"{'chart':<13}{'1y move':>10}{'3y move':>10}{'longs':>10}{'shorts':>10}"
      f"{'S:L':>8}{'skew is':>12}")
print("-" * 104)
for name, (box, off) in BOXES.items():
    c0 = next(x for x in CHARTS if x["name"] == name)
    frame = load_frame(c0, off)
    piv = zigzag_pct(frame, box)
    n = {}
    for dd in (1, -1):
        n[dd] = len({tuple(piv[j].ts.value for j in idx)
                     for idx in mef_candidates(piv, dd)
                     if piv[idx[-1]].ts >= LIVE_FROM})
    ts = anchor_ts(name)
    d = daily(name)
    i = bar_index(d, ts)
    cl = d["close"].to_numpy(float)
    mv = {}
    for y in (1, 3):
        b = i - int(365.25 * y)
        mv[y] = 100.0 * (cl[i] / cl[b] - 1.0) if b >= 0 else np.nan
    skew = "with trend" if (n[1] > n[-1]) == (mv[1] > 0) else "AGAINST trend"
    f1 = f"{mv[1]:+.1f}%" if not np.isnan(mv[1]) else "--"
    f3 = f"{mv[3]:+.1f}%" if not np.isnan(mv[3]) else "--"
    print(f"{name:<13}{f1:>10}{f3:>10}{n[1]:>10,}{n[-1]:>10,}"
          f"{n[-1] / n[1] if n[1] else 0:>8.1f}{skew:>12}", flush=True)
print("-" * 104)
