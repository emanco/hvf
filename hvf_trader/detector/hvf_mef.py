"""The mutual-extreme funnel rule (spec 8.14) -- the validated HVF detector.

Promoted verbatim out of `scripts/hvf_v2_mef.py` so the live bot and the research
harness run the *same* code. The research scripts import from here; the numbers in
HVF_V2_SPEC.md remain reproducible.

Why this and not `hvf_v2.detect_hvf`: that one scans a sliding window of five
consecutive pivots, which spec 8.12 proved cannot express Hunt's USDJPY 1W funnel
(pivot gaps [7,5,5,5,1]). The funnel's degree is not globally monotone, so no
global rule over leg amplitude can find it. What does hold is a LOCAL condition --
each funnel pivot is an extreme over the window its two neighbours define:

    RL1 = min low  between H1  and RH2        RH2 = max high between RL1 and RL2
    RL2 = min low  between RH2 and RH3        RH3 = max high between RL2 and RL3

Parameter-free: no threshold, no degree index, no lookback. 8/8 on Hunt's charts.

CAUSALITY. Every interior condition references only pivots in the past at arming
time. The one live edge is RL3, a running extreme since RH3, which can still move;
a lower low simply re-arms a new funnel later.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from hvf_trader.detector.hvf_v2 import Pivot, zigzag_pct  # noqa: E402,F401

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

