"""Does the funnel do anything? (spec 8.23)

8.22 found the backtest profitable (+0.76R) but could not attribute it: its
control shuffled WHICH funnel was traded and so kept every structural feature
intact -- direction, timing, and the 2.5:1 geometry were present in the null
too. It therefore could never answer whether the six-pivot contraction matters.

The funnel does three separable jobs. It supplies a SCALE (AMP1, which 8.19's
direction gate needs), a TIMING (the breakout at the 5th pivot, armed from
RL3.confirm), and a RISK UNIT with its payoff ((rh3-rl3)*AMP1 against AMP1).
Three ablations, each removing exactly one:

  B  structure   same instrument, direction, risk distance and R:R, and the
                 same distance from price to the trigger -- but armed k bars
                 away from the funnel. If the edge survives being moved off
                 the breakout, the breakout was not what earned it.
  D  direction   every trade mirrored about its anchor. If the edge is trend
                 alignment, this must go sharply negative.
  E  gate        the same rank and geometry, selected from the UNGATED pool.
                 What 8.19 is worth in money rather than in recall.

B is expressed as an offset from the anchor's close so that risk, reward:risk
and the distance price must travel to trigger are all preserved EXACTLY; only
the coincidence that this level bounds a funnel is removed. Shift 0 with no
flip reproduces the baseline bar for bar, which is the sanity check.
"""
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import HELD_OUT, load_frame, mef_candidates  # noqa: E402
from hvf_v2_mef_backtest import FIT, FROM, coarse_table  # noqa: E402
from hvf_v2_mef_rank import BOX, GRID, K, offsets_for  # noqa: E402

CACHE = ROOT / "scripts" / ".ablation_cache.pkl"
N = 3
NSEED = 200
SHIFTS = [25, 50, 100, 250, 500]
RAND_LO, RAND_HI = 50, 1500


def enumerate_all(c0):
    """As 8.22, but keeping ungated candidates so E can be measured."""
    c, offs = offsets_for(c0)
    frame = load_frame(c, offs[0] if offs[0] is not None else None)
    piv = zigzag_pct(frame, BOX[c0["name"]])
    tab = coarse_table(frame)
    atr = _atr(frame, 14).to_numpy(float)
    close = frame["close"].to_numpy(float)

    out, seen = [], set()
    for d in (1, -1):
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            if w[-1].ts < FROM:
                continue
            key = (d,) + tuple(p.ts.value for p in w)
            if key in seen:
                continue
            seen.add(key)
            amp = abs(w[0].price - w[1].price)
            a = atr[w[0].index]
            risk = abs(w[4].price - w[5].price)
            if not (amp > 0 and a > 0 and risk > 0):
                continue
            g = int(np.argmin(np.abs(np.log(GRID)
                                     - np.log(100.0 * K * amp / abs(w[0].price)))))
            cf, pp = tab[g]
            j = int(np.searchsorted(cf, w[0].index, "right")) - 1
            if j < 0:
                continue
            mv = w[0].price - pp[j]
            trend = abs(mv)
            if trend <= 0:
                continue
            u, v = np.log(amp / a), np.log(amp / trend)
            z = np.sqrt(((u - FIT["u"][0]) / FIT["u"][1]) ** 2
                        + ((v - FIT["v"][0]) / FIT["v"][1]) ** 2)
            arm = w[5].confirm
            out.append(dict(d=d, z=float(z), amp=amp, risk=risk, arm=arm,
                            gated=bool(np.sign(mv) == d),
                            e_off=w[4].price - close[arm],
                            s_off=w[5].price - close[arm],
                            wait=w[5].index - w[0].index,
                            month=w[5].ts.tz_localize(None).to_period("M")))
    return frame, out


