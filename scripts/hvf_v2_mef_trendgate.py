"""Does the repaired trend definition work as the direction gate? (spec 8.19)

8.18 made direction a hard filter to correct a measured 17-50:1 counter-trend
bias in the enumerator, and 8.18's candidate gate was a calendar-window net move
(2y-5y) that only matches Hunt 4/7. 8.19 replaces it with the prior impulse
measured at the FUNNEL'S OWN degree, which matches 7/8.

That rule is per-candidate, not per-chart, so it is EXCLUSIVE in 8.16's sense --
each candidate is admitted in exactly one direction, its own. The question this
script answers is whether that is enough to remove the skew, or whether it
merely relabels it.

Each candidate carries its own AMP1, so its own coarse box. Re-running a ZigZag
per candidate is hopeless; instead one coarse ZigZag is precomputed per box on a
log grid and each candidate looks up the nearest. The grid step is 1.1: at 1.3
the snap cost USDJPY 1W its match (it wants a 12.7% box and got 12.35%), which
is itself worth knowing -- the coarser the funnel, the less slack the rule has.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import load_frame, mef_candidates  # noqa: E402

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
K = 1.0                                   # 8.19's pre-committed degree
CASES = [("GoldCFD 2h", 0.6153, 0), ("BTCUSD 1h", 1.8822, None),
         ("USDJPY 4h", 0.4652, 1), ("HYG 4h", 0.7076, 0)]


def grid(lo=0.05, hi=60.0, step=1.1):
    out, v = [], lo
    while v <= hi:
        out.append(v)
        v *= step
    return np.array(out)


GRID = grid()


def coarse_table(frame):
    """For each grid box: the pivots keyed by `confirm`, not `index`.

    Keying by `index` is a lookahead bug and it is not a subtle one -- a pivot
    printed at bar i is not KNOWN until price has reversed a box away from it,
    and 4.1 says so explicitly. Selecting on `confirm` makes one pass over the
    whole series identical to re-running the ZigZag truncated at every bar.
    Keyed by `index` this gate scored USDJPY 1W and gold differently from the
    per-chart run in `hvf_v2_mef_trendfix`; keyed by `confirm` they agree.
    """
    tab = []
    for box in GRID:
        piv = zigzag_pct(frame, float(box))
        tab.append((np.array([p.confirm for p in piv]),
                    np.array([p.price for p in piv])))
    return tab


def impulse_sign(tab, bar, price, amp):
    """Sign of the move from the last coarse pivot KNOWN at `bar` to `price`.

    Direction-free: nothing here is told how the candidate is oriented.
    """
    want = 100.0 * K * amp / abs(price)
    g = int(np.argmin(np.abs(np.log(GRID) - np.log(want))))
    cf, pp = tab[g]
    j = int(np.searchsorted(cf, bar, "right")) - 1
    if j < 0:
        return 0
    d = price - pp[j]
    return 0 if d == 0 else (1 if d > 0 else -1)


print("=" * 100)
print("DIRECTION GATE -- prior impulse at the funnel's own degree, per candidate")
print("=" * 100)
print(f"{'chart':<13}{'dir':>7}{'ungated':>12}{'gated':>10}{'kept':>8}"
      f"{'S:L ungated':>14}{'S:L gated':>12}")
print("-" * 100)

for name, box, off in CASES:
    c0 = next(x for x in CHARTS if x["name"] == name)
    frame = load_frame(c0, off)
    piv = zigzag_pct(frame, box)
    tab = coarse_table(frame)

    raw, kept = {}, {}
    for d in (1, -1):
        seen_raw, seen_kept = set(), set()
        for idx in mef_candidates(piv, d):
            if piv[idx[-1]].ts < LIVE_FROM:
                continue
            key = tuple(piv[j].ts.value for j in idx)
            seen_raw.add(key)
            p0, p1 = piv[idx[0]], piv[idx[1]]
            if impulse_sign(tab, p0.index, p0.price, abs(p0.price - p1.price)) == d:
                seen_kept.add(key)
        raw[d], kept[d] = len(seen_raw), len(seen_kept)

    for d, lab in ((1, "long"), (-1, "short")):
        share = kept[d] / raw[d] if raw[d] else float("nan")
        head = name if d == 1 else ""
        sl_r = f"{raw[-1] / raw[1]:.1f}" if d == 1 and raw[1] else ""
        sl_k = f"{kept[-1] / kept[1]:.1f}" if d == 1 and kept[1] else ""
        print(f"{head:<13}{lab:>7}{raw[d]:>12,}{kept[d]:>10,}{share:>8.1%}"
              f"{sl_r:>14}{sl_k:>12}", flush=True)
    print("-" * 100)

# The cut above is worthless if it also removes Hunt's own setups, and the grid
# lookup is an approximation the per-chart run in `hvf_v2_mef_trendfix` did not
# make. Recall is therefore re-tested here, through the exact gate code path.
from hvf_v2_charts import reference_prices  # noqa: E402

# Same anchors as `hvf_v2_mef_trendfix`, copied rather than imported: that
# module runs its whole measurement at import time.
MATCH = {"GoldCFD 2h": ("2026-06-15", 0), "BTCUSD 1h": ("2026-03-10", None),
         "XAU/XAG 8h": ("2026-02-05", 3), "USDJPY 4h": ("2026-07-01", 0),
         "USDJPY 1W": ("2024-06-27", 0), "WTI 18h": ("2026-03-10", 15),
         "XAUEUR 1h": ("2026-04-21", None), "HYG 4h": ("2026-03-27", 0)}


def anchor_bar(frame, ts):
    dt = pd.DatetimeIndex(frame["dt"])
    if dt.tz is not None:
        dt = dt.tz_convert(None)
    return int(np.searchsorted(dt.to_numpy(), np.datetime64(ts), "right")) - 1

print()
print("=" * 100)
print("RECALL -- does the gate, as implemented, admit Hunt's eight funnels?")
print("=" * 100)
print(f"{'chart':<13}{'Hunt':>7}{'box used':>11}{'gate says':>11}  verdict")
print("-" * 100)
ok = 0
for c0 in CHARTS:
    ts_s, off = MATCH[c0["name"]]
    c = dict(c0, src=c0["src"].replace("_W1", "_D1")) if c0["src"].endswith("_W1") else c0
    frame = load_frame(c, off)
    i = anchor_bar(frame, pd.Timestamp(ts_s))
    _, _, _, ra, rb = reference_prices(c0)
    amp1, px = abs(rb - ra), (rb if c0["dir"] > 0 else ra)
    want = 100.0 * K * amp1 / abs(px)
    g = int(np.argmin(np.abs(np.log(GRID) - np.log(want))))
    piv = zigzag_pct(frame, float(GRID[g]))
    cf = np.array([p.confirm for p in piv])
    pp = np.array([p.price for p in piv])
    j = int(np.searchsorted(cf, i, "right")) - 1
    s = 0 if j < 0 else int(np.sign(px - pp[j]))
    good = s == c0["dir"]
    ok += good
    print(f"{c0['name']:<13}{'long' if c0['dir'] > 0 else 'short':>7}"
          f"{GRID[g]:>11.3f}{'long' if s > 0 else 'short' if s < 0 else 'none':>11}"
          f"  {'OK' if good else 'MISSED'}")
print("-" * 100)
print(f"recall {ok}/8")
