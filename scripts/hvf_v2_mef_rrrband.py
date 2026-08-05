"""8.32 -- does an RRR band beat the shift-null?

8.31 showed realised win% falls faster than the breakeven requirement as RRR
rises, crossing over near 4R. Hunt's own eight setups sit at median 2.04R,
inside the profitable band. This tests whether that band is a real selector or
just another in-sample artefact: filter candidates to an RRR window, take
top-3/month as usual, then compare against 200 random relocations of the same
trades (which preserve direction, risk and R:R exactly).
"""
import pickle, sys
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")
import hvf_v2_mef_waves as W
from hvf_v2_charts import CHARTS
from hvf_v2_mef_backtest import load_frame, offsets_for

CACHE = "/private/tmp/claude-501/-Users-manu-Dev-atspass/a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad/rrrband.pkl"
BANDS = [("none", 0.0, 1e9), ("<=4R", 0.0, 4.0)]
NSEED = 200

try:
    store = pickle.loads(open(CACHE, "rb").read())
except Exception:
    store = {}

PERIODS = [("BLIND (pre-2023)", True)]
frames, dirty = {}, False
for lab, blind in PERIODS:
    for c0 in CHARTS:
        nm = c0["name"]
        if nm not in W.WANT:
            continue
        c, offs = offsets_for(c0)
        full = load_frame(c, offs[0] if offs[0] is not None else None)
        if blind:
            m = (full["dt"] >= pd.Timestamp(W.START[nm], tz="UTC")) & (full["dt"] < W.CUT)
        else:
            m = full["dt"] >= W.CUT
        fr = full[m].reset_index(drop=True)
        if len(fr) < 500:
            continue
        frames[(nm, lab)] = fr
        if (nm, lab) not in store:
            cands = W.enumerate_window(c0, W.BOX, fr)
            store[(nm, lab)] = {
                b: W.top([c for c in cands
                          if lo <= (c["amp"] / c["risk"] - 0.5) < hi])
                for b, lo, hi in BANDS}
            dirty = True
            print(f"enumerated {nm} {lab}: {len(cands):,} -> picks "
                  + ", ".join(f"{b}:{len(store[(nm,lab)][b])}" for b, _, _ in BANDS),
                  flush=True)
            del cands
if dirty:
    open(CACHE, "wb").write(pickle.dumps(store))


def band(cands, lo, hi):
    return [c for c in cands if lo <= (c["amp"] / c["risk"] - 0.5) < hi]


for lab, blind in PERIODS:
    print("\n" + "=" * 96)
    print(f"{lab} -- RRR band as a selector, legacy exit")
    print("=" * 96)
    print(f"{'band':<9}{'chart':<13}{'n':>5}{'win%':>8}{'meanR':>8}{'null':>8}{'pctile':>9}")
    print("-" * 96)
    for bl, lo, hi in BANDS:
        agg = []
        for c0 in CHARTS:
            nm = c0["name"]
            if (nm, lab) not in frames:
                continue
            fr = frames[(nm, lab)]
            picks = store[(nm, lab)][bl]
            t = W.simulate(fr, picks, mode="legacy")
            if not t:
                continue
            a = np.array(t, float)
            nulls = np.empty(NSEED)
            for sd in range(NSEED):
                rng = np.random.default_rng(sd)
                sh = int(rng.integers(W.RAND_LO, W.RAND_HI) * rng.choice([-1, 1]))
                tt = W.simulate(fr, picks, shift=sh, mode="legacy")
                nulls[sd] = np.mean(tt) if tt else 0.0
            agg.append((nm, a, nulls))
            print(f"{bl:<9}{nm:<13}{len(a):>5}{(a>0).mean():>8.1%}{a.mean():>8.2f}"
                  f"{nulls.mean():>8.2f}{(nulls<a.mean()).mean()*100:>8.1f}%", flush=True)
        if agg:
            w = np.array([len(a) for _, a, _ in agg], float)
            pr = np.average([a.mean() for _, a, _ in agg], weights=w)
            pn = np.average(np.vstack([n for _, _, n in agg]), axis=0, weights=w)
            print(f"{bl:<9}{'POOLED':<13}{int(w.sum()):>5}{'':>8}{pr:>8.2f}"
                  f"{pn.mean():>8.2f}{(pn<pr).mean()*100:>8.1f}%")
            print("-" * 96)
