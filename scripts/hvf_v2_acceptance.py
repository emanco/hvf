"""Acceptance test: does the v2 detector find the funnels Hunt drew?

This is the test the retired implementation never had. It asks about
*correctness*, not profitability, and it must pass before any performance number
from this strategy means anything.

Reference prices are not read off the charts, they are *solved* from the panel
(see `hvf_v2_charts`), so the reference is independent of pixel-reading.

Three defects in the first version of this harness are worth stating, because
each produced a false negative and each is easy to reintroduce (spec 8.3):

  1. The box sweep was a hand-picked list stepping 0.5 -> 0.75, and gold's
     admissible band is 0.60-0.74. The sweep is now geometric at 1.15x.
  2. Scoring was normalised by PRICE. Gold's whole funnel spans 1.5% of price,
     so any six pivots inside it scored under 1.5% automatically. Scoring is now
     in FIB units, where the panel's 2dp printing sets the tolerance, and the
     candidate's own range must be near the reference range.
  3. Nothing anchored the match in TIME, so the search returned the best
     coincidence in 26 years -- USDJPY 4h "matched" in 2016, USDJPY 1W in 1998.
     The chart filenames are epoch-ms and run 2026-03-12..2026-07-31, so a match
     must now END in 2026.
  4. All six pivots were required to be CONSECUTIVE. They are not, and cannot
     be: the funnel interior and the exhaustion leg live at different degrees.
     At a box fine enough to emit RH3/RL3, the H1 -> RL1 leg is subdivided; at a
     box coarse enough to keep H1 adjacent, RH3/RL3 never print. See `anchor`.

That last point also gives a free negative control: the same search restricted
to everything BEFORE 2026 cannot be finding Hunt's setups, so its best score
measures the noise floor. A pass is only meaningful well below that floor.

Calibration/test split is pre-committed in spec 8.4 and must not be revised to
suit a result.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    detect_hvf, load_ohlc, ratio_series, resample_ohlc, zigzag_pct,
    prior_trend_extreme_of_m, prior_trend_atr_span, prior_trend_slope,
)
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402

DATA = ROOT / "backtests" / "data" / "hvf_v2"
BAR = "=" * 104

# Spec 8.4, pre-committed.
HELD_OUT = {"BTCUSD 1h", "XAUEUR 1h"}

# Spec 4.1: geometric, step <= 1.15x. A hand-picked list is what hid the answer.
def _grid(lo, hi, step):
    out, x = [], lo
    while x <= hi:
        out.append(round(x, 4))
        x *= step
    return out


BOX_SIZES = _grid(0.10, 5.0, 1.15)
LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")   # charts posted 2026-03..07
PASS_FIB = 0.02          # the panel prints fibs to 2dp
NEAR_FIB = 0.05
AMP_TOL = 0.25           # candidate range within 25% of reference


def load_frame(c):
    src = load_ohlc(str(DATA / f"{c['src']}.csv"))
    if c["ratio"]:
        src = ratio_series(src, load_ohlc(str(DATA / f"{c['ratio']}.csv")))
    return src


def anchor(piv, i, want_kind):
    """The swing extreme that started the move into the funnel's first pivot.

    The exhaustion leg is a larger degree than the funnel it precedes, so a box
    that resolves the funnel shatters that leg into sub-pivots and H1 stops
    being adjacent to RH2. Recover it without a second box size: walk backwards
    from RL1 keeping a running extreme of same-kind pivots and stop at the last
    one that improved it -- the origin of the run of lower highs (or higher
    lows, short side). Parameter-free, and it reduces to the old adjacency rule
    whenever the leg happens to be a single clean swing, as it is for gold.
    """
    best, k, j = None, None, i - 1
    while j >= 0:
        p = piv[j]
        if p.kind == want_kind:
            if best is None or (p.price > best.price if want_kind == "H"
                                else p.price < best.price):
                best, k = p, j
            else:
                break
        j -= 1
    return best, k


def score(h1, w, c, ref_a, ref_b):
    """Mean |fib error| over the four funnel pivots, in the candidate's frame."""
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
    err = sum(abs(g - x) for g, x in zip(got, want)) / 4.0
    return err, got, 100.0 * abs(rng - ref_rng) / ref_rng


def search(c):
    """Best live match and best pre-2026 match, from one pass over the sweep."""
    names, ref, kinds, ref_a, ref_b = reference_prices(c)
    src = load_frame(c)
    native = c["src"].endswith("_W1") or c["hours"] == 1
    offsets = [None] if native else list(range(int(c["hours"])))
    anchor_kind, run_kinds = kinds[0], kinds[1:]

    best_live = best_null = None
    for off in offsets:
        frame = src if off is None else resample_ohlc(src, c["hours"], off)
        for box in BOX_SIZES:
            piv = zigzag_pct(frame, box)
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
                cand = (s[0], box, off, [h1] + list(w), s[1], s[2], i - k)
                live = w[-1].ts >= LIVE_FROM
                if live:
                    if best_live is None or cand[0] < best_live[0]:
                        best_live = cand
                elif best_null is None or cand[0] < best_null[0]:
                    best_null = cand
    return names, best_live, best_null


