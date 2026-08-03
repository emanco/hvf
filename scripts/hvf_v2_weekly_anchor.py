"""Does Hunt's USDJPY 1W funnel reproduce under ANY week-start anchor?

The acceptance suite treats a *_W1 source as native and never sweeps the anchor,
so the 0.3403 miss may be an artefact of the broker's week boundary rather than
a wrong rule (spec 11.1). Rebuild weekly bars from D1 (7 week-starts) and from
H1 (all 168 hour-starts) and re-run the same search.
"""
import sys
from pathlib import Path

ROOT = Path("/Users/manu/Dev/hvf")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd
from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc, zigzag_pct
from hvf_v2_charts import CHARTS, reference_prices

DATA = ROOT / "backtests" / "data" / "hvf_v2"
AMP_TOL = 0.35
LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")


def _grid(lo, hi, step):
    out, x = [], lo
    while x <= hi:
        out.append(round(x, 4))
        x *= step
    return out


BOXES = _grid(0.10, 12.0, 1.15)      # weekly funnels are wider; extend the top


def anchor(piv, i, want):
    best, k = None, None
    for j in range(i - 1, -1, -1):
        p = piv[j]
        if p.kind != want:
            continue
        if best is None or (p.price > best.price if want == "H" else p.price < best.price):
            best, k = p, j
        else:
            break
    return best, k


def score(h1, w, c, ref_a, ref_b):
    if c["dir"] > 0:
        b, a = h1.price, w[0].price
        want = [c["rh2"], c["rl2"], c["rh3"], c["rl3"]]
    else:
        a, b = h1.price, w[0].price
        want = [c["rl2"], c["rh2"], c["rl3"], c["rh3"]]
    if not (b > a > 0):
        return None
    rng, ref_rng = b - a, ref_b - ref_a
    if abs(rng - ref_rng) / ref_rng > AMP_TOL:
        return None
    got = [(p.price - a) / rng for p in w[1:]]
    return sum(abs(g - x) for g, x in zip(got, want)) / 4.0, got


c = next(x for x in CHARTS if x["name"] == "USDJPY 1W")
names, ref, kinds, ref_a, ref_b = reference_prices(c)
anchor_kind, run_kinds = kinds[0], kinds[1:]
print(f"reference a={ref_a:.3f} b={ref_b:.3f} AMP1={ref_b - ref_a:.3f}")
print(f"target fibs RH2={c['rh2']} RL2={c['rl2']} RH3={c['rh3']} RL3={c['rl3']}\n")


def run(frame, label, offsets, src):
    best_live = best_null = None
    for off in offsets:
        f = src if off is None else resample_ohlc(src, 168, off)
        if len(f) < 50:
            continue
        for box in BOXES:
            piv = zigzag_pct(f, box)
            for i in range(len(piv) - 4):
                w = piv[i:i + 5]
                if "".join(p.kind for p in w) != run_kinds:
                    continue
                h1, k = anchor(piv, i, anchor_kind)
                if h1 is None:
                    continue
                s = score(h1, w, c, ref_a, ref_b)
                if s is None:
                    continue
                cand = (s[0], box, off, [h1] + list(w), s[1])
                if w[-1].ts >= LIVE_FROM:
                    if best_live is None or cand[0] < best_live[0]:
                        best_live = cand
                elif best_null is None or cand[0] < best_null[0]:
                    best_null = cand
    return best_live, best_null


for label, path, offsets in [
    ("native W1", "USDJPY_W1", [None]),
    ("W1 from D1", "USDJPY_D1", list(range(0, 168, 24))),
    ("W1 from H1", "USDJPY_H1", list(range(0, 168, 4))),
]:
    src = load_ohlc(str(DATA / f"{path}.csv"))
    live, null = run(None, label, offsets, src)
    if live is None:
        print(f"{label:<12} no 2026 candidate")
        continue
    err, box, off, w, got = live
    nl = f"{null[0]:.4f}" if null else "--"
    print(f"{label:<12} best fib err {err:.4f}  (null {nl})  box {box}%  "
          f"anchor {off}  {w[0].ts:%Y-%m-%d}..{w[-1].ts:%Y-%m-%d}")
    print(f"{'':<12}   got {[round(g, 2) for g in got]}")
