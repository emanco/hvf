"""Can a better entry lift avgR above the level at which our data can settle it?

Step 4 (spec 8.10) measured avgR = 0.059 at a 5% ATR cost, needing N ~ 9,300
closed trades against the 1,960 available. Since N scales as 1/avgR^2 and the
trade supply is ~75/year across six instruments, that sample can never be
reached -- not by waiting (a century) and not by adding correlated symbols over
the same 26 years. The sample cannot move, so the edge has to.

Threshold to clear, PRE-COMMITTED before this ran: avgR >= 0.13 at 5% ATR cost,
with the TEST leg not collapsing. At 0.13 the 1,960 trades already on disk are
sufficient; below it, HVF is retired.

Two thirds of signals die at the entry: 29% UNPLACEABLE (price already through
the rail when the funnel became knowable) and 32% EXPIRED_BROKE (stop rail taken
out before entry). Four variants attack exactly that, all seeing identical
funnels:

  A  rail-stop          buy stop at RH3, invalidate if RL3 breaks first (step 4)
  B  rail-stop, re-arm  same, but a pre-fill break does NOT invalidate
  C  market-on-confirm  enter at the open after RL3 confirms; no UNPLACEABLE
  D  limit-at-mid       buy limit at the funnel midpoint; better price, smaller risk

Testing four variants and reporting the best is upward-biased. Train and TEST
legs are reported separately and the multiplicity is stated in the verdict.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    _atr, detect_hvf, load_ohlc, resample_ohlc, prior_trend_extreme_of_m,
)

DATA = ROOT / "backtests" / "data" / "hvf_v2"
BAR = "=" * 104
GATE = prior_trend_extreme_of_m(50)
SPLIT = pd.Timestamp("2020-01-01", tz="UTC")
COST = 0.05                       # ATR fraction; the decision cost from spec 8.10
THRESHOLD = 0.13                  # pre-committed


def _grid(lo, hi, step):
    out, x = [], lo
    while x <= hi:
        out.append(round(x, 4))
        x *= step
    return out


BOXES = _grid(0.10, 5.0, 1.15)
UNIVERSE = [
    ("XAUUSD_H1", "GoldCFD 2h", 2, 0), ("USDJPY_H1", "USDJPY 4h", 4, 1),
    ("HYG_NYSE_H1", "HYG 4h", 4, 0), ("BTCUSD_H1", "BTCUSD 1h", 1, None),
    ("XAUEUR_H1", "XAUEUR 1h", 1, None), ("XTIUSD_H1", "WTI 18h", 18, 0),
]


def resolve(o, h, l, fill_i, fill, stop, target, long, cost, arm):
    """Walk forward from a fill to the first rail touched. Stop wins ties."""
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    for i in range(fill_i, len(o)):
        hit_stop = (l[i] <= stop) if long else (h[i] >= stop)
        hit_tgt = (h[i] >= target) if long else (l[i] <= target)
        if hit_stop:
            raw = (stop - fill) if long else (fill - stop)
            return dict(outcome="STOP", R=(raw - cost) / risk,
                        arm=arm, held=i - fill_i)
        if hit_tgt:
            raw = (target - fill) if long else (fill - target)
            return dict(outcome="TARGET", R=(raw - cost) / risk,
                        arm=arm, held=i - fill_i)
    return dict(outcome="OPEN", R=None, arm=arm, held=len(o) - fill_i)


def run_variant(frame, f, atr, variant):
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)

    arm = f.pivots[-1].confirm
    if arm < 0 or arm + 1 >= len(o):
        return None
    long = f.direction > 0
    rail, stop, target, mid = f.entry, f.stop, f.target, f.mid
    cost = COST * atr[arm] if np.isfinite(atr[arm]) else 0.0
    budget = max(1, f.pivots[-1].index - f.pivots[1].index)

    if variant == "C":                       # market on confirmation
        fill = o[arm + 1]
        if (long and fill <= stop) or (not long and fill >= stop):
            return dict(outcome="INVALID", R=None, arm=arm, held=0)
        return resolve(o, h, l, arm + 1, fill, stop, target, long, cost, arm)

    if variant == "D":                       # limit at the funnel midpoint
        level = mid
        if (long and c[arm] <= level) or (not long and c[arm] >= level):
            fill_i, fill = arm + 1, o[arm + 1]     # already through -> market
        else:
            fill_i = None
            for i in range(arm + 1, min(len(o), arm + 1 + budget)):
                if (long and l[i] <= stop) or (not long and h[i] >= stop):
                    return dict(outcome="EXPIRED_BROKE", R=None, arm=arm, held=0)
                if (long and l[i] <= level) or (not long and h[i] >= level):
                    fill_i = i
                    break
            if fill_i is None:
                return dict(outcome="EXPIRED_UNFILLED", R=None, arm=arm, held=0)
            fill = min(level, o[fill_i]) if long else max(level, o[fill_i])
        return resolve(o, h, l, fill_i, fill, stop, target, long, cost, arm)

    # A and B: buy/sell stop at the rail.
    if (long and c[arm] >= rail) or (not long and c[arm] <= rail):
        return dict(outcome="UNPLACEABLE", R=None, arm=arm, held=0)
    fill_i = None
    for i in range(arm + 1, min(len(o), arm + 1 + budget)):
        if variant == "A" and ((long and l[i] <= stop) or (not long and h[i] >= stop)):
            return dict(outcome="EXPIRED_BROKE", R=None, arm=arm, held=0)
        if (long and h[i] >= rail) or (not long and l[i] <= rail):
            fill_i = i
            break
    if fill_i is None:
        return dict(outcome="EXPIRED_UNFILLED", R=None, arm=arm, held=0)
    fill = max(rail, o[fill_i]) if long else min(rail, o[fill_i])
    return resolve(o, h, l, fill_i, fill, stop, target, long, cost, arm)


rows = []
for src, label, hours, off in UNIVERSE:
    path = DATA / f"{src}.csv"
    if not path.exists():
        continue
    base = load_ohlc(str(path))
    frame = base if off is None else resample_ohlc(base, hours, off)
    atr = _atr(frame, 14).to_numpy(float)

    seen, funnels = set(), []
    for box in BOXES:
        found, _ = detect_hvf(frame, bar_hours=hours, box_pct=box, prior_trend=GATE)
        for f in found:
            key = (f.pivots[1].index, f.pivots[-1].index, f.direction)
            if key not in seen:
                seen.add(key)
                funnels.append(f)

    for f in funnels:
        for v in ("A", "B", "C", "D"):
            r = run_variant(frame, f, atr, v)
            if r is None:
                continue
            r.update(sym=label, variant=v, ts=frame["dt"].iloc[r["arm"]])
            rows.append(r)
    print(f"  {label:<12} {len(funnels):>5} funnels", flush=True)

df = pd.DataFrame(rows)
df["leg"] = np.where(df["ts"] < SPLIT, "train", "TEST")

NAMES = {"A": "rail-stop (step 4)", "B": "rail-stop, re-arm",
         "C": "market-on-confirm", "D": "limit-at-mid"}

print(f"\n{BAR}")
print(f"ENTRY EXPERIMENT -- cost {COST} x ATR14, pre-committed threshold "
      f"avgR >= {THRESHOLD}")
print(BAR)
print(f"{'variant':<22}{'fills':>7}{'fill%':>7}{'WR%':>7}{'avgR':>8}{'sdR':>7}"
      f"{'95% CI':>20}{'trainR':>9}{'TESTR':>8}{'verdict':>10}")
print("-" * 104)

for v in ("A", "B", "C", "D"):
    d = df[df["variant"] == v]
    cl = d[d["R"].notna()]
    if not len(cl):
        continue
    n, avg, sd = len(cl), cl["R"].mean(), cl["R"].std()
    se = sd / np.sqrt(n)
    lo, hi = avg - 1.96 * se, avg + 1.96 * se
    tr = cl[cl["leg"] == "train"]["R"].mean()
    te = cl[cl["leg"] == "TEST"]["R"].mean()
    ok = "PASS" if (avg >= THRESHOLD and te > 0) else "fail"
    print(f"{NAMES[v]:<22}{n:>7}{n / len(d) * 100:>7.1f}{(cl['R'] > 0).mean() * 100:>7.1f}"
          f"{avg:>8.3f}{sd:>7.2f}   [{lo:+.3f}, {hi:+.3f}]{tr:>9.3f}{te:>8.3f}{ok:>10}")

print(f"\n{BAR}\noutcome mix by variant\n{BAR}")
mix = df.pivot_table(index="outcome", columns="variant", values="R",
                     aggfunc="size", fill_value=0)
print(mix.to_string())

print(f"\n{BAR}")
best = max("ABCD", key=lambda v: df[(df.variant == v) & df.R.notna()]["R"].mean())
cl = df[(df.variant == best) & df.R.notna()]
need = 7.85 * cl["R"].std() ** 2 / cl["R"].mean() ** 2 if cl["R"].mean() else np.inf
print(f"best variant: {NAMES[best]}  avgR {cl['R'].mean():+.3f}  "
      f"N needed {need:,.0f}  have {len(cl)}")
print(f"Best-of-4 is upward biased; the threshold was fixed at {THRESHOLD} "
      f"before this ran.")
print(BAR)
