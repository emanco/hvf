"""A minimum stop distance in ATR units (spec 8.25).

8.24 found the payoff asymmetry real at every size but collapsing past
AMP1/risk ~ 10, and diagnosed the cause: AMP1/risk is 1/(rh3-rl3), so an extreme
value means the last two pivots nearly coincide, the stop sits inside single-bar
noise, and it is taken out before the structure can resolve. That is a statement
about `risk` against VOLATILITY, not against AMP1 -- so the principled filter is

    risk / ATR14 >= threshold      measured at the bar the trade arms

which unlike 8.20's prior has a mechanism behind it rather than a fit to eight
charts. It was suggested by the 8.24 data, so it is validated the only way that
means anything here: the threshold is chosen on the six CALIBRATION charts and
then applied, unchanged, to the two pre-committed held-out ones.

Two ATRs are recorded because they answer different questions -- at H1 (the
anchor, as 8.20 used) and at RL3.confirm (when the trade actually starts, which
is the one the noise argument is about).
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
from hvf_v2_mef_ablation import NSEED, RAND_HI, RAND_LO  # noqa: E402
from hvf_v2_mef_backtest import FIT, FROM, coarse_table  # noqa: E402
from hvf_v2_mef_payoff import run_keep  # noqa: E402
from hvf_v2_mef_rank import BOX, GRID, K, offsets_for  # noqa: E402

CACHE = ROOT / "scripts" / ".stopfilter_cache.pkl"
N = 3
THRESHOLDS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def enumerate_all(c0):
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
            a0, arm = atr[w[0].index], w[5].confirm
            a1 = atr[arm] if arm < len(atr) else np.nan
            risk = abs(w[4].price - w[5].price)
            if not (amp > 0 and a0 > 0 and risk > 0 and a1 > 0):
                continue
            g = int(np.argmin(np.abs(np.log(GRID)
                                     - np.log(100.0 * K * amp / abs(w[0].price)))))
            cf, pp = tab[g]
            j = int(np.searchsorted(cf, w[0].index, "right")) - 1
            if j < 0:
                continue
            mv = w[0].price - pp[j]
            if abs(mv) <= 0:
                continue
            u, v = np.log(amp / a0), np.log(amp / abs(mv))
            z = np.sqrt(((u - FIT["u"][0]) / FIT["u"][1]) ** 2
                        + ((v - FIT["v"][0]) / FIT["v"][1]) ** 2)
            out.append(dict(d=d, z=float(z), amp=amp, risk=risk, arm=arm,
                            gated=bool(np.sign(mv) == d),
                            ratr=float(risk / a1), ratr0=float(risk / a0),
                            e_off=w[4].price - close[arm],
                            s_off=w[5].price - close[arm],
                            wait=w[5].index - w[0].index,
                            month=w[5].ts.tz_localize(None).to_period("M")))
    return frame, out


def top(cands, thr=0.0, n=N):
    by = defaultdict(list)
    for s in cands:
        if s["gated"] and s["ratr"] >= thr:
            by[s["month"]].append(s)
    out = []
    for m, g in by.items():
        out += sorted(g, key=lambda x: x["z"])[:n]
    return out


store = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
POOL = {}
for c0 in CHARTS:
    if c0["name"] not in store:
        store[c0["name"]] = enumerate_all(c0)
        CACHE.write_bytes(pickle.dumps(store))
    POOL[c0["name"]] = (c0, *store[c0["name"]])
print(f"pool loaded ({sum(len(v[2]) for v in POOL.values()):,} candidates)", flush=True)

# --------------------------------------------------------------------------
print()
print("=" * 100)
print("1. IS THE MECHANISM THERE? -- baseline trades bucketed by risk/ATR14 at arm")
print("=" * 100)
rows = []
for name, (c0, frame, cands) in POOL.items():
    picks = top(cands)
    keep = {(p["arm"], round(p["risk"], 10)): p for p in picks}
    for t, r in run_keep(frame, picks):
        # recover the pick this trade came from by its target multiple
        pass
    # simpler: re-run per pick so the association is exact
    for p in picks:
        res = run_keep(frame, [p])
        if res:
            rows.append((p["ratr"], p["amp"] / p["risk"], res[0][1]))
arr = np.array(rows)
print(f"{'risk/ATR bucket':<20}{'n':>7}{'median T':>11}{'breakeven':>12}"
      f"{'realised win%':>15}{'edge':>9}{'mean R':>10}")
print("-" * 100)
order = arr[arr[:, 0].argsort()]
for q in np.array_split(order, 4):
    be = 1.0 / (1.0 + np.median(q[:, 1]))
    win = (q[:, 2] > 0).mean()
    print(f"{f'{q[0, 0]:.2f} - {q[-1, 0]:.2f}':<20}{len(q):>7}{np.median(q[:, 1]):>11.2f}"
          f"{be:>12.1%}{win:>15.1%}{win - be:>+9.1%}{q[:, 2].mean():>10.2f}")
print("-" * 100)
print(f"corr(risk/ATR, win) = {np.corrcoef(arr[:, 0], (arr[:, 2] > 0))[0, 1]:+.3f}"
      f"   |   corr(risk/ATR, AMP1/risk) = {np.corrcoef(arr[:, 0], arr[:, 1])[0, 1]:+.3f}")

# --------------------------------------------------------------------------
print()
print("=" * 100)
print("2. THRESHOLD SWEEP -- chosen on CALIBRATION only, held-out reported blind")
print("=" * 100)
print(f"{'thr':>6}" + "".join(f"{h:>26}" for h in ("6 calibration charts",
                                                   "2 held-out charts", "all 8")))
print(f"{'':>6}" + "".join(f"{'n':>7}{'win%':>8}{'meanR':>11}" for _ in range(3)))
print("-" * 100)
RES = {}
for thr in THRESHOLDS:
    cal, tst = [], []
    for name, (c0, frame, cands) in POOL.items():
        t = [r for _, r in run_keep(frame, top(cands, thr))]
        (tst if name in HELD_OUT else cal).extend(t)
    RES[thr] = (cal, tst)
    both = cal + tst

    def f(t):
        return (f"{len(t):>7,}{(np.array(t) > 0).mean():>8.1%}"
                f"{np.mean(t):>11.2f}") if t else f"{0:>7}{'':>8}{'':>11}"
    print(f"{thr:>6.2f}{f(cal)}{f(tst)}{f(both)}", flush=True)
print("-" * 100)
best = max(THRESHOLDS, key=lambda t: np.mean(RES[t][0]) if RES[t][0] else -9)
print(f"best threshold on CALIBRATION: risk/ATR >= {best:.2f} "
      f"({np.mean(RES[best][0]):+.2f}R, n={len(RES[best][0])})")
print(f"  the same threshold, applied BLIND to the held-out two: "
      f"{np.mean(RES[best][1]):+.2f}R, n={len(RES[best][1])} "
      f"(was {np.mean(RES[0.0][1]):+.2f}R at no filter)")

# --------------------------------------------------------------------------
print()
print("=" * 100)
print(f"3. DOES THE STRUCTURE STILL CARRY IT? -- risk/ATR >= {best:.2f} vs shift-null")
print("=" * 100)
print(f"{'chart':<13}{'':<3}{'no filter':>11}{'filtered':>10}{'null mean':>11}"
      f"{'null sd':>9}{'pctile':>9}{'n':>7}{'win%':>8}")
print("-" * 100)
pf, pn = [], []
for name, (c0, frame, cands) in POOL.items():
    base = [r for _, r in run_keep(frame, top(cands))]
    picks = top(cands, best)
    a = np.array([r for _, r in run_keep(frame, picks)])
    if a.size == 0:
        print(f"{name:<13}{'':<3}{'no trades':>11}")
        continue
    nulls = np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        sh = [dict(x, arm=x["arm"] + int(rng.integers(RAND_LO, RAND_HI))
                   * int(rng.choice([-1, 1]))) for x in picks]
        t = np.array([r for _, r in run_keep(frame, sh)])
        nulls[s] = t.mean() if t.size else 0.0
    pf.append(a.mean())
    pn.append(nulls)
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}"
          f"{(np.mean(base) if base else float('nan')):>11.2f}{a.mean():>10.2f}"
          f"{nulls.mean():>11.2f}{nulls.std():>9.2f}"
          f"{(nulls < a.mean()).mean():>9.1%}{a.size:>7}{(a > 0).mean():>8.1%}",
          flush=True)
print("-" * 100)
nlp = np.mean(np.array(pn), axis=0)
print(f"{'POOLED':<13}{'':<3}{'':>11}{np.mean(pf):>10.2f}{nlp.mean():>11.2f}"
      f"{nlp.std():>9.2f}{(nlp < np.mean(pf)).mean():>9.1%}")
print("=" * 100)
print("Zero costs, zero slippage, one regime, non-independent trades.")
