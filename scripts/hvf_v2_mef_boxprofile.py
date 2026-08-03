"""At which box sizes does Hunt's funnel still score as a MATCH?

The acceptance run reported box 0.1% for 7 of 8 charts, but ties break to the
first box in the sweep and the MEF condition is scale-invariant, so 0.1% is an
artefact of ordering, not a fit. What matters is the COARSEST box that still
matches, because emission rate falls roughly as box^-3 and spec 8.7's rates are
only reachable near 1-2%.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import pandas as pd
from hvf_trader.detector.hvf_v2 import zigzag_pct
from hvf_v2_mef import (BOX_SIZES, CHARTS, LIVE_ANCHOR, LIVE_BARS, PASS_FIB,
                        amp_gate, load_frame, mef_candidates, reference_prices,
                        score)

print(f"{'chart':<13}{'best box':>10}{'coarsest MATCH':>16}{'err there':>11}"
      f"{'anchor':>8}   per-box best-live err profile")
print("-" * 118)
for c0 in CHARTS:
    _, _, _, ra, rb = reference_prices(c0)
    keep = amp_gate(c0, ra, rb)
    lf = LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c0["hours"])
    if c0["src"].endswith("_W1"):
        c = dict(c0, src=c0["src"].replace("_W1", "_D1"))
        offs = list(range(0, 168, 24))
    elif c0["hours"] == 1:
        c, offs = c0, [None]
    else:
        c, offs = c0, list(range(int(c0["hours"])))

    prof = {}
    for off in offs:
        frame = load_frame(c, off)
        for box in BOX_SIZES:
            piv = zigzag_pct(frame, box)
            if len(piv) < 6:
                continue
            for idx in mef_candidates(piv, c0["dir"], keep_ab=keep):
                w = [piv[j] for j in idx]
                s = score(w, c0, ra, rb)
                if s is None or w[-1].ts < lf:
                    continue
                if box not in prof or s[0] < prof[box][0]:
                    prof[box] = (s[0], off)
    if not prof:
        print(f"{c0['name']:<13}   no live candidates")
        continue
    passing = [b for b, v in prof.items() if v[0] <= PASS_FIB]
    best_box = min(prof, key=lambda b: prof[b][0])
    line = " ".join(f"{b:g}:{prof[b][0]:.3f}" for b in sorted(prof))
    if passing:
        cb = max(passing)
        print(f"{c0['name']:<13}{best_box:>10g}{cb:>16g}{prof[cb][0]:>11.4f}"
              f"{str(prof[cb][1]):>8}   {line}", flush=True)
    else:
        print(f"{c0['name']:<13}{best_box:>10g}{'none':>16}{'--':>11}{'--':>8}"
              f"   {line}", flush=True)
