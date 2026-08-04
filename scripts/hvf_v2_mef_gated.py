"""MEF emissions under spec 8.7's protocol -- prior-trend gate, 2026, same box.

Spec 8.14 first reported MEF selectivity ungated, over the whole feed, at boxes
of our choosing, and compared it to 8.7's rates. That was not like for like on
three axes at once, and it overstated the problem. 8.7's benchmark is: the box
that reproduces Hunt's setup, 2026 only, `extreme_of_m(50)` on H1. Same protocol
here, so the numbers can actually be set beside each other.

The gate is also the direct test of "does referencing the funnel to the
confirmed prior trend do the selecting?" -- `extreme_of_m(50)` asks only that H1
be the highest high of the preceding 50 bars, i.e. that the funnel sits at the
terminus of a real move rather than in the middle of chop.

RECALL IS THE THING THAT CAN BREAK. A filter that cuts emissions but loses
Hunt's own funnel is worse than no filter, so every row carries whether the true
setup survived.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    zigzag_pct, prior_trend_extreme_of_m, prior_trend_atr_span,
    prior_trend_slope,
)
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402
from hvf_v2_mef import PASS_FIB, load_frame, mef_candidates, score  # noqa: E402

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
BAR = "=" * 92

# Spec 8.6's reproducing box and resample anchor -- unchanged.
REPRODUCING = {"GoldCFD 2h": (0.6153, 0), "USDJPY 4h": (0.4652, 1),
               "HYG 4h": (0.7076, 0)}
# Coarsest box still scoring MATCH, from hvf_v2_mef_boxprofile.
COARSEST = {"GoldCFD 2h": (0.7076, 0), "BTCUSD 1h": (1.8822, None),
            "XAU/XAG 8h": (3.2919, 3), "USDJPY 4h": (0.4652, 0),
            "USDJPY 1W": (3.2919, 0), "WTI 18h": (1.0761, 15),
            "XAUEUR 1h": (0.9358, None), "HYG 4h": (0.9358, 0)}
GATES = {
    "none (geometry only)": lambda df, idx, d: True,
    "extreme_of_m(100)": prior_trend_extreme_of_m(100),
    "extreme_of_m(50)": prior_trend_extreme_of_m(50),
    "atr_span(k=4,n=100)": prior_trend_atr_span(4.0, 100),
    "atr_span(k=3,n=50)": prior_trend_atr_span(3.0, 50),
    "slope(n=100,r2=0.5)": prior_trend_slope(100, 0.5),
    "slope(n=50,r2=0.3)": prior_trend_slope(50, 0.3),
}


def emissions(c, box, off, gate):
    """Distinct 2026 MEF funnels passing `gate`, and the best fib error among
    them. No AMP prune: a live system has no reference range."""
    c0 = c
    if c["src"].endswith("_W1"):
        c = dict(c, src=c["src"].replace("_W1", "_D1"))
    frame = load_frame(c, off)
    _, _, _, ra, rb = reference_prices(c0)
    piv = zigzag_pct(frame, box)
    out, best = {}, None
    for idx in mef_candidates(piv, c0["dir"]):
        w = [piv[j] for j in idx]
        if w[-1].ts < LIVE_FROM:
            continue
        if not gate(frame, w[0].index, c0["dir"]):
            continue
        out[tuple(p.ts.value for p in w)] = idx
        s = score(w, c0, ra, rb)          # AMP_TOL still bounds what counts as
        if s and (best is None or s[0] < best):   # "Hunt's funnel", as in 8.6
            best = s[0]
    span = (frame["dt"].iloc[-1] - max(frame["dt"].iloc[0], LIVE_FROM)).days / 30.44
    return len(out), len(out) / span, best


print(BAR)
print("A -- spec 8.7 protocol exactly: reproducing box, 2026, per gate")
print(BAR)
print(f"{'prior-trend gate':<22}" + "".join(f"{n:>21}" for n in REPRODUCING))
print(f"{'':<22}" + "".join(f"{'/mo':>10}{'true?':>11}" for _ in REPRODUCING))
print("-" * 92)
ref87 = {"GoldCFD 2h": 1.1, "USDJPY 4h": 0.4, "HYG 4h": 0.2}
for gname, gate in GATES.items():
    cells = ""
    for name, (box, off) in REPRODUCING.items():
        c = next(x for x in CHARTS if x["name"] == name)
        n, rate, best = emissions(c, box, off, gate)
        ok = "yes" if best is not None and best <= PASS_FIB else (
            f"no({best:.3f})" if best is not None else "no")
        cells += f"{rate:>10.1f}{ok:>11}"
    print(f"{gname:<22}{cells}", flush=True)
print(f"{'v8.7 detector':<22}" + "".join(f"{ref87[n]:>10.1f}{'yes':>11}"
                                         for n in REPRODUCING))

print(f"\n{BAR}")
print("B -- all eight, coarsest matching box, 2026, extreme_of_m(50)")
print(BAR)
print(f"{'chart':<13}{'box%':>8}{'funnels':>10}{'per month':>12}{'best fib':>10}"
      f"{'Hunt kept?':>12}")
print("-" * 92)
g = GATES["extreme_of_m(50)"]
for c in CHARTS:
    box, off = COARSEST[c["name"]]
    n, rate, best = emissions(c, box, off, g)
    ok = "yes" if best is not None and best <= PASS_FIB else "NO"
    bs = f"{best:.4f}" if best is not None else "--"
    print(f"{c['name']:<13}{box:>8}{n:>10,}{rate:>12.1f}{bs:>10}{ok:>12}",
          flush=True)
print(BAR)