print(BAR)
print("STAGE A -- PRESENCE: does a percentage ZigZag reproduce Hunt's six pivots?")
print(f"  box sweep: {len(BOX_SIZES)} sizes, {BOX_SIZES[0]}%..{BOX_SIZES[-1]}% "
      f"geometric x1.15   |   pass <= {PASS_FIB} fib")
print(BAR)
print(f"{'chart':<13}{'set':<7}{'box%':>6}{'anch':>5}{'fib err':>9}{'AMP1':>7}"
      f"{'gap':>5}{'verdict':>9}{'null':>8}   matched window")
print("-" * 104)

results = {}
for c in CHARTS:
    names, live, null = search(c)
    tag = "TEST" if c["name"] in HELD_OUT else "calib"
    nullv = f"{null[0]:.3f}" if null else "--"
    if live is None:
        print(f"{c['name']:<13}{tag:<7}{'--':>6}{'--':>5}{'--':>9}{'--':>7}{'--':>5}"
              f"{'NONE':>9}{nullv:>8}   no 2026 window at a comparable scale")
        continue
    err, box, off, w, got, amp, gap = live
    verdict = "MATCH" if err <= PASS_FIB else ("near" if err <= NEAR_FIB else "MISS")
    print(f"{c['name']:<13}{tag:<7}{box:>6}{str(off):>5}{err:>9.4f}{amp:>6.1f}%"
          f"{gap:>5}{verdict:>9}{nullv:>8}   "
          f"{w[0].ts:%Y-%m-%d} .. {w[-1].ts:%Y-%m-%d}")
    results[c["name"]] = dict(c=c, err=err, box=box, off=off, w=w, got=got,
                              names=names, null=null[0] if null else None, gap=gap)

print()
print(BAR)
print("fib coordinates, panel vs found")
print(BAR)
for name, r in results.items():
    c, names = r["c"], r["names"]
    want = ([c["rh2"], c["rl2"], c["rh3"], c["rl3"]] if c["dir"] > 0
            else [c["rl2"], c["rh2"], c["rl3"], c["rh3"]])
    print(f"  {name:<13}" + "  ".join(f"{n}: {x:.2f}/{g:.2f}"
                                      for n, x, g in zip(names[2:], want, r["got"])))

print()
print(BAR)
print("STAGE B -- ADMISSION: does the full detector emit the matched pattern?")
print("NB: detect_hvf still requires six CONSECUTIVE pivots, so any match with")
print("    gap > 1 above cannot be emitted until the anchor rule is ported to it.")
print(BAR)
TESTS = {
    "extreme_of_m(100)": prior_trend_extreme_of_m(100),
    "extreme_of_m(50)": prior_trend_extreme_of_m(50),
    "atr_span(k=4,n=100)": prior_trend_atr_span(4.0, 100),
    "atr_span(k=3,n=50)": prior_trend_atr_span(3.0, 50),
    "slope(n=100,r2=0.5)": prior_trend_slope(100, 0.5),
    "slope(n=50,r2=0.3)": prior_trend_slope(50, 0.3),
}
print(f"{'chart':<13}{'prior-trend test':<22}{'emitted?':>10}{'n_found':>9}   rejections")
print("-" * 104)
for name, r in results.items():
    if r["err"] > NEAR_FIB:
        continue
    c = r["c"]
    src = load_frame(c)
    frame = src if r["off"] is None else resample_ohlc(src, c["hours"], r["off"])
    lo, hi = r["w"][0].index, r["w"][-1].index
    for label, test in TESTS.items():
        found, rej = detect_hvf(frame, bar_hours=c["hours"], box_pct=r["box"],
                                prior_trend=test)
        hit = any(f.pivots[0].index == lo and f.pivots[-1].index == hi for f in found)
        interesting = {k: v for k, v in rej.as_dict().items()
                       if v and k not in ("candidates", "admitted")}
        print(f"{name:<13}{label:<22}{('YES' if hit else 'no'):>10}{len(found):>9}   "
              f"{interesting}")
    print()

print(BAR)
for label, members in (("CALIBRATION", [c for c in CHARTS if c["name"] not in HELD_OUT]),
                       ("HELD-OUT TEST", [c for c in CHARTS if c["name"] in HELD_OUT])):
    got = [results[c["name"]] for c in members if c["name"] in results]
    n_m = sum(1 for r in got if r["err"] <= PASS_FIB)
    n_n = sum(1 for r in got if PASS_FIB < r["err"] <= NEAR_FIB)
    print(f"{label:<15} {n_m} matched, {n_n} near, {len(members) - n_m - n_n} missed"
          f"  (of {len(members)})")
nulls = [r["null"] for r in results.values() if r["null"] is not None]
if nulls:
    print(f"\nNegative control: best pre-2026 score {min(nulls):.4f} fib "
          f"(median {sorted(nulls)[len(nulls) // 2]:.4f}). A match is only "
          f"meaningful well below this.")
print(BAR)
