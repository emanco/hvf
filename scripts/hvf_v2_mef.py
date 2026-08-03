"""Multi-degree funnel selection: the MUTUAL-EXTREME rule (spec 8.14).

Spec 8.12 showed the detector's `anchor + 5 consecutive pivots` model cannot
express Hunt's USDJPY 1W funnel, whose pivot gaps are [7,5,5,5,1]. Two obvious
repairs were tried on paper first and both fail on that chart's own numbers:

  * A ZigZag whose reversal threshold shrinks with the funnel. To confirm
    RH3=0.51 the threshold must be <= 0.26 (the drop into RL3), but an earlier
    pullback inside the same leg is 0.31 (0.40 -> 0.09) and would have confirmed
    0.40 as the high first. The admissible interval is empty.
  * Hierarchical degree reduction (repeatedly delete the smallest leg). The
    funnel's LAST leg is 0.26 while the noise legs inside it run to 0.41, so any
    reduction coarse enough to clear the noise deletes RH3->RL3 first.

Both fail for the same reason: they are GLOBAL rules over leg amplitude, and the
funnel's degree is not globally monotone. What does hold is a LOCAL condition --
each funnel pivot is the extreme of the window its two neighbours define:

    RL1 = min low  between H1  and RH2      RL2 = min low  between RH2 and RH3
    RH2 = max high between RL1 and RL2      RH3 = max high between RL2 and RL3

verified exactly on USDJPY 1W. This is `_anchor_pivot` -- already the accepted
fix for the H1->RL1 leg in spec 4.3 -- generalised from one leg to all of them,
which is what 8.12 diagnosed. It is parameter-free: no threshold, no degree
index, no lookback.

CAUSALITY. Every interior condition references only pivots that are in the past
at arming time, so it is causal by construction. The one live edge is RL3, which
is defined as the running extreme since RH3 and can therefore still move: a
lower low simply re-arms a new funnel later. Selection must use only pivots
CONFIRMED by the evaluation bar, never `Pivot.index` (spec 8.9).

WHAT CHANGED IN THE TEST, AND WHY. Two things, both forced by the rule rather
than chosen to suit it:

  1. Liveness is now measured in BARS, not on a calendar. See LIVE_BARS.
  2. The pass criterion is no longer "best live score beats the best pre-2026
     score". That comparison is broken here. The rule emits ~40 live candidates
     against ~20,000 pre-2026 ones on gold, and the minimum of 20,000 draws is
     far below the minimum of 40 for arithmetic reasons alone -- so a bare floor
     comparison silently penalises the live side by a factor that varies per
     chart. The test is now a rank: what fraction of NULL candidates score at
     least as well as the best LIVE one, times the number of live candidates.
     That is the expected number of coincidences this good, and it is what
     "could this have happened by chance" actually means. Pre-committed at
     E < 0.05 before any chart beyond the two already inspected was run.

Candidates are also deduplicated by their six timestamps. The MEF condition is
scale-invariant, so the same funnel reappears at every box fine enough to print
it -- USDJPY 1W's appears at 26 of 28 boxes -- and counting it 26 times would
corrupt both sides of the rank.

Search is bounded by "previous/next more-extreme same-kind pivot". Those walls,
and the record runs between them, are precomputed once per pivot list with
monotonic stacks, so enumeration costs O(candidates) rather than O(n) per step.
"""
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    load_ohlc, ratio_series, resample_ohlc, zigzag_pct,
)
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402

DATA = ROOT / "backtests" / "data" / "hvf_v2"
BAR = "=" * 108

# Unchanged from hvf_v2_acceptance (spec 8.3, 8.4).
HELD_OUT = {"BTCUSD 1h", "XAUEUR 1h"}
PASS_FIB = 0.02
NEAR_FIB = 0.05
AMP_TOL = 0.25
PASS_E = 0.05            # expected coincidences this good; pre-committed

