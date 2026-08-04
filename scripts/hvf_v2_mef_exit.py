"""The exit rule (spec 8.26).

Untouched since 8.21 flagged it, and 8.21's evidence that it matters is direct:
7 of Hunt's 8 setups reach >=1R of favourable excursion but only 2 of the 4
resolved trades banked it. Everything from 8.22 to 8.25 has used one exit --
a measured move of AMP1 from entry, stop at the 6th pivot, no trail, no time
limit -- and never asked whether it is the right one.

Fourteen rules, in four families:

  fixed R      exit at k*R. Trades payoff for hit rate along 8.24's curve.
  breakeven    AMP1 target, stop to entry once k*R of excursion is banked.
  trailing     AMP1 target, stop trailed m*ATR14 behind the running extreme.
  partial      half off at k*R, remainder to AMP1 with the stop at entry.
  time         AMP1 target abandoned at market after n funnel-spans.

Chosen on the SIX calibration charts and reported blind on the two pre-committed
held-out ones, because 8.20, 8.24 and 8.25 were each killed by exactly this test
and an exit rule has more free parameters than any of them.

Sequencing is re-run per rule: changing the exit changes when capital frees up
and therefore which later trades are taken at all. Evaluating rules against one
fixed trade list would quietly compare them on different opportunity sets.
"""
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr  # noqa: E402
from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import HELD_OUT  # noqa: E402
from hvf_v2_mef_ablation import NSEED, RAND_HI, RAND_LO  # noqa: E402
from hvf_v2_mef_stopfilter import CACHE, top  # noqa: E402

RULES = [
    ("AMP1 target (baseline)", dict()),
    ("fixed 1R", dict(fixed=1.0)),
    ("fixed 2R", dict(fixed=2.0)),
    ("fixed 3R", dict(fixed=3.0)),
    ("fixed 4R", dict(fixed=4.0)),
    ("fixed 5R", dict(fixed=5.0)),
    ("AMP1 + BE at 1R", dict(be=1.0)),
    ("AMP1 + BE at 2R", dict(be=2.0)),
    ("AMP1 + trail 2 ATR", dict(trail=2.0)),
    ("AMP1 + trail 3 ATR", dict(trail=3.0)),
    ("AMP1 + trail 5 ATR", dict(trail=5.0)),
    ("half 2R, rest AMP1+BE", dict(partial=2.0)),
    ("half 3R, rest AMP1+BE", dict(partial=3.0)),
    ("AMP1, time stop 3 spans", dict(tmax=3)),
    ("AMP1, time stop 10 spans", dict(tmax=10)),
]


