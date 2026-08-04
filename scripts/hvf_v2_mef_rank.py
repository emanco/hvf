"""Turn the scale band into a RANK, the last thing blocking 8.10 (spec 8.20).

8.15 applied `AMP1/ATR14` as a hard band [1.9, 10.2] taken from the six
calibration charts. It cut emissions 20-170x and it deleted USDJPY 4h, whose
ratio is 10.196 -- the top edge, set by one chart. That is the generic failure
of a band fitted on n=6: everything on an edge is lost, and the edge is an
artefact of the smallest sample in the study. 8.15 concluded the quantity is a
*scale prior* and belongs in a ranking score. This builds it.

The score is a diagonal Mahalanobis distance in log space over two features,

    u = log(AMP1 / ATR14 at the anchor)      8.15, the only usable shape metric
    v = log(AMP1 / prior trend)              8.19, usable only since the repair

fitted to the six calibration funnels and evaluated on all eight. Log space
because both are ratios, diagonal because n=6 cannot support a covariance.

Nothing is discarded by the score. What is reported instead is where Hunt's own
funnel sits in the ordering, and how many candidates per month outrank it --
which is the honest form of the "emission rate" question 8.7 asked, and the
number 8.10 actually needs.
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402
from hvf_v2_mef import (  # noqa: E402
    HELD_OUT, LIVE_ANCHOR, LIVE_BARS, PASS_FIB, amp_gate, load_frame,
    mef_candidates, score,
)

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
K = 1.0                                    # 8.19's degree
BAND = (1.882, 10.196)                     # 8.15's hard band, for comparison


def live_from(c0):
    """8.14 defect 3: liveness is counted in BARS, not calendar dates.

    Missing this costs USDJPY 1W its match outright -- its RL3 is 2025-09-12,
    25 weeks but only 25 bars before the anchor.
    """
    return LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c0["hours"])

# Coarsest box that still scores MATCH in 8.14, snapped to the BOX_SIZES grid.
# The matching plateau there is often 30x wide, so this is a choice of
# convenience inside a range the acceptance run validated, not a fitted knob.
BOX = {"GoldCFD 2h": 0.7076, "BTCUSD 1h": 1.8822, "XAU/XAG 8h": 3.2919,
       "USDJPY 4h": 0.4652, "USDJPY 1W": 3.2919, "WTI 18h": 1.0761,
       "XAUEUR 1h": 0.9358, "HYG 4h": 0.9358}


def grid(lo=0.05, hi=60.0, step=1.1):
    out, v = [], lo
    while v <= hi:
        out.append(v)
        v *= step
    return np.array(out)


GRID = grid()


def offsets_for(c0):
    if c0["src"].endswith("_W1"):
        return dict(c0, src=c0["src"].replace("_W1", "_D1")), list(range(0, 168, 24))
    if c0["hours"] == 1:
        return c0, [None]
    return c0, list(range(int(c0["hours"])))


def coarse_table(frame):
    """Grid of coarse ZigZags, keyed by `confirm` -- see 8.19 on the lookahead."""
    tab = []
    for box in GRID:
        piv = zigzag_pct(frame, float(box))
        tab.append((np.array([p.confirm for p in piv]),
                    np.array([p.price for p in piv])))
    return tab


def impulse(tab, bar, price, amp):
    """(signed move, origin price) from the last coarse pivot known at `bar`."""
    g = int(np.argmin(np.abs(np.log(GRID) - np.log(100.0 * K * amp / abs(price)))))
    cf, pp = tab[g]
    j = int(np.searchsorted(cf, bar, "right")) - 1
    if j < 0:
        return 0.0, np.nan
    return price - pp[j], pp[j]


def pick_offset(c0):
    """The resample offset that actually prints Hunt's funnel at this box."""
    c, offs = offsets_for(c0)
    _, _, _, ra, rb = reference_prices(c0)
    keep = amp_gate(c0, ra, rb)
    lf = live_from(c0)
    best = (float("inf"), offs[0])
    for off in offs:
        piv = zigzag_pct(load_frame(c, off), BOX[c0["name"]])
        if len(piv) < 6:
            continue
        for idx in mef_candidates(piv, c0["dir"], keep_ab=keep):
            w = [piv[j] for j in idx]
            if w[-1].ts < lf:
                continue
            s = score(w, c0, ra, rb)
            if s and s[0] < best[0]:
                best = (s[0], off)
    return best