# Spec 8.3 defect 3 anchored a match in TIME with a flat `ends in 2026` rule.
# That is a bar-count statement disguised as a date, and on the weekly chart it
# is wrong: Hunt posted these between 2026-03 and 2026-07, and USDJPY 1W's RL3
# is 2025-09-12 -- 25 weeks before the earliest chart, but only 25 BARS, which
# on a 1h chart would be a day. So the bound is scaled by the bar period. For
# every chart of 18h or less this is 2026-01-01 give or take a fortnight, i.e.
# the old rule; only the weekly moves materially.
LIVE_ANCHOR = pd.Timestamp("2026-01-01", tz="UTC")
LIVE_BARS = 30


def _grid(lo, hi, step):
    out, x = [], lo
    while x <= hi:
        out.append(round(x, 4))
        x *= step
    return out


BOX_SIZES = _grid(0.10, 5.0, 1.15)


def build_index(piv):
    """Walls and record chains, in one forward and one backward pass.

    prev_of[k][i] / next_of[k][i]  nearest pivot of kind k either side of i
    prev_beyond[i] / next_beyond[i]  nearest same-kind pivot MORE extreme than i

    The running-extreme run walking back from i is then just the chain
    prev_of -> prev_beyond -> prev_beyond -> ..., which is why enumeration does
    not pay a scan per step.
    """
    n = len(piv)
    price = [p.price for p in piv]
    kind = [p.kind for p in piv]
    prev_of = {"H": [-1] * n, "L": [-1] * n}
    next_of = {"H": [n] * n, "L": [n] * n}
    prev_beyond = [-1] * n
    next_beyond = [n] * n

    last = {"H": -1, "L": -1}
    stack = {"H": [], "L": []}
    for i in range(n):
        k = kind[i]
        prev_of["H"][i], prev_of["L"][i] = last["H"], last["L"]
        st = stack[k]
        if k == "H":
            while st and price[st[-1]] <= price[i]:
                st.pop()
        else:
            while st and price[st[-1]] >= price[i]:
                st.pop()
        prev_beyond[i] = st[-1] if st else -1
        st.append(i)
        last[k] = i

    last = {"H": n, "L": n}
    stack = {"H": [], "L": []}
    for i in range(n - 1, -1, -1):
        k = kind[i]
        next_of["H"][i], next_of["L"][i] = last["H"], last["L"]
        st = stack[k]
        if k == "H":
            while st and price[st[-1]] <= price[i]:
                st.pop()
        else:
            while st and price[st[-1]] >= price[i]:
                st.pop()
        next_beyond[i] = st[-1] if st else n
        st.append(i)
        last[k] = i

    return dict(price=price, kind=kind, prev_of=prev_of, next_of=next_of,
                prev_beyond=prev_beyond, next_beyond=next_beyond, n=n)


def _back_run(ix, start, kind, floor):
    """Same-kind pivots that are the running extreme walking back from start."""
    j = ix["prev_of"][kind][start]
    while j >= floor:
        yield j
        j = ix["prev_beyond"][j]


def _fwd_run(ix, start, kind, ceil):
    j = ix["next_of"][kind][start]
    while j <= ceil:
        yield j
        j = ix["next_beyond"][j]