def simulate(frame, picks, rule, shift=0):
    """One pass, one position at a time. `rule` is empty for the 8.22 baseline."""
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    atr = _atr(frame, 14).to_numpy(float)
    n = len(frame)
    free, out = -1, []

    for s in sorted(picks, key=lambda x: x["arm"] + shift):
        arm = s["arm"] + shift
        if arm < 0 or arm + 1 >= n or arm <= free:
            continue
        d, risk = s["d"], s["risk"]
        e = close[arm] + s["e_off"]
        st = close[arm] + s["s_off"]
        if abs(e - st) <= 0:
            continue
        risk = abs(e - st)

        fill = None
        for i in range(arm + 1, min(arm + 1 + s["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                fill = i
                break
        if fill is None:
            continue

        tgt_R = rule["fixed"] if "fixed" in rule else s["amp"] / risk
        tgt = e + d * tgt_R * risk
        stop = st
        peak = e
        banked, size = 0.0, 1.0
        res = None

        for i in range(fill, n):
            adv = (stop - lo[i]) if d > 0 else (hi[i] - stop)
            fav_px = hi[i] if d > 0 else lo[i]
            fav_R = d * (fav_px - e) / risk

            if adv >= 0:                                  # stop first on a tie
                res = banked + size * d * (stop - e) / risk
                free = i
                break
            if fav_R >= tgt_R:
                res = banked + size * tgt_R
                free = i
                break
            if "partial" in rule and size == 1.0 and fav_R >= rule["partial"]:
                banked, size = 0.5 * rule["partial"], 0.5
                stop = e if d > 0 else e                  # remainder rides free
            if "be" in rule and fav_R >= rule["be"]:
                stop = max(stop, e) if d > 0 else min(stop, e)
            if "trail" in rule and np.isfinite(atr[i]):
                peak = max(peak, fav_px) if d > 0 else min(peak, fav_px)
                t = (peak - rule["trail"] * atr[i] if d > 0
                     else peak + rule["trail"] * atr[i])
                stop = max(stop, t) if d > 0 else min(stop, t)
            if "tmax" in rule and i - fill >= rule["tmax"] * max(s["wait"], 1):
                res = banked + size * d * (close[i] - e) / risk
                free = i
                break
        if res is not None:
            out.append(res)
    return out


store = pickle.loads(CACHE.read_bytes())
POOL = {c["name"]: (c, *store[c["name"]]) for c in CHARTS if c["name"] in store}
PICKS = {n: top(v[2]) for n, v in POOL.items()}
print(f"pool loaded ({sum(len(p) for p in PICKS.values())} shortlisted setups)",
      flush=True)

print()
print("=" * 100)
print("1. EXIT RULES -- chosen on CALIBRATION, held-out reported blind")
print("=" * 100)
print(f"{'rule':<26}" + "".join(f"{h:>24}" for h in
      ("6 calibration", "2 held-out (blind)", "all 8")))
print(f"{'':<26}" + "".join(f"{'n':>6}{'win%':>7}{'meanR':>11}" for _ in range(3)))
print("-" * 100)


def fmt(t):
    if not t:
        return f"{0:>6}{'':>7}{'':>11}"
    a = np.array(t)
    return f"{len(a):>6}{(a > 0).mean():>7.1%}{a.mean():>11.2f}"


TAB = {}
for lab, rule in RULES:
    cal, tst = [], []
    for name, (c0, frame, cands) in POOL.items():
        t = simulate(frame, PICKS[name], rule)
        (tst if name in HELD_OUT else cal).extend(t)
    TAB[lab] = (cal, tst)
    print(f"{lab:<26}{fmt(cal)}{fmt(tst)}{fmt(cal + tst)}", flush=True)
print("-" * 100)

base_c = np.mean(TAB["AMP1 target (baseline)"][0])
base_t = np.mean(TAB["AMP1 target (baseline)"][1])
best = max(TAB, key=lambda k: np.mean(TAB[k][0]) if TAB[k][0] else -9)
bc, bt = np.mean(TAB[best][0]), np.mean(TAB[best][1])
print(f"baseline           : calib {base_c:+.2f}R   held-out {base_t:+.2f}R")
print(f"best on CALIBRATION: '{best}'  calib {bc:+.2f}R "
      f"({bc - base_c:+.2f})   held-out {bt:+.2f}R ({bt - base_t:+.2f})")
print("  -> transfers" if bt > base_t else "  -> DOES NOT TRANSFER: reject")

print()
print("=" * 100)
print(f"2. PER CHART -- baseline vs '{best}'")
print("=" * 100)
print(f"{'chart':<13}{'':<3}{'base n':>8}{'base R':>9}{'new n':>8}{'new R':>9}"
      f"{'delta':>9}")
print("-" * 100)
for name, (c0, frame, cands) in POOL.items():
    a = simulate(frame, PICKS[name], {})
    b = simulate(frame, PICKS[name], dict(TAB and RULES[[r[0] for r in RULES].index(best)][1]))
    if not a and not b:
        continue
    ma = np.mean(a) if a else float("nan")
    mb = np.mean(b) if b else float("nan")
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{len(a):>8}{ma:>9.2f}"
          f"{len(b):>8}{mb:>9.2f}{mb - ma:>+9.2f}")

print()
print("=" * 100)
print(f"3. SHIFT-NULL under '{best}' -- is it the structure or the exit?")
print("=" * 100)
print(f"{'chart':<13}{'':<3}{'real':>9}{'null mean':>11}{'null sd':>9}{'pctile':>9}")
print("-" * 100)
rule = RULES[[r[0] for r in RULES].index(best)][1]
reals, nulls_all = [], []
for name, (c0, frame, cands) in POOL.items():
    a = simulate(frame, PICKS[name], rule)
    if not a:
        continue
    nulls = np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        k = [int(rng.integers(RAND_LO, RAND_HI)) * int(rng.choice([-1, 1]))
             for _ in PICKS[name]]
        sh = [dict(x, arm=x["arm"] + kk) for x, kk in zip(PICKS[name], k)]
        t = simulate(frame, sh, rule)
        nulls[s] = np.mean(t) if t else 0.0
    reals.append(np.mean(a))
    nulls_all.append(nulls)
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{np.mean(a):>9.2f}"
          f"{nulls.mean():>11.2f}{nulls.std():>9.2f}"
          f"{(nulls < np.mean(a)).mean():>9.1%}", flush=True)
print("-" * 100)
np_ = np.mean(np.array(nulls_all), axis=0)
print(f"{'POOLED':<13}{'':<3}{np.mean(reals):>9.2f}{np_.mean():>11.2f}"
      f"{np_.std():>9.2f}{(np_ < np.mean(reals)).mean():>9.1%}")
print("=" * 100)
print("Zero costs, zero slippage, one regime, non-independent trades.")


# ---------------------------------------------------------------------------
# 4-5. Every rule above shortens the trade. The measured move has to be tested
# in the other direction too, or "AMP1 wins" only means "AMP1 beats cutting it
# short" -- which is a much weaker claim than it sounds.
# ---------------------------------------------------------------------------
MULTS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 3.00]


