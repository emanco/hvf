"""Does the win rate survive a larger target? (spec 8.24)

8.23 settled attribution but left the ENGINE unexamined. At 26.4% wins and
+0.76R the average winner is +5.67R, well above the 2.47R median geometry of
8.21 -- so the expectancy is carried by the tight funnels, whose risk is small
and whose measured move is many multiples of it.

That invites an obvious strategy: select on reward:risk. It is only a good idea
if the win rate HOLDS as the target recedes. Under a random walk it cannot --
the probability of travelling `T` risk-units before travelling one falls as
roughly 1/(1+T), so mean R is flat and sorting on T buys nothing. The question
is therefore not "is the payoff asymmetric" (it is, by construction) but "is the
hit rate better than the asymmetry implies".

Two measurements:

  1. bucket the 8.23 baseline trades by AMP1/risk and compare the realised win
     rate against the 1/(1+T) breakeven each bucket needs;
  2. reselect the shortlist by AMP1/risk instead of by 8.20's z-score, and put
     it against the same shift-null 8.23 used.
"""
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import HELD_OUT  # noqa: E402
from hvf_v2_mef_ablation import CACHE, N, NSEED, RAND_HI, RAND_LO, top  # noqa: E402

store = pickle.loads(CACHE.read_bytes())
POOL = {c["name"]: (c, *store[c["name"]]) for c in CHARTS if c["name"] in store}


def run_keep(frame, picks, shift=0):
    """As 8.23's `run`, but returning the target multiple alongside the result."""
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    n = len(frame)
    free, out = -1, []
    for s in sorted(picks, key=lambda x: x["arm"] + shift):
        arm = s["arm"] + shift
        if arm < 0 or arm + 1 >= n or arm <= free:
            continue
        d = s["d"]
        e, st = close[arm] + s["e_off"], close[arm] + s["s_off"]
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
        for i in range(fill, n):
            adv = (e - lo[i]) / risk if d > 0 else (hi[i] - e) / risk
            fav = (hi[i] - e) / risk if d > 0 else (e - lo[i]) / risk
            if adv >= 1.0:
                out.append((tgt, -1.0))
                free = i
                break
            if fav >= tgt:
                out.append((tgt, tgt))
                free = i
                break
    return out


print("=" * 100)
print("1. DOES THE HIT RATE SURVIVE A LARGER TARGET? -- 8.23 baseline trades")
print("=" * 100)
rows = []
for name, (c0, frame, cands) in POOL.items():
    rows += run_keep(frame, top(cands))
rows.sort(key=lambda x: x[0])
arr = np.array(rows)
print(f"{'AMP1/risk bucket':<22}{'n':>7}{'median T':>11}{'breakeven':>12}"
      f"{'realised win%':>15}{'edge':>9}{'mean R':>10}")
print("-" * 100)
qs = np.array_split(arr, 4)
for q in qs:
    t, r = q[:, 0], q[:, 1]
    be = 1.0 / (1.0 + np.median(t))
    win = (r > 0).mean()
    print(f"{f'{t.min():.2f} - {t.max():.2f}':<22}{len(q):>7}{np.median(t):>11.2f}"
          f"{be:>12.1%}{win:>15.1%}{win - be:>+9.1%}{r.mean():>10.2f}")
print("-" * 100)
be_all = 1.0 / (1.0 + np.median(arr[:, 0]))
print(f"{'ALL':<22}{len(arr):>7}{np.median(arr[:, 0]):>11.2f}{be_all:>12.1%}"
      f"{(arr[:, 1] > 0).mean():>15.1%}"
      f"{(arr[:, 1] > 0).mean() - be_all:>+9.1%}{arr[:, 1].mean():>10.2f}")
print()
w = arr[:, 1] > 0
print(f"correlation(AMP1/risk, win) = {np.corrcoef(arr[:, 0], w.astype(float))[0, 1]:+.3f}"
      f"   |   mean AMP1/risk: winners {arr[w, 0].mean():.2f}, losers {arr[~w, 0].mean():.2f}")

print()
print("=" * 100)
print(f"2. SELECT BY REWARD:RISK INSTEAD OF 8.20's RANK -- top {N}/month, vs shift-null")
print("=" * 100)
print(f"{'chart':<13}{'':<3}{'by z (8.20)':>13}{'by AMP1/risk':>14}{'null mean':>11}"
      f"{'null sd':>9}{'pctile':>9}{'n':>7}{'win%':>8}")
print("-" * 100)


def top_rr(cands, n=N):
    by = defaultdict(list)
    for s in cands:
        if s["gated"]:
            by[s["month"]].append(s)
    out = []
    for m, g in by.items():
        out += sorted(g, key=lambda x: -x["amp"] / x["risk"])[:n]
    return out


zm, rm = [], []
for name, (c0, frame, cands) in POOL.items():
    z = np.array([r for _, r in run_keep(frame, top(cands))])
    picks = top_rr(cands)
    a = np.array([r for _, r in run_keep(frame, picks)])
    if a.size == 0 or z.size == 0:
        continue
    nulls = np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        sh = [dict(x, arm=x["arm"] + int(rng.integers(RAND_LO, RAND_HI))
                   * int(rng.choice([-1, 1]))) for x in picks]
        t = np.array([r for _, r in run_keep(frame, sh)])
        nulls[s] = t.mean() if t.size else 0.0
    zm.append(z.mean())
    rm.append(a.mean())
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{z.mean():>13.2f}"
          f"{a.mean():>14.2f}{nulls.mean():>11.2f}{nulls.std():>9.2f}"
          f"{(nulls < a.mean()).mean():>9.1%}{a.size:>7}{(a > 0).mean():>8.1%}",
          flush=True)
print("-" * 100)
print(f"{'POOLED':<13}{'':<3}{np.mean(zm):>13.2f}{np.mean(rm):>14.2f}")
print("=" * 100)
print("Zero costs, zero slippage, one regime, non-independent trades.")