def collect(c0):
    """Every live MEF candidate at this chart's box, with its two features."""
    c, _ = offsets_for(c0)
    fib_err, off = pick_offset(c0)
    frame = load_frame(c, off)
    piv = zigzag_pct(frame, BOX[c0["name"]])
    tab = coarse_table(frame)
    atr = _atr(frame, 14).to_numpy(float)
    months = (frame["dt"].iloc[-1] - max(frame["dt"].iloc[0], LIVE_FROM)).days / 30.44
    _, _, _, ra, rb = reference_prices(c0)
    lf = live_from(c0)

    rows, seen, hunt = [], set(), None
    for d in (1, -1):
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            if w[-1].ts < lf:
                continue
            key = (d,) + tuple(p.ts.value for p in w)
            if key in seen:
                continue
            seen.add(key)
            amp = abs(w[0].price - w[1].price)
            a = atr[w[0].index]
            mv, origin = impulse(tab, w[0].index, w[0].price, amp)
            trend = abs(w[0].price - origin) if np.isfinite(origin) else 0.0
            if not (amp > 0 and a > 0 and trend > 0):
                continue
            r = dict(d=d, gated=bool(np.sign(mv) == d),
                     u=float(np.log(amp / a)), v=float(np.log(amp / trend)))
            rows.append(r)
            if hunt is None and d == c0["dir"]:
                s = score(w, c0, ra, rb)
                if s and s[0] <= PASS_FIB:
                    hunt = r
    return rows, hunt, fib_err, months


CACHE = Path(__file__).resolve().parent / ".rank_cache.pkl"


def collect_cached(c0):
    """`collect` is deterministic and costs minutes; the pickle is disposable."""
    store = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
    if c0["name"] not in store:
        store[c0["name"]] = collect(c0)
        CACHE.write_bytes(pickle.dumps(store))
    return store[c0["name"]]


print("=" * 104)
print("0. POPULATIONS -- one box per chart, both directions, live window")
print("=" * 104)
print(f"{'chart':<13}{'set':<7}{'box':>8}{'fib err':>9}{'candidates':>12}"
      f"{'gated':>9}{'months':>8}{'Hunt?':>8}{'8.15 band keeps':>17}")
print("-" * 104)

DATA = {}
for c0 in CHARTS:
    rows, hunt, fib_err, months = collect_cached(c0)
    DATA[c0["name"]] = (c0, rows, hunt, months)
    # What 8.15's hard band would do to this chart, for the like-for-like the
    # whole section exists to make: a band DELETES, a rank only reorders.
    nb = sum(1 for r in rows if BAND[0] <= np.exp(r["u"]) <= BAND[1])
    hb = ("--" if hunt is None else
          ("Hunt" if BAND[0] <= np.exp(hunt["u"]) <= BAND[1] else "DROPS Hunt"))
    print(f"{c0['name']:<13}{'TEST' if c0['name'] in HELD_OUT else 'calib':<7}"
          f"{BOX[c0['name']]:>8.3f}{fib_err:>9.4f}{len(rows):>12,}"
          f"{sum(r['gated'] for r in rows):>9,}{months:>8.1f}"
          f"{('yes' if hunt else 'NO'):>8}{f'{nb:,} / {hb}':>17}", flush=True)
print("-" * 104)

# ---------------------------------------------------------------------------
# The prior, fitted on the six calibration funnels only.
# ---------------------------------------------------------------------------
cal = [DATA[n][2] for n in DATA
       if n not in HELD_OUT and DATA[n][2] is not None]
FIT = {}
for f in ("u", "v"):
    xs = np.array([h[f] for h in cal])
    FIT[f] = (float(xs.mean()), float(xs.std(ddof=1)))

print()
print("=" * 104)
print(f"1. THE PRIOR -- fitted on {len(cal)} calibration funnels, log space")
print("=" * 104)
print(f"{'feature':<26}{'mean':>10}{'sd':>10}{'= ratio':>12}{'1sd band':>22}")
print("-" * 104)
for f, lab in (("u", "log AMP1/ATR14"), ("v", "log AMP1/trend")):
    m, s = FIT[f]
    print(f"{lab:<26}{m:>10.3f}{s:>10.3f}{np.exp(m):>12.2f}"
          f"{f'{np.exp(m - s):.2f} - {np.exp(m + s):.2f}':>22}")
print("-" * 104)