def mef_candidates(piv, direction, keep_ab=None):
    """Every 6-pivot funnel satisfying the mutual-extreme and contraction rules.

    Bullish kinds are H L H L H L (H1 RL1 RH2 RL2 RH3 RL3); bearish mirrors.
    Enumerated around i3 -- the pivot both interior conditions hinge on -- so the
    two halves can be built independently and joined.

    `keep_ab(p0, p1)` is an optional prune on the funnel's own range, applied as
    soon as H1 and RL1 are fixed. It is a search economy only: it can discard
    candidates but never reorders or invents them.
    """
    ix = build_index(piv)
    n, price, kind = ix["n"], ix["price"], ix["kind"]
    if n < 6:
        return
    kA = "H" if direction > 0 else "L"          # kinds at positions 0, 2, 4
    kB = "L" if direction > 0 else "H"          # kinds at positions 1, 3, 5
    if kA == "H":
        def hi(a, b): return a > b
        def lo(a, b): return a < b
    else:
        def hi(a, b): return a < b
        def lo(a, b): return a > b

    for i3 in range(n):
        if kind[i3] != kB:
            continue
        left_wall = max(ix["prev_beyond"][i3], 0)    # i2 sits at or after this
        right_wall = min(ix["next_beyond"][i3], n - 1)

        for i2 in _back_run(ix, i3, kA, left_wall):
            w1 = max(ix["prev_beyond"][i2], 0)
            for i1 in _back_run(ix, i2, kB, w1):
                if not lo(price[i1], price[i3]):
                    continue                          # RL2 must retract vs RL1
                w0 = max(ix["prev_beyond"][i1], 0)
                for i0 in _back_run(ix, i1, kA, w0):
                    if not hi(price[i0], price[i2]):
                        continue                      # RH2 must contract vs H1
                    if keep_ab is not None and not keep_ab(price[i0], price[i1]):
                        continue
                    for i4 in _fwd_run(ix, i3, kA, right_wall):
                        if not hi(price[i2], price[i4]):
                            continue                  # RH3 contracts vs RH2
                        w5 = min(ix["next_beyond"][i4], n - 1)
                        for i5 in _fwd_run(ix, i4, kB, w5):
                            if not lo(price[i3], price[i5]):
                                continue              # RL3 retracts vs RL2
                            yield (i0, i1, i2, i3, i4, i5)


def amp_gate(c, ref_a, ref_b):
    """The AMP_TOL test, expressed on (H1, RL1) alone so it can prune."""
    ref_rng = ref_b - ref_a

    def keep(p0, p1):
        b, a = (p0, p1) if c["dir"] > 0 else (p1, p0)
        if not (b > a > 0):
            return False
        return abs((b - a) - ref_rng) / ref_rng <= AMP_TOL
    return keep


def score(w, c, ref_a, ref_b):
    """Mean |fib error| over the four funnel pivots, in the candidate's frame."""
    h1, rl1 = w[0], w[1]
    if c["dir"] > 0:
        b, a = h1.price, rl1.price
        want = [c["rh2"], c["rl2"], c["rh3"], c["rl3"]]
    else:
        a, b = h1.price, rl1.price
        want = [c["rl2"], c["rh2"], c["rl3"], c["rh3"]]
    if not (b > a > 0):
        return None
    rng, ref_rng = b - a, ref_b - ref_a
    amp = abs(rng - ref_rng) / ref_rng
    if amp > AMP_TOL:
        return None
    got = [(p.price - a) / rng for p in w[2:]]
    return sum(abs(g - x) for g, x in zip(got, want)) / 4.0, got, 100.0 * amp


def load_frame(c, off):
    src = load_ohlc(str(DATA / f"{c['src']}.csv"))
    if c["ratio"]:
        src = ratio_series(src, load_ohlc(str(DATA / f"{c['ratio']}.csv")))
    if off is None:
        return src
    return resample_ohlc(src, c["hours"], off)


def search(c):
    """Every distinct MEF funnel, scored, split into live and null populations."""
    _, _, _, ref_a, ref_b = reference_prices(c)
    keep = amp_gate(c, ref_a, ref_b)
    live_from = LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c["hours"])

    # Spec 8.12: the old harness treated a *_W1 source as native and so never
    # swept the week-start. Resample the daily bars instead, all 7 anchors.
    if c["src"].endswith("_W1"):
        c = dict(c, src=c["src"].replace("_W1", "_D1"))
        offsets = list(range(0, 168, 24))
    elif c["hours"] == 1:
        offsets = [None]
    else:
        offsets = list(range(int(c["hours"])))

    live, null, seen = {}, {}, 0
    for off in offsets:
        frame = load_frame(c, off)
        if frame is None or len(frame) < 50:
            continue
        for box in BOX_SIZES:
            piv = zigzag_pct(frame, box)
            if len(piv) < 6:
                continue
            for idx in mef_candidates(piv, c["dir"], keep_ab=keep):
                w = [piv[j] for j in idx]
                s = score(w, c, ref_a, ref_b)
                if s is None:
                    continue
                seen += 1
                key = tuple(p.ts.value for p in w)
                bucket = live if w[-1].ts >= live_from else null
                if key not in bucket:
                    bucket[key] = (s[0], box, off, w, s[1], s[2], idx)
    return live, null, seen, live_from


