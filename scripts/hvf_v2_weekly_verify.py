"""Score Hunt's USDJPY 1W funnel using the pivots the detector already prints.

Selected by eye from the box-3.0% pivot list, so this is a POST-HOC fit on n=1
and proves only that the six pivots exist and carry Hunt's fibs -- not that any
rule finds them. Scored exactly as hvf_v2_acceptance.score does: in the
CANDIDATE's own (a, b) frame, not Hunt's.
"""
import sys
from pathlib import Path

ROOT = Path("/Users/manu/Dev/hvf")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd
from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc, zigzag_pct
from hvf_v2_charts import CHARTS, reference_prices

c = next(x for x in CHARTS if x["name"] == "USDJPY 1W")
_, _, _, A, B = reference_prices(c)
want = [c["rh2"], c["rl2"], c["rh3"], c["rl3"]]

src = load_ohlc(str(ROOT / "backtests/data/hvf_v2/USDJPY_D1.csv"))
frame = resample_ohlc(src, 168, 24)
piv = zigzag_pct(frame, 3.0)

# The six, by (kind, month) as read off the box-3.0% listing.
picks = [("H", "2024-06"), ("L", "2024-09"), ("H", "2025-01"),
         ("L", "2025-04"), ("H", "2025-08"), ("L", "2025-09")]
sel = []
for kind, mon in picks:
    cands = [p for p in piv if p.kind == kind and f"{p.ts:%Y-%m}" == mon]
    # the extreme one in that month, which is what a coarser degree would keep
    sel.append(max(cands, key=lambda p: p.price) if kind == "H"
               else min(cands, key=lambda p: p.price))

h1, rl1, rh2, rl2, rh3, rl3 = sel
b, a = h1.price, rl1.price
rng = b - a
got = [(p.price - a) / rng for p in (rh2, rl2, rh3, rl3)]
err = sum(abs(g - w) for g, w in zip(got, want)) / 4.0

print(f"candidate a={a:.3f} ({rl1.ts:%Y-%m-%d})  b={b:.3f} ({h1.ts:%Y-%m-%d})")
print(f"AMP1 {rng:.3f} vs reference {B - A:.3f}  -> "
      f"{100 * abs(rng - (B - A)) / (B - A):.1f}% off\n")
print(f"{'pivot':<6}{'date':<13}{'price':>10}{'got fib':>10}{'want':>8}{'err':>8}")
for nm, p, g, w in zip(("RH2", "RL2", "RH3", "RL3"), (rh2, rl2, rh3, rl3), got, want):
    print(f"{nm:<6}{p.ts:%Y-%m-%d}  {p.price:>10.3f}{g:>10.3f}{w:>8.2f}{abs(g - w):>8.3f}")

print(f"\nmean |fib error| = {err:.4f}   (null floor 0.0820, "
      f"detector's best 0.3287)")
idx = [piv.index(p) for p in sel]
print(f"pivot indices {idx} -> gaps between consecutive funnel pivots: "
      f"{[idx[i + 1] - idx[i] for i in range(5)]}")
