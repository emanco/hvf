"""Does referencing the funnel to the prior trend give it a SCALE?

The MEF rule's over-generation has a specific cause: it is scale-free. Funnels
nest inside funnels, from three-bar wiggles to multi-year structures, and every
level satisfies the mutual-extreme condition simultaneously. `extreme_of_m(50)`
only asks that H1 top a 50-bar window; it says nothing about how BIG the funnel
should be relative to the move it is digesting.

So measure, on the eight funnels Hunt actually drew, how the funnel sizes
against the impulse into it. The impulse is defined parameter-free and in the
same idiom as the rule itself: the trend origin is the extreme low between H1
and the previous high that exceeds H1 (i.e. one degree up from H1), mirrored for
shorts.

  amp_ratio   AMP1 / trend range      -- how much of the impulse it retraces
  atr_ratio   AMP1 / ATR14 at H1      -- funnel height in volatility units
  time_ratio  funnel bars / trend bars
  overshoot   how far past the trend origin RL1 sits, in AMP1 units

Calibrated on the six calibration charts, checked against the two pre-committed
held-out ones (spec 8.4). A band that survives that is a scale prior worth
building on; one that does not is n=6 numerology.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402
from hvf_v2_mef import (  # noqa: E402
    BOX_SIZES, HELD_OUT, LIVE_ANCHOR, LIVE_BARS, amp_gate, build_index,
    load_frame, mef_candidates, score,
)

BAR = "=" * 96


def best_match(c0):
    """Hunt's funnel as the acceptance run finds it, plus its frame and box."""
    _, _, _, ra, rb = reference_prices(c0)
    keep = amp_gate(c0, ra, rb)
    lf = LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c0["hours"])
    if c0["src"].endswith("_W1"):
        c, offs = dict(c0, src=c0["src"].replace("_W1", "_D1")), list(range(0, 168, 24))
    elif c0["hours"] == 1:
        c, offs = c0, [None]
    else:
        c, offs = c0, list(range(int(c0["hours"])))
    best = None
    for off in offs:
        frame = load_frame(c, off)
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
                    best = (s[0], frame, piv, idx, box, off)
    return best


def trend_of(piv, idx0, direction):
    """The impulse into H1: extreme opposite pivot since the last pivot that
    exceeds H1. One degree up from H1, in the rule's own idiom."""
    ix = build_index(piv)
    wall = ix["prev_beyond"][idx0]                  # last high above H1 (long)
    kind = "L" if direction > 0 else "H"
    span = [j for j in range(max(wall, 0), idx0) if ix["kind"][j] == kind]
    if not span:
        return None
    return (min(span, key=lambda j: piv[j].price) if direction > 0
            else max(span, key=lambda j: piv[j].price))


print(BAR)
print("FUNNEL SHAPE REFERENCED TO THE PRIOR TREND -- Hunt's eight setups")
print(BAR)
print(f"{'chart':<13}{'set':<7}{'AMP1':>10}{'trend':>10}{'amp/trend':>11}"
      f"{'AMP1/ATR':>10}{'f.bars':>8}{'t.bars':>8}{'time':>7}{'oshoot':>8}")
print("-" * 96)
rows = []
for c0 in CHARTS:
    b = best_match(c0)
    if b is None:
        print(f"{c0['name']:<13} no match")
        continue
    err, frame, piv, idx, box, off = b
    t = trend_of(piv, idx[0], c0["dir"])
    if t is None:
        print(f"{c0['name']:<13} no prior trend at this degree")
        continue
    h1, rl1, rl3 = piv[idx[0]], piv[idx[1]], piv[idx[5]]
    origin = piv[t]
    amp1 = abs(h1.price - rl1.price)
    trend = abs(h1.price - origin.price)
    atr = _atr(frame, 14).to_numpy(float)[h1.index]
    f_bars = rl3.index - h1.index
    t_bars = h1.index - origin.index
    row = dict(name=c0["name"], tag="TEST" if c0["name"] in HELD_OUT else "calib",
               amp=amp1 / trend if trend else float("nan"),
               atr=amp1 / atr if atr else float("nan"),
               time=f_bars / t_bars if t_bars else float("nan"),
               osh=(origin.price - rl1.price) / amp1 * c0["dir"])
    rows.append(row)
    print(f"{row['name']:<13}{row['tag']:<7}{amp1:>10.3f}{trend:>10.3f}"
          f"{row['amp']:>11.3f}{row['atr']:>10.1f}{f_bars:>8}{t_bars:>8}"
          f"{row['time']:>7.2f}{row['osh']:>8.2f}", flush=True)

print(f"\n{BAR}\ncalibration band (n=6) vs the two held-out charts\n{BAR}")
print(f"{'metric':<12}{'calib min':>11}{'calib max':>11}{'ratio':>8}"
      f"{'BTCUSD 1h':>11}{'XAUEUR 1h':>11}   holds?")
print("-" * 96)
cal = [r for r in rows if r["tag"] == "calib"]
tst = {r["name"]: r for r in rows if r["tag"] == "TEST"}
for k, label in (("amp", "AMP1/trend"), ("atr", "AMP1/ATR"),
                 ("time", "time ratio"), ("osh", "overshoot")):
    vs = [r[k] for r in cal]
    lo, hi = min(vs), max(vs)
    got = [tst[n][k] if n in tst else float("nan")
           for n in ("BTCUSD 1h", "XAUEUR 1h")]
    ok = all(lo <= g <= hi for g in got)
    print(f"{label:<12}{lo:>11.3f}{hi:>11.3f}{hi/lo if lo else float('inf'):>8.1f}"
          f"{got[0]:>11.3f}{got[1]:>11.3f}   {'yes' if ok else 'NO'}")
print(BAR)