def trades_at(mult):
    out = []
    for name, (c0, frame, cands) in POOL.items():
        p = PICKS[name]
        if mult != 1.0:
            p = [dict(q, amp=q["amp"] * mult) for q in p]
        out.extend(simulate(frame, p, {}))
    return np.array(out)


print()
print("=" * 100)
print("4. TARGET DISTANCE -- multiples of the measured move")
print("=" * 100)
print(f"{'target':<26}" + "".join(f"{h:>24}" for h in
      ("6 calibration", "2 held-out (blind)", "all 8")))
print(f"{'':<26}" + "".join(f"{'n':>6}{'win%':>7}{'meanR':>11}" for _ in range(3)))
print("-" * 100)
for m in MULTS:
    cal, tst = [], []
    for name, (c0, frame, cands) in POOL.items():
        p = PICKS[name]
        if m != 1.0:
            p = [dict(q, amp=q["amp"] * m) for q in p]
        (tst if name in HELD_OUT else cal).extend(simulate(frame, p, {}))
    lab = f"{m:.2f} x AMP1" + (" (baseline)" if m == 1.0 else "")
    print(f"{lab:<26}{fmt(cal)}{fmt(tst)}{fmt(cal + tst)}", flush=True)
print("-" * 100)

B, rng = 10000, np.random.default_rng(20260805)
base = trades_at(1.0)
print()
print("=" * 100)
print("5. IS ANY TARGET DISTANCE DISTINGUISHABLE FROM THE MEASURED MOVE?")
print("=" * 100)
print(f"{'target':<16}{'n':>6}{'mean R':>9}{'total R':>10}"
      f"{'d(mean)':>10}{'95% CI of difference':>26}{'P(better)':>11}")
print("-" * 100)
for m in MULTS:
    t = trades_at(m)
    d = (t[rng.integers(0, len(t), (B, len(t)))].mean(1)
         - base[rng.integers(0, len(base), (B, len(base)))].mean(1))
    print(f"{f'{m:.2f} x AMP1':<16}{len(t):>6}{t.mean():>9.2f}{t.sum():>10.1f}"
          f"{t.mean() - base.mean():>+10.2f}"
          f"{f'[{np.percentile(d, 2.5):+.2f}, {np.percentile(d, 97.5):+.2f}]':>26}"
          f"{(d > 0).mean():>11.1%}"
          f"{'  <- baseline' if m == 1.0 else ''}", flush=True)
print("-" * 100)
print("10,000 resamples. Trade sets differ between rules (sequencing), so these are")
print("independent bootstraps, not a paired test -- the CI is if anything too narrow.")