def verdict(live, null):
    """Best live match, and the expected number of null coincidences that good."""
    if not live:
        return None
    best = min(live.values(), key=lambda v: v[0])
    err = best[0]
    n_null = len(null)
    k = sum(1 for v in null.values() if v[0] <= err)
    p = (k + 1) / (n_null + 1)          # +1: never claim a rate of exactly zero
    return best, p * len(live), k, n_null, len(live)


if __name__ == "__main__":
    print(BAR, flush=True)
    print("MUTUAL-EXTREME RULE -- does it find the funnels Hunt drew?")
    print(f"  box sweep {BOX_SIZES[0]}%..{BOX_SIZES[-1]}% x1.15, deduped  |  "
          f"shape: fib <= {PASS_FIB}  |  evidence: E < {PASS_E} expected "
          f"coincidences")
    print(BAR, flush=True)
    print(f"{'chart':<13}{'set':<7}{'box%':>6}{'anch':>5}{'fib err':>9}{'AMP1':>7}"
          f"{'shape':>7}{'live':>7}{'null':>9}{'k':>4}{'E':>9}{'s':>7}"
          f"{'gaps':>17}   matched window", flush=True)
    print("-" * 108, flush=True)

    tally, detail = {}, []
    for c in CHARTS:
        t0 = time.time()
        try:
            live, null, seen, live_from = search(c)
        except FileNotFoundError as e:
            print(f"{c['name']:<13}{'--':<7} no feed ({e})", flush=True)
            continue
        dt = time.time() - t0
        tag = "TEST" if c["name"] in HELD_OUT else "calib"
        v = verdict(live, null)
        if v is None:
            print(f"{c['name']:<13}{tag:<7}{'--':>6}{'--':>5}{'--':>9}{'--':>7}"
                  f"{'NONE':>7}{0:>7}{len(null):>9}{'--':>4}{'--':>9}{dt:>7.1f}"
                  f"{'--':>17}   nothing live since {live_from:%Y-%m-%d}",
                  flush=True)
            tally.setdefault(tag, []).append("NONE")
            continue
        best, E, k, n_null, n_live = v
        err, box, off, w, got, amp, idx = best
        shape = "MATCH" if err <= PASS_FIB else ("near" if err <= NEAR_FIB
                                                 else "MISS")
        ok = shape != "MISS" and E < PASS_E
        gaps = [idx[i + 1] - idx[i] for i in range(5)]
        print(f"{c['name']:<13}{tag:<7}{box:>6}{str(off):>5}{err:>9.4f}{amp:>6.1f}%"
              f"{shape:>7}{n_live:>7}{n_null:>9,}{k:>4}{E:>9.3f}{dt:>7.1f}"
              f"{str(gaps):>17}   {w[0].ts:%Y-%m-%d} .. {w[-1].ts:%Y-%m-%d}"
              f"{'' if ok else '   <-- fails'}", flush=True)
        tally.setdefault(tag, []).append("PASS" if ok else shape)
        detail.append((c, got))

    print(f"\n{BAR}\nfib coordinates, panel vs found\n{BAR}", flush=True)
    for c, got in detail:
        want = ([c["rh2"], c["rl2"], c["rh3"], c["rl3"]] if c["dir"] > 0
                else [c["rl2"], c["rh2"], c["rl3"], c["rh3"]])
        names = (["RH2", "RL2", "RH3", "RL3"] if c["dir"] > 0
                 else ["RL2", "RH2", "RL3", "RH3"])
        print(f"  {c['name']:<13}" + "  ".join(f"{n}: {x:.2f}/{g:.2f}"
              for n, x, g in zip(names, want, got)), flush=True)

    print(f"\n{BAR}", flush=True)
    for tag, vs in tally.items():
        print(f"{tag:<7} {vs.count('PASS')} pass  (of {len(vs)}) -- others: "
              f"{[x for x in vs if x != 'PASS']}", flush=True)
    print(BAR, flush=True)
