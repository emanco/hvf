"""Does a nearer target pay better than AMP1? (spec 9.1, the AMP2 ladder)

Hunt's "AMP1" naming implies a ladder and every chart carries a second dashed
ray, so the 1.0-AMP target may not be the one he trades. A nearer target trades
win rate against payoff; since §8.10's problem is that avgR is too small to
establish with the trades available, a higher-WR/lower-payoff point on the curve
could plausibly land somewhere decidable.

Sweeping seven multiples and reporting the best is seven comparisons, so the
whole curve is printed. A smooth curve peaking in the interior is a real
trade-off; a lone spike is noise.

⚠️ READ THIS BEFORE USING THE NUMBERS. This runs on the funnel population the
CURRENT detector emits, and spec §8.12 shows that detector systematically misses
multi-degree funnels -- including Hunt's own USDJPY 1W, which it scores 0.3287
against a 0.0820 noise floor when the structure is actually present at 0.0034.
So this measures the target rule over a population that is biased toward
funnels whose pivots happen to be consecutive. It cannot settle the ladder; it
can only say whether the ladder is worth retesting once detection is fixed.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    _atr, detect_hvf, load_ohlc, resample_ohlc, prior_trend_extreme_of_m,
    select_projection,
)

DATA = ROOT / "backtests" / "data" / "hvf_v2"
BAR = "=" * 96
GATE = prior_trend_extreme_of_m(50)
SPLIT = pd.Timestamp("2020-01-01", tz="UTC")
COST = 0.05
MULTS = [0.25, 0.375, 0.5, 0.75, 1.0, 1.5, 2.0]     # 1.0 == the current rule


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


def target_at(f, m, bar_hours):
    """The ladder rung at m x AMP1, in whichever projection the period implies."""
    if select_projection(bar_hours) == "log":
        return f.mid * (f.b / f.a) ** (m * f.direction)
    return f.mid + f.direction * m * (f.b - f.a)


def simulate(frame, f, atr, target):
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)

    arm = f.pivots[-1].confirm
    if arm < 0 or arm + 1 >= len(o):
        return None
    long = f.direction > 0
    entry, stop = f.entry, f.stop
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    # A target inside the entry is not a trade, it is an instant fill.
    if (long and target <= entry) or (not long and target >= entry):
        return dict(outcome="DEGENERATE", R=None, arm=arm)
    if (long and c[arm] >= entry) or (not long and c[arm] <= entry):
        return dict(outcome="UNPLACEABLE", R=None, arm=arm)

    budget = max(1, f.pivots[-1].index - f.pivots[1].index)
    fill_i = None
    for i in range(arm + 1, min(len(o), arm + 1 + budget)):
        if (long and l[i] <= stop) or (not long and h[i] >= stop):
            return dict(outcome="EXPIRED_BROKE", R=None, arm=arm)
        if (long and h[i] >= entry) or (not long and l[i] <= entry):
            fill_i = i
            break
    if fill_i is None:
        return dict(outcome="EXPIRED_UNFILLED", R=None, arm=arm)

    fill = max(entry, o[fill_i]) if long else min(entry, o[fill_i])
    cost = COST * atr[fill_i]
    if not np.isfinite(cost):
        cost = 0.0
    for i in range(fill_i, len(o)):
        hit_stop = (l[i] <= stop) if long else (h[i] >= stop)
        hit_tgt = (h[i] >= target) if long else (l[i] <= target)
        if hit_stop:
            raw = (stop - fill) if long else (fill - stop)
            return dict(outcome="STOP", R=(raw - cost) / risk, arm=arm)
        if hit_tgt:
            raw = (target - fill) if long else (fill - target)
            return dict(outcome="TARGET", R=(raw - cost) / risk, arm=arm)
    return dict(outcome="OPEN", R=None, arm=arm)


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
        for m in MULTS:
            r = simulate(frame, f, atr, target_at(f, m, hours))
            if r is None:
                continue
            r.update(sym=label, m=m, ts=frame["dt"].iloc[r["arm"]])
            rows.append(r)
    print(f"  {label:<12} {len(funnels):>5} funnels", flush=True)

df = pd.DataFrame(rows)
df["leg"] = np.where(df["ts"] < SPLIT, "train", "TEST")

print(f"\n{BAR}\nTARGET LADDER -- R measured against the SAME stop, cost "
      f"{COST} x ATR14\n{BAR}")
print(f"{'m x AMP1':<10}{'n':>7}{'WR%':>8}{'avgR':>9}{'sdR':>7}{'95% CI':>21}"
      f"{'train':>9}{'TEST':>8}{'N needed':>11}")
print("-" * 96)
for m in MULTS:
    cl = df[(df["m"] == m) & df["R"].notna()]
    if not len(cl):
        continue
    n, avg, sd = len(cl), cl["R"].mean(), cl["R"].std()
    se = sd / np.sqrt(n)
    need = 7.85 * sd ** 2 / avg ** 2 if avg else np.inf
    tag = "  <- current" if m == 1.0 else ""
    print(f"{m:<10.3f}{n:>7}{(cl['R'] > 0).mean() * 100:>8.1f}{avg:>9.3f}{sd:>7.2f}"
          f"   [{avg - 1.96 * se:+.3f}, {avg + 1.96 * se:+.3f}]"
          f"{cl[cl['leg'] == 'train']['R'].mean():>9.3f}"
          f"{cl[cl['leg'] == 'TEST']['R'].mean():>8.3f}{need:>11,.0f}{tag}")
print(BAR)
