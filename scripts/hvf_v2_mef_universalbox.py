"""One box size for every chart, taken from Hunt's own tool (spec 8.29).

The box is the last hindsight in the system. 8.14 chose it per chart as "the
coarsest box that still reproduces Hunt's funnel", which needs to know the
answer first -- eight numbers fitted to eight charts, 0.4652% to 3.2919%.
Everything else is now either doctrine or has been beaten against a null; this
has not, and it sits upstream of all of it.

The USDJPY 1W chart displays the setting directly: `Box Size 0.5 %`, `Source
H/L`. That is a single universal constant from the source, exactly the kind of
input AMP1 turned out to be. My value on that same chart is 3.2919% -- 6.6x
coarser -- and that chart yields two trades.

Detection at a universal 0.5% already matches 7 of 8 (all but WTI, which fails
seven prior sections and is excluded). This asks the harder question: does the
BACKTEST survive it? Emission rate falls roughly as box^-3, so a finer box
enumerates far more candidates and the top-3/month shortlist selects from a
much larger pool. More candidates is not automatically better.
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

CACHE = ROOT / "scripts" / ".universalbox_cache.pkl"
N = 3


def enumerate_all(c0, box):
    """8.22's enumeration, with the box passed in rather than looked up."""
    c, offs = offsets_for(c0)
    frame = load_frame(c, offs[0] if offs[0] is not None else None)
    piv = zigzag_pct(frame, box)
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
                            e_off=w[4].price - close[arm],
                            s_off=w[5].price - close[arm],
                            wait=w[5].index - w[0].index,
                            month=w[5].ts.tz_localize(None).to_period("M")))
    return out


def top(cands, n=N):
    by = defaultdict(list)
    for s in cands:
        if s["gated"]:
            by[s["month"]].append(s)
    out = []
    for m, g in by.items():
        out += sorted(g, key=lambda x: x["z"])[:n]
    return out


def simulate(frame, picks, shift=0):
    """8.22 baseline: AMP1 measured move, hard stop at the 6th pivot."""
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    n, free, out = len(frame), -1, []
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
        tgt = e + d * s["amp"]
        for i in range(fill, n):
            if (d > 0 and lo[i] <= st) or (d < 0 and hi[i] >= st):
                out.append(d * (st - e) / risk)
                free = i
                break
            if (d > 0 and hi[i] >= tgt) or (d < 0 and lo[i] <= tgt):
                out.append(d * (tgt - e) / risk)
                free = i
                break
    return out


store = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
VARIANTS = [("hindsight per-chart", None), ("universal 0.50%", 0.50),
            ("universal 0.4652%", 0.4652), ("universal 1.00%", 1.00)]

FRAMES = {}
for c0 in CHARTS:
    c, offs = offsets_for(c0)
    FRAMES[c0["name"]] = load_frame(c, offs[0] if offs[0] is not None else None)

RES, dirty = {}, False
for lab, box in VARIANTS:
    for c0 in CHARTS:
        key = (c0["name"], lab)
        if key not in store:
            b = BOX[c0["name"]] if box is None else box
            store[key] = enumerate_all(c0, b)
            dirty = True
    RES[lab] = {c0["name"]: store[(c0["name"], lab)] for c0 in CHARTS}
    print(f"enumerated {lab}: "
          f"{sum(len(v) for v in RES[lab].values()):,} candidates", flush=True)
if dirty:
    CACHE.write_bytes(pickle.dumps(store))


def fmt(t):
    if not t:
        return f"{0:>6}{'':>7}{'':>9}"
    a = np.array(t)
    return f"{len(a):>6}{(a > 0).mean():>7.1%}{a.mean():>9.2f}"


print()
print("=" * 104)
print("1. DOES THE BACKTEST SURVIVE A UNIVERSAL BOX?")
print("=" * 104)
print(f"{'variant':<22}" + "".join(f"{h:>22}" for h in
      ("6 calibration", "2 held-out (blind)", "all 8")))
print(f"{'':<22}" + "".join(f"{'n':>6}{'win%':>7}{'meanR':>9}" for _ in range(3)))
print("-" * 104)
TAB = {}
for lab, _ in VARIANTS:
    cal, tst = [], []
    for name, cands in RES[lab].items():
        t = simulate(FRAMES[name], top(cands))
        (tst if name in HELD_OUT else cal).extend(t)
    TAB[lab] = (cal, tst)
    print(f"{lab:<22}{fmt(cal)}{fmt(tst)}{fmt(cal + tst)}", flush=True)
print("-" * 104)

print()
print("=" * 104)
print("2. PER CHART -- hindsight box vs universal 0.50%")
print("=" * 104)
print(f"{'chart':<13}{'':<3}{'box used':>10}{'hind n':>8}{'hind R':>9}"
      f"{'univ n':>8}{'univ R':>9}{'delta':>9}{'cands x':>9}")
print("-" * 104)
for c0 in CHARTS:
    name = c0["name"]
    ca = RES["hindsight per-chart"][name]
    cb = RES["universal 0.50%"][name]
    a, b = simulate(FRAMES[name], top(ca)), simulate(FRAMES[name], top(cb))
    if not a and not b:
        continue
    ma = np.mean(a) if a else float("nan")
    mb = np.mean(b) if b else float("nan")
    mult = len(cb) / len(ca) if ca else float("nan")
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{BOX[name]:>10.4f}"
          f"{len(a):>8}{ma:>9.2f}{len(b):>8}{mb:>9.2f}{mb - ma:>+9.2f}{mult:>8.1f}x")
print("-" * 104)
print("'cands x' is how many more raw candidates the finer box enumerates.")