def zscore(r, feats):
    return float(np.sqrt(sum(((r[f] - FIT[f][0]) / FIT[f][1]) ** 2 for f in feats)))


VARIANTS = [("ATR only", ("u",)), ("trend only", ("v",)), ("both", ("u", "v"))]

for gated_only in (False, True):
    print()
    print("=" * 104)
    print(f"2{'b' if gated_only else 'a'}. RANK OF HUNT'S FUNNEL"
          f"{' -- after the 8.19 direction gate' if gated_only else ' -- ungated'}")
    print("=" * 104)
    print(f"{'chart':<13}{'set':<7}{'N':>10}" +
          "".join(f"{lab:>22}" for lab, _ in VARIANTS))
    print(f"{'':<13}{'':<7}{'':>10}" +
          "".join(f"{'rank  pct  ahead/mo':>22}" for _ in VARIANTS))
    print("-" * 104)
    tot = {lab: [] for lab, _ in VARIANTS}
    for name, (c0, rows, hunt, months) in DATA.items():
        pool = [r for r in rows if r["gated"]] if gated_only else rows
        if hunt is None or (gated_only and not hunt["gated"]):
            why = "no match" if hunt is None else "gate drops it"
            print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
                  f"{len(pool):>10,}{why:>22}")
            continue
        cells = []
        for lab, feats in VARIANTS:
            hs = zscore(hunt, feats)
            ahead = sum(1 for r in pool if zscore(r, feats) < hs)
            rank, n = ahead + 1, max(len(pool), 1)
            tot[lab].append(rank)
            cells.append(f"{rank:>6,}{rank / n:>6.1%}{ahead / months:>10.1f}")
        print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
              f"{len(pool):>10,}" + "".join(f"{t:>22}" for t in cells), flush=True)
    print("-" * 104)
    # Percentile is reported but is NOT the headline: the direction gate removes
    # candidates that were already worse than Hunt's, so it can worsen the
    # percentile while improving the absolute rank. `ahead/mo` is the quantity
    # 8.7 and 8.10 actually care about -- how long a list a human has to read.
    print(f"{'median rank':<13}{'':<7}{'':>10}" +
          "".join(f"{np.median(tot[lab]) if tot[lab] else np.nan:>22.0f}"
                  for lab, _ in VARIANTS))

# ---------------------------------------------------------------------------
# 3. The composition. A rank does not automatically retire the band: on gold
# the band keeps 1,268 candidates while the rank leaves 2,106 ahead of Hunt,
# so as a shortlist the band is the stronger of the two THERE. The question is
# whether keeping both is better than either, and what it costs in recall.
# ---------------------------------------------------------------------------
print()
print("=" * 104)
print("3. BAND AND RANK COMPOSED -- 8.19 gate, then 8.15's band, then rank on `both`")
print("=" * 104)
print(f"{'chart':<13}{'set':<7}{'gated':>9}{'+band':>9}{'survives':>10}"
      f"{'rank':>8}{'pct':>7}{'ahead/mo':>11}{'vs 2b':>10}")
print("-" * 104)
for name, (c0, rows, hunt, months) in DATA.items():
    pool = [r for r in rows if r["gated"]]
    inb = [r for r in pool if BAND[0] <= np.exp(r["u"]) <= BAND[1]]
    if hunt is None or not hunt["gated"]:
        print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
              f"{len(pool):>9,}{len(inb):>9,}{'gate drops it':>10}")
        continue
    keeps = BAND[0] <= np.exp(hunt["u"]) <= BAND[1]
    if not keeps:
        print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
              f"{len(pool):>9,}{len(inb):>9,}{'BAND DROPS':>10}")
        continue
    hs = zscore(hunt, ("u", "v"))
    ahead = sum(1 for r in inb if zscore(r, ("u", "v")) < hs)
    prev = sum(1 for r in pool if zscore(r, ("u", "v")) < hs)
    print(f"{name:<13}{'TEST' if name in HELD_OUT else 'calib':<7}"
          f"{len(pool):>9,}{len(inb):>9,}{'yes':>10}{ahead + 1:>8,}"
          f"{(ahead + 1) / max(len(inb), 1):>7.1%}{ahead / months:>11.1f}"
          f"{f'{prev / ahead:.1f}x' if ahead else 'inf':>10}", flush=True)
print("-" * 104)

print("=" * 104)
print("v8.7 detector rates for comparison: gold 1.1, USDJPY 4h 0.4, HYG 4h 0.2 /mo")
