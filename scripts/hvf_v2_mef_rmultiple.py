"""What is a Hunt funnel actually worth? (spec 8.21)

Everything from 8.14 to 8.20 measures agreement with Hunt's annotations. None
of it measures money, and agreement is not a proxy for profit: the object being
reproduced has unknown expectancy, so a perfect classifier for a break-even
pattern is a live possibility. This is the cheapest thing that could falsify
the premise -- the realised R-multiple of his own eight setups.

Two numbers per chart:

  geometric   AMP1 / |entry - stop| = 1 / (rh3 - rl3), pure structure, exact
  realised    walk the bars forward and see which level price reaches first

The simulation runs on the DETECTED funnel, never the annotation, and starts at
`RL3.confirm` -- the bar the sixth pivot becomes knowable. A live system has
nothing earlier. Intrabar ties resolve to the stop, which is the conservative
side of an ambiguity OHLC cannot settle.
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
    HELD_OUT, LIVE_ANCHOR, LIVE_BARS, PASS_FIB, amp_gate, load_frame,
    mef_candidates, score,
)
from hvf_v2_mef_rank import BOX, offsets_for  # noqa: E402


def find_funnel(c0):
    """Hunt's funnel as the detector sees it: best fib error at the chart's box."""
    c, offs = offsets_for(c0)
    _, _, _, ra, rb = reference_prices(c0)
    keep = amp_gate(c0, ra, rb)
    lf = LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c0["hours"])
    best = None
    for off in offs:
        frame = load_frame(c, off)
        piv = zigzag_pct(frame, BOX[c0["name"]])
        if len(piv) < 6:
            continue
        for idx in mef_candidates(piv, c0["dir"], keep_ab=keep):
            w = [piv[j] for j in idx]
            if w[-1].ts < lf:
                continue
            s = score(w, c0, ra, rb)
            if s and (best is None or s[0] < best[0]):
                best = (s[0], w, frame)
    return best


def simulate(frame, w, d, wait):
    """Stop-entry at the 5th pivot, stop-loss at the 6th, from RL3.confirm.

    Returns bars-to-fill, the realised R at the first level touched, and the
    excursions -- MFE is what a target sweep can spend, MAE is what it costs.
    """
    entry, stop = w[4].price, w[5].price
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    n = len(frame)

    fill = None
    for i in range(w[5].confirm + 1, min(w[5].confirm + 1 + wait, n)):
        if (d > 0 and hi[i] >= entry) or (d < 0 and lo[i] <= entry):
            fill = i
            break
    if fill is None:
        return dict(state="no entry", bars=None)

    mfe = mae = 0.0
    for i in range(fill, n):
        fav = (hi[i] - entry) / risk if d > 0 else (entry - lo[i]) / risk
        adv = (entry - lo[i]) / risk if d > 0 else (hi[i] - entry) / risk
        mfe, mae = max(mfe, fav), max(mae, adv)
        if adv >= 1.0:                      # stop first on an intrabar tie
            return dict(state="stopped", bars=fill - w[5].confirm,
                        held=i - fill, R=-1.0, mfe=mfe, mae=mae)
    return dict(state="open", bars=fill - w[5].confirm, held=n - 1 - fill,
                R=mfe, mfe=mfe, mae=mae)


print("=" * 100)
print("1. GEOMETRY -- reward:risk implied by the funnel alone, before any price action")
print("=" * 100)
print(f"{'chart':<13}{'set':<7}{'dir':>6}{'AMP1':>12}{'risk':>10}"
      f"{'AMP1/risk':>11}{'breakeven win%':>16}")
print("-" * 100)
FUN = {}
geo = []
for c0 in CHARTS:
    best = find_funnel(c0)
    if best is None:
        print(f"{c0['name']:<13}{'no funnel found':>40}")
        continue
    err, w, frame = best
    FUN[c0["name"]] = (c0, w, frame)
    amp1 = abs(w[0].price - w[1].price)
    risk = abs(w[4].price - w[5].price)
    rr = amp1 / risk
    geo.append(rr)
    print(f"{c0['name']:<13}{'TEST' if c0['name'] in HELD_OUT else 'calib':<7}"
          f"{('long' if c0['dir'] > 0 else 'short'):>6}{amp1:>12.4f}{risk:>10.4f}"
          f"{rr:>11.2f}{1.0 / (1.0 + rr):>15.1%}", flush=True)
print("-" * 100)
print(f"{'median':<13}{'':<7}{'':>6}{'':>12}{'':>10}{np.median(geo):>11.2f}"
      f"{1.0 / (1.0 + np.median(geo)):>15.1%}")

print()
print("=" * 100)
print("2. REALISED -- detected funnel, entry from RL3.confirm, ties to the stop")
print("=" * 100)
print(f"{'chart':<13}{'set':<7}{'state':>10}{'bars->fill':>12}{'held':>7}"
      f"{'MFE (R)':>10}{'MAE (R)':>10}{'R @ AMP1 tgt':>14}")
print("-" * 100)
rows = []
for name, (c0, w, frame) in FUN.items():
    amp1 = abs(w[0].price - w[1].price)
    risk = abs(w[4].price - w[5].price)
    r = simulate(frame, w, c0["dir"], wait=w[5].index - w[0].index)
    if r is None or r["state"] == "no entry":
        print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
              f"{'no entry':>10}")
        rows.append((name, None))
        continue
    tgt = amp1 / risk
    # What a measured-move target actually returns, given the path taken.
    got = (-1.0 if r["state"] == "stopped" and r["mfe"] < tgt
           else tgt if r["mfe"] >= tgt else np.nan)
    rows.append((name, (r, tgt, got)))
    print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
          f"{r['state']:>10}{r['bars']:>12}{r['held']:>7}{r['mfe']:>10.2f}"
          f"{r['mae']:>10.2f}"
          f"{('open' if np.isnan(got) else f'{got:+.2f}'):>14}", flush=True)
print("-" * 100)
done = [g for _, v in rows if v for g in [v[2]] if not np.isnan(g)]
if done:
    print(f"resolved {len(done)}/8 at a measured-move target: "
          f"mean {np.mean(done):+.2f}R, wins {sum(g > 0 for g in done)}/{len(done)}")
mf = [v[0]["mfe"] for _, v in rows if v]
print(f"MFE across all entered: median {np.median(mf):.2f}R, "
      f"max {max(mf):.2f}R, >=1R {sum(m >= 1 for m in mf)}/{len(mf)}, "
      f">=2R {sum(m >= 2 for m in mf)}/{len(mf)}")
print("=" * 100)
print("n=8. This is a sanity check on the premise, NOT a backtest.")
