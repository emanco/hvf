"""Repair the prior-trend definition (spec 8.19).

Spec 8.15 measured funnel shape against a prior trend defined as "the extreme
opposite pivot since the last pivot exceeding H1" -- i.e. walk back to
`prev_beyond`. That wall is a SINGLE pivot and the distance to it is unbounded
both ways, so the definition failed outright on 2 of 8 charts:

    USDJPY 4h   H1 is the highest pivot in the feed -> wall = -1 -> the "trend"
                is the entire 22,802-bar history back to the all-time low.
    WTI 18h     the pivot immediately before H1 already exceeds it -> the
                "trend" is 1 bar, and AMP1/trend = 3.22, i.e. the funnel comes
                out 3x LARGER than the impulse that supposedly produced it.

Both are the same defect: the definition has no notion of DEGREE. An impulse is
only an impulse relative to a scale, and the funnel already carries one -- AMP1.

The repair, in the spec's own idiom (4.1 uses a percentage box, and MEF is
scale-free): re-run the ZigZag at a box scaled to the funnel,

    box = k * AMP1 / anchor_price          k = 1 by default

and take the last pivot it confirms at or before the anchor. Everything inside
the funnel is then noise by construction, so the leg that survives is exactly
one degree up. It is bounded above (any k*AMP1 retracement terminates the leg)
and below (a shorter leg is never confirmed), causal, and free of any constant
that is not derived from the funnel itself.

Two things are measured:

  1. SHAPE -- AMP1/trend and the time ratio, the two numbers 8.15 could not use.
  2. DIRECTION -- the sign of that impulse against the way Hunt traded. This has
     never been tested: 8.17 only ever tried calendar windows (SMA, net move,
     zigzag) on the daily series, never the prior trend at the funnel's own
     degree, which is what doctrine (2.2) actually claims.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402
from hvf_v2_mef import (  # noqa: E402
    BOX_SIZES, HELD_OUT, LIVE_ANCHOR, LIVE_BARS, amp_gate, load_frame,
    mef_candidates, score,
)

BAR = "=" * 100
KS = [0.5, 1.0, 2.0, 3.0]

# Anchor pivot (H1 long / L1 short) and resample offset of the funnel the MEF
# acceptance search matched, from spec 8.14 and 8.17. Reused rather than
# recomputed: best_match re-runs the whole box sweep for every chart.
MATCH = {
    "GoldCFD 2h": ("2026-06-15", 0),
    "BTCUSD 1h": ("2026-03-10", None),
    "XAU/XAG 8h": ("2026-02-05", 3),
    "USDJPY 4h": ("2026-07-01", 0),
    "USDJPY 1W": ("2024-06-27", 0),
    "WTI 18h": ("2026-03-10", 15),
    "XAUEUR 1h": ("2026-04-21", None),
    "HYG 4h": ("2026-03-27", 0),
}


def anchor_bar(frame, ts):
    """Positional index of the last bar at or before ts."""
    dt = pd.DatetimeIndex(frame["dt"])
    if dt.tz is not None:
        dt = dt.tz_convert(None)
    return int(np.searchsorted(dt.to_numpy(), np.datetime64(ts), "right")) - 1


def impulse(frame, i, amp1, k):
    """The prior impulse into bar i, measured at the funnel's own degree.

    Returns (origin_pivot, signed move, bars). Direction-free: the sign falls
    out of where the last coarse pivot sits relative to the anchor, so nothing
    here knows how Hunt traded the chart.
    """
    sub = frame.iloc[: i + 1]
    close = float(sub["close"].iloc[-1])
    box = 100.0 * k * amp1 / abs(close)
    piv = zigzag_pct(sub, box)
    if not piv:
        return None, float("nan"), 0
    o = piv[-1]
    return o, close - o.price, i - o.index


def opposite_origin(frame, i, amp1, k, direction):
    """Same coarse ZigZag, but the last pivot OPPOSITE the funnel's anchor.

    This is the denominator 8.15 wanted: the low the rally into H1 started from
    (mirrored for shorts). Unlike `impulse` it is told the direction, so it is
    a shape measure only and must never be read as evidence about direction.
    """
    sub = frame.iloc[: i + 1]
    box = 100.0 * k * amp1 / abs(float(sub["close"].iloc[-1]))
    want = "L" if direction > 0 else "H"
    for p in reversed(zigzag_pct(sub, box)):
        if p.kind == want:
            return p
    return None


def funnel_span(c0, frame):
    """Bars from H1 to RL3 for the funnel the acceptance search matched.

    8.15 divided by this and it is not recoverable from the panel, so it is
    re-found here -- but only over the box grid at the ONE offset spec 8.14
    already recorded, which is what made `best_match` too slow to rerun.
    """
    _, _, _, ra, rb = reference_prices(c0)
    keep = amp_gate(c0, ra, rb)
    lf = LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c0["hours"])
    best = None
    for box in BOX_SIZES:
        piv = zigzag_pct(frame, box)
        if len(piv) < 6:
            continue
        for idx in mef_candidates(piv, c0["dir"], keep_ab=keep):
            w = [piv[j] for j in idx]
            if w[-1].ts < lf:
                continue
            s = score(w, c0, ra, rb)
            if s and (best is None or s[0] < best[0]):
                best = (s[0], w)
    return None if best is None else best[1]


rows = []
for c0 in CHARTS:
    ts_s, off = MATCH[c0["name"]]
    ts = pd.Timestamp(ts_s)
    c = dict(c0, src=c0["src"].replace("_W1", "_D1")) if c0["src"].endswith("_W1") else c0
    frame = load_frame(c, off)
    i = anchor_bar(frame, ts)
    _, _, _, ref_a, ref_b = reference_prices(c0)
    amp1 = abs(ref_b - ref_a)
    anchor_px = ref_b if c0["dir"] > 0 else ref_a
    w = funnel_span(c0, frame)
    rows.append(dict(c=c0, frame=frame, i=i, amp1=amp1, px=anchor_px, w=w,
                     tag="TEST" if c0["name"] in HELD_OUT else "calib"))

print(BAR)
print("1. DIRECTION -- sign of the prior impulse at the funnel's own degree")
print(BAR)
print(f"{'chart':<13}{'set':<7}{'Hunt':>6}" + "".join(f"{'k=' + str(k):>19}" for k in KS))
print("-" * 100)
recall = {k: [0, 0] for k in KS}
for r in rows:
    cells = []
    for k in KS:
        _, mv, bars = impulse(r["frame"], r["i"], r["amp1"], k)
        if not np.isfinite(mv):
            cells.append("--")
            continue
        agree = np.sign(mv) == np.sign(r["c"]["dir"])
        recall[k][0] += int(agree)
        recall[k][1] += 1
        cells.append(f"{mv:+.4g}/{bars}b {'OK' if agree else 'XX'}")
    print(f"{r['c']['name']:<13}{r['tag']:<7}"
          f"{'long' if r['c']['dir'] > 0 else 'short':>6}"
          + "".join(f"{t:>19}" for t in cells), flush=True)
print("-" * 100)
print(f"{'recall':<13}{'':<7}{'':>6}"
      + "".join(f"{f'{recall[k][0]}/{recall[k][1]}':>19}" for k in KS))

print()
print(BAR)
print("2. SHAPE -- the two ratios 8.15 could not use, k = 1")
print(BAR)
print(f"{'chart':<13}{'set':<7}{'AMP1':>11}{'trend':>11}{'AMP1/trend':>12}"
      f"{'f.bars':>8}{'t.bars':>8}{'time':>8}")
print("-" * 100)
shape = []
for r in rows:
    c0, frame, i = r["c"], r["frame"], r["i"]
    o = opposite_origin(frame, i, r["amp1"], 1.0, c0["dir"])
    if o is None:
        print(f"{c0['name']:<13}{r['tag']:<7} no coarse pivot")
        continue
    trend = abs(r["px"] - o.price)
    t_bars = i - o.index
    if r["w"] is None:
        print(f"{c0['name']:<13}{r['tag']:<7} funnel not relocated")
        continue
    f_bars = max(r["w"][-1].index - r["w"][0].index, 1)
    row = dict(name=c0["name"], tag=r["tag"], amp=r["amp1"] / trend if trend else np.nan,
               time=f_bars / t_bars if t_bars else np.nan)
    shape.append(row)
    print(f"{c0['name']:<13}{r['tag']:<7}{r['amp1']:>11.3f}{trend:>11.3f}"
          f"{row['amp']:>12.3f}{f_bars:>8}{t_bars:>8}{row['time']:>8.2f}", flush=True)

print()
print(BAR)
print("calibration band (n=6) against the two pre-committed held-out charts")
print(BAR)
print(f"{'metric':<12}{'calib min':>12}{'calib max':>12}{'spread':>9}"
      f"{'BTCUSD 1h':>12}{'XAUEUR 1h':>12}  holds?")
print("-" * 100)
cal = [r for r in shape if r["tag"] == "calib"]
tst = {r["name"]: r for r in shape if r["tag"] == "TEST"}
for key, label in (("amp", "AMP1/trend"), ("time", "time ratio")):
    vs = [r[key] for r in cal if np.isfinite(r[key])]
    lo, hi = min(vs), max(vs)
    got = [tst[n][key] if n in tst else float("nan") for n in ("BTCUSD 1h", "XAUEUR 1h")]
    ok = all(lo <= g <= hi for g in got)
    print(f"{label:<12}{lo:>12.3f}{hi:>12.3f}{hi / lo if lo else np.inf:>9.1f}"
          f"{got[0]:>12.3f}{got[1]:>12.3f}  {'yes' if ok else 'NO'}")
print(BAR)
