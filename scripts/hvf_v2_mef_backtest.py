"""Expectancy over the ranked shortlist -- the first HVF backtest (spec 8.22).

8.21 established the premise is not dead: the geometry pays 2.47R at the median
and Hunt's own eight reach 1R of favourable excursion 7 times out of 8. This
asks the question that actually matters -- if a system enumerates funnels,
imposes 8.19's direction, ranks them by 8.20's prior and trades the top few
each month, does it make money?

Design decisions that the previous failures (8.12 twice) turned on:

* Trades come off a SHORTLIST, never the raw population. 8.12's error was
  measuring expectancy over everything the enumerator emitted.
* A RANDOM control draws the same number of trades per month from the same
  gated pool. Without it, a positive result cannot be attributed -- it might be
  the pattern, the direction gate, or a bull market, and not the rank at all.
* Entry is a stop order at the 5th pivot, filled at the trigger price, armed
  only from `RL3.confirm`. 8.21 found fills land a median of ONE bar later, so
  this is the single most slippage-sensitive assumption in the study.
* One open position per chart. Funnels nest, so without this the same move is
  banked many times over.

Known leak, disclosed rather than hidden: 8.20's prior is fitted on Hunt's six
calibration funnels, which are dated 2026 and therefore sit inside the test
window. Six points setting four constants is a small leak, but it is not zero.
"""
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import HELD_OUT, load_frame, mef_candidates  # noqa: E402
from hvf_v2_mef_rank import BOX, GRID, K, offsets_for  # noqa: E402

FROM = pd.Timestamp("2023-01-01", tz="UTC")
TOPN = [1, 2, 3, 5, 10]
SEED = 20260804

# 8.20's prior, fitted on the six calibration funnels. Hard-coded so the
# backtest does not silently re-fit itself on whatever it happens to enumerate.
FIT = {"u": (1.688, 0.605), "v": (-0.442, 0.760)}


def coarse_table(frame):
    tab = []
    for box in GRID:
        piv = zigzag_pct(frame, float(box))
        tab.append((np.array([p.confirm for p in piv]),
                    np.array([p.price for p in piv])))
    return tab


def enumerate_chart(c0):
    """Every gated, scored, live candidate at this chart's box."""
    c, offs = offsets_for(c0)
    off = offs[0] if offs[0] is not None else None
    frame = load_frame(c, off)
    piv = zigzag_pct(frame, BOX[c0["name"]])
    tab = coarse_table(frame)
    atr = _atr(frame, 14).to_numpy(float)

    out, seen = [], set()
    for d in (1, -1):
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            if w[-1].ts < FROM:
                continue
            key = (d,) + tuple(p.ts.value for p in w)
            if key in seen:
                continue
            seen.add(key)

            amp = abs(w[0].price - w[1].price)
            a = atr[w[0].index]
            risk = abs(w[4].price - w[5].price)
            if not (amp > 0 and a > 0 and risk > 0):
                continue

            g = int(np.argmin(np.abs(np.log(GRID)
                                     - np.log(100.0 * K * amp / abs(w[0].price)))))
            cf, pp = tab[g]
            j = int(np.searchsorted(cf, w[0].index, "right")) - 1
            if j < 0:
                continue
            mv = w[0].price - pp[j]
            if np.sign(mv) != d:                       # 8.19 direction gate
                continue
            trend = abs(mv)
            if trend <= 0:
                continue

            u = np.log(amp / a)
            v = np.log(amp / trend)
            z = np.sqrt(((u - FIT["u"][0]) / FIT["u"][1]) ** 2
                        + ((v - FIT["v"][0]) / FIT["v"][1]) ** 2)
            out.append(dict(d=d, z=float(z), amp=amp, risk=risk,
                            entry=w[4].price, stop=w[5].price,
                            arm=w[5].confirm, wait=w[5].index - w[0].index,
                            ts=w[5].ts, month=w[5].ts.to_period("M")))
    return frame, out


def run(frame, picks):
    """Sequential fills, one position at a time, measured-move target."""
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    n = len(frame)
    free, trades = -1, []
    for s in sorted(picks, key=lambda x: x["arm"]):
        if s["arm"] <= free:                            # already in a position
            continue
        d, e, st = s["d"], s["entry"], s["stop"]
        tgt = e + d * s["amp"]
        fill = None
        for i in range(s["arm"] + 1, min(s["arm"] + 1 + s["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                fill = i
                break
        if fill is None:
            continue
        res = None
        for i in range(fill, n):
            adv = (e - lo[i]) / s["risk"] if d > 0 else (hi[i] - e) / s["risk"]
            fav = (hi[i] - e) / s["risk"] if d > 0 else (e - lo[i]) / s["risk"]
            if adv >= 1.0:                              # ties go to the stop
                res, free = -1.0, i
                break
            if fav >= s["amp"] / s["risk"]:
                res, free = s["amp"] / s["risk"], i
                break
        if res is None:                                 # still open at feed end
            continue
        trades.append(res)
    return trades


def stats(t):
    if not t:
        return "no trades"
    t = np.array(t)
    w = t[t > 0]
    pf = w.sum() / -t[t < 0].sum() if (t < 0).any() else float("inf")
    return (f"{len(t):>7,}{(t > 0).mean():>9.1%}{t.mean():>10.2f}"
            f"{t.sum():>11.1f}{pf:>9.2f}")


rng = np.random.default_rng(SEED)
POOL = {}
print("=" * 104)
print(f"0. POPULATION -- one box per chart, 8.19 gate applied, from {FROM.date()}")
print("=" * 104)
print(f"{'chart':<13}{'set':<7}{'gated cands':>13}{'months':>9}{'per month':>12}")
print("-" * 104)
for c0 in CHARTS:
    frame, cands = enumerate_chart(c0)
    POOL[c0["name"]] = (c0, frame, cands)
    ms = len({s["month"] for s in cands})
    print(f"{c0['name']:<13}{'TEST' if c0['name'] in HELD_OUT else 'calib':<7}"
          f"{len(cands):>13,}{ms:>9}{len(cands) / max(ms, 1):>12.1f}", flush=True)
print("-" * 104)

for N in TOPN:
    print()
    print("=" * 104)
    print(f"1. TOP {N} PER MONTH BY RANK          vs          RANDOM {N} PER MONTH")
    print("=" * 104)
    print(f"{'chart':<13}{'set':<7}" + f"{'n':>7}{'win%':>9}{'mean R':>10}"
          f"{'total R':>11}{'PF':>9}" + "   |" + f"{'n':>7}{'win%':>9}"
          f"{'mean R':>10}{'total R':>11}{'PF':>9}")
    print("-" * 104)
    allr, allc = [], []
    for name, (c0, frame, cands) in POOL.items():
        by = defaultdict(list)
        for s in cands:
            by[s["month"]].append(s)
        top, ctl = [], []
        for m, group in by.items():
            top += sorted(group, key=lambda x: x["z"])[:N]
            k = min(N, len(group))
            ctl += [group[i] for i in rng.choice(len(group), k, replace=False)]
        tr, tc = run(frame, top), run(frame, ctl)
        allr += tr
        allc += tc
        print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
              f"{stats(tr)}   |{stats(tc)}", flush=True)
    print("-" * 104)
    print(f"{'ALL':<13}{'':<7}{stats(allr)}   |{stats(allc)}")
print("=" * 104)
print("Fills at the trigger price, zero slippage, zero cost, zero financing.")