def run(frame, picks, shift=0, flip=False):
    """Sequential fills. shift=0, flip=False is the 8.22 baseline exactly."""
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    n = len(frame)
    free, trades = -1, []
    for s in sorted(picks, key=lambda x: x["arm"] + shift):
        arm = s["arm"] + shift
        if arm < 0 or arm + 1 >= n or arm <= free:
            continue
        d = -s["d"] if flip else s["d"]
        m = -1.0 if flip else 1.0
        e = close[arm] + m * s["e_off"]
        st = close[arm] + m * s["s_off"]
        risk = abs(e - st)
        if risk <= 0:
            continue
        fill = None
        for i in range(arm + 1, min(arm + 1 + s["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                fill = i
                break
        if fill is None:
            continue
        tgt = s["amp"] / risk
        res = None
        for i in range(fill, n):
            adv = (e - lo[i]) / risk if d > 0 else (hi[i] - e) / risk
            fav = (hi[i] - e) / risk if d > 0 else (e - lo[i]) / risk
            if adv >= 1.0:
                res, free = -1.0, i
                break
            if fav >= tgt:
                res, free = tgt, i
                break
        if res is not None:
            trades.append(res)
    return trades


def top(cands, n=N, gated=True):
    by = defaultdict(list)
    for s in cands:
        if gated and not s["gated"]:
            continue
        by[s["month"]].append(s)
    out = []
    for m, g in by.items():
        out += sorted(g, key=lambda x: x["z"])[:n]
    return out


def line(t):
    if not t:
        return f"{'--':>7}{'':>9}{'':>10}{'':>10}"
    t = np.array(t)
    return f"{len(t):>7,}{(t > 0).mean():>9.1%}{t.mean():>10.2f}{t.sum():>10.1f}"


store = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
POOL = {}
for c0 in CHARTS:
    if c0["name"] not in store:
        store[c0["name"]] = enumerate_all(c0)
        CACHE.write_bytes(pickle.dumps(store))
    frame, cands = store[c0["name"]]
    POOL[c0["name"]] = (c0, frame, cands)
print(f"pool loaded ({sum(len(v[2]) for v in POOL.values()):,} candidates, "
      f"{sum(sum(s['gated'] for s in v[2]) for v in POOL.values()):,} gated)",
      flush=True)

print()
print("=" * 104)
print(f"A. BASELINE vs ABLATIONS -- top {N}/month, per chart")
print("=" * 104)
print(f"{'chart':<13}{'':<3}" + "".join(f"{h:>36}" for h in
      ("A baseline", "D direction flipped", "E gate removed")))
print(f"{'':<13}{'':<3}" + "".join(f"{'n':>7}{'win%':>9}{'meanR':>10}{'totR':>10}"
                                   for _ in range(3)))
print("-" * 104)
BASE, FLIP, UNG = [], [], []
for name, (c0, frame, cands) in POOL.items():
    g = top(cands)
    a = run(frame, g)
    d = run(frame, g, flip=True)
    e = run(frame, top(cands, gated=False))
    BASE += a
    FLIP += d
    UNG += e
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}"
          f"{line(a)}{line(d)}{line(e)}", flush=True)
print("-" * 104)
print(f"{'ALL':<13}{'':<3}{line(BASE)}{line(FLIP)}{line(UNG)}")

print()
print("=" * 104)
print("B. STRUCTURE REMOVED -- same direction, risk, R:R and trigger distance,")
print("   armed k bars away from the funnel. k=0 must reproduce A.")
print("=" * 104)
print(f"{'chart':<13}{'':<3}" + "".join(f"{f'k={k}':>17}" for k in [0] + SHIFTS))
print(f"{'':<13}{'':<3}" + "".join(f"{'n':>7}{'meanR':>10}" for _ in [0] + SHIFTS))
print("-" * 104)
POOLED = {k: [] for k in [0] + SHIFTS}
for name, (c0, frame, cands) in POOL.items():
    g = top(cands)
    cells = ""
    for k in [0] + SHIFTS:
        t = run(frame, g, shift=k)
        POOLED[k] += t
        cells += (f"{len(t):>7,}{np.mean(t):>10.2f}" if t else f"{'--':>7}{'':>10}")
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{cells}", flush=True)
print("-" * 104)
print(f"{'ALL':<13}{'':<3}" + "".join(
    f"{len(POOLED[k]):>7,}{np.mean(POOLED[k]):>10.2f}" for k in [0] + SHIFTS))

print()
print("=" * 104)
print(f"C. NULL DISTRIBUTION -- {NSEED} random shifts, each trade moved "
      f"+/-{RAND_LO}-{RAND_HI} bars")
print("=" * 104)
print(f"{'chart':<13}{'':<3}{'real meanR':>12}{'null mean':>11}{'null sd':>9}"
      f"{'null p95':>10}{'percentile':>12}{'real win%':>11}{'null win%':>11}")
print("-" * 104)
real_means, null_acc, nullw_acc, nn = [], np.zeros(NSEED), np.zeros(NSEED), 0
for name, (c0, frame, cands) in POOL.items():
    g = top(cands)
    a = np.array(run(frame, g))
    if a.size == 0:
        continue
    nulls, nullw = np.empty(NSEED), np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        shifted = []
        for x in g:
            k = int(rng.integers(RAND_LO, RAND_HI)) * int(rng.choice([-1, 1]))
            shifted.append(dict(x, arm=x["arm"] + k))
        t = np.array(run(frame, shifted))
        nulls[s] = t.mean() if t.size else 0.0
        nullw[s] = (t > 0).mean() if t.size else 0.0
    real_means.append(a.mean())
    null_acc += nulls
    nullw_acc += nullw
    nn += 1
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{a.mean():>12.2f}"
          f"{nulls.mean():>11.2f}{nulls.std():>9.2f}"
          f"{np.percentile(nulls, 95):>10.2f}{(nulls < a.mean()).mean():>12.1%}"
          f"{(a > 0).mean():>11.1%}{nullw.mean():>11.1%}", flush=True)
print("-" * 104)
rm, nl = float(np.mean(real_means)), null_acc / nn
print(f"{'POOLED':<13}{'':<3}{rm:>12.2f}{nl.mean():>11.2f}{nl.std():>9.2f}"
      f"{np.percentile(nl, 95):>10.2f}{(nl < rm).mean():>12.1%}"
      f"{'':>11}{(nullw_acc / nn).mean():>11.1%}")
print("=" * 104)
print("Zero costs, zero slippage, one regime, non-independent trades.")
