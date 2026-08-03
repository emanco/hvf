"""Step 4: do the funnels the detector emits actually make money?

Rules are pre-committed in spec 8.9 and are not to be revised to suit a result.
The two that matter most:

  * ARM ON `confirm`, NEVER ON `index`. A percentage ZigZag cannot assert RL3
    when RL3 prints -- only once price has reversed a box away from it. Arming
    at `index` buys the dip with tomorrow's newspaper, and is the most likely
    way this strategy fabricates an edge.
  * A stop order already through the market is REJECTED, not filled. Live it
    returns retcode 10015. Counted separately, because the rejected ones are
    disproportionately the fast moves that would have been the winners.

Declared deviations from the section 8 contract (also in spec 8.9): `simulate()`
is not copied verbatim because it is M15/Asian-session specific and HVF holds
for weeks -- its fill semantics are reused instead; and FINANCING IS NOT
MODELLED because `swap_fn` needs MetaTrader5, which is Windows-only. The spec
calls financing the single most likely source of a fictitious edge on
high-timeframe HVF, so multi-week results here are provisional.
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
BAR = "=" * 100
GATE = prior_trend_extreme_of_m(50)          # decided on evidence, spec 8.7
SPLIT = pd.Timestamp("2020-01-01", tz="UTC")  # pre-committed, spec 8.9


def _grid(lo, hi, step):
    out, x = [], lo
    while x <= hi:
        out.append(round(x, 4))
        x *= step
    return out


BOXES = _grid(0.10, 5.0, 1.15)

# The sweep is mandatory: spec 8.8 showed no rule picks a box, so a live system
# must run all of them. Backtesting one hand-picked box would flatter the result.
UNIVERSE = [
    ("XAUUSD_H1", "GoldCFD 2h", 2, 0),
    ("USDJPY_H1", "USDJPY 4h", 4, 1),
    ("HYG_NYSE_H1", "HYG 4h", 4, 0),
    ("BTCUSD_H1", "BTCUSD 1h", 1, None),
    ("XAUEUR_H1", "XAUEUR 1h", 1, None),
    ("XTIUSD_H1", "WTI 18h", 18, 0),
]


# Spec 8 item 7: for long histories use cost_mode "atrfrac". The per-bar
# `spread` column cannot be used here for two measured reasons: ~50% of bars
# before 2020 carry spread=0, which makes any pre/post split a cost artefact
# rather than a regime finding; and the point size needed to convert points to
# price is not in the CSVs, with a naive inference putting BTCUSD's cost at 2.7x
# its median bar range. A fraction of ATR is uniform across history and needs no
# point size. Reported as a sensitivity band, not a single number.
COST_ATRFRAC = [0.0, 0.05, 0.10]


def simulate(frame, f, atr, atrfrac):
    """One funnel -> one outcome. Fill semantics from asb_fill_audit.py:193,196."""
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)

    arm = f.pivots[-1].confirm                      # spec 8.9: never .index
    if arm < 0 or arm + 1 >= len(o):
        return None
    long = f.direction > 0
    entry, stop, target = f.entry, f.stop, f.target
    risk = abs(entry - stop)
    if risk <= 0:
        return None

    # Placeability at the arm bar: a stop order through the market is rejected.
    px = frame["close"].to_numpy(float)[arm]
    if (long and px >= entry) or (not long and px <= entry):
        return dict(outcome="UNPLACEABLE", R=None, bars=0, arm=arm)

    # The funnel's own duration is the unfilled-expiry budget (pre-committed).
    budget = max(1, f.pivots[-1].index - f.pivots[1].index)

    fill_i = None
    for i in range(arm + 1, min(len(o), arm + 1 + budget)):
        # Pre-fill invalidation: the structure broke before it triggered.
        if (long and l[i] <= stop) or (not long and h[i] >= stop):
            return dict(outcome="EXPIRED_BROKE", R=None, bars=i - arm, arm=arm)
        if (long and h[i] >= entry) or (not long and l[i] <= entry):
            fill_i = i
            break
    if fill_i is None:
        return dict(outcome="EXPIRED_UNFILLED", R=None, bars=budget, arm=arm)

    # Gap fills take the OPEN, not the level; risk stays derived from the level.
    fill = entry
    if long and o[fill_i] > entry:
        fill = o[fill_i]
    elif not long and o[fill_i] < entry:
        fill = o[fill_i]
    gapped = fill != entry

    cost = atrfrac * atr[fill_i]
    if not np.isfinite(cost):
        cost = 0.0

    for i in range(fill_i, len(o)):
        hit_stop = (l[i] <= stop) if long else (h[i] >= stop)
        hit_tgt = (h[i] >= target) if long else (l[i] <= target)
        if hit_stop and hit_tgt:
            hit_tgt = False                        # same bar -> stop wins
        if hit_stop:
            raw = (stop - fill) if long else (fill - stop)
            return dict(outcome="STOP", R=(raw - cost) / risk, bars=i - arm,
                        arm=arm, gapped=gapped, held=i - fill_i)
        if hit_tgt:
            raw = (target - fill) if long else (fill - target)
            return dict(outcome="TARGET", R=(raw - cost) / risk, bars=i - arm,
                        arm=arm, gapped=gapped, held=i - fill_i)
    return dict(outcome="OPEN", R=None, bars=len(o) - arm, arm=arm)


rows = []
for src, label, hours, off in UNIVERSE:
    path = DATA / f"{src}.csv"
    if not path.exists():
        continue
    base = load_ohlc(str(path))
    frame = base if off is None else resample_ohlc(base, hours, off)
    atr = _atr(frame, 14).to_numpy(float)

    seen = set()
    for box in BOXES:
        found, _ = detect_hvf(frame, bar_hours=hours, box_pct=box, prior_trend=GATE)
        for f in found:
            key = (f.pivots[1].index, f.pivots[-1].index, f.direction)
            if key in seen:            # same funnel re-found at a nearby box
                continue
            seen.add(key)
            for frac in COST_ATRFRAC:
                r = simulate(frame, f, atr, frac)
                if r is None:
                    continue
                r.update(sym=label, box=box, cost=frac,
                         dir="L" if f.direction > 0 else "S",
                         ts=frame["dt"].iloc[r["arm"]], rrr=f.rrr)
                rows.append(r)

df = pd.DataFrame(rows)
df["leg"] = np.where(df["ts"] < SPLIT, "train", "TEST")
base_cost = df[df["cost"] == COST_ATRFRAC[0]]

print(BAR)
print("STEP 4 -- HVF performance, lookahead-free (armed on Pivot.confirm)")
print(f"{len(base_cost)} funnels across {df['sym'].nunique()} instruments, "
      f"{df['ts'].min():%Y-%m-%d}..{df['ts'].max():%Y-%m-%d}")
print(BAR)
print("\nOutcome mix (all funnels emitted, before any trade is possible):")
for k, v in base_cost["outcome"].value_counts().items():
    print(f"   {k:<18}{v:>6}{v / len(base_cost) * 100:>7.1f}%")

closed = df[df["R"].notna()].copy()
n0 = len(closed[closed["cost"] == COST_ATRFRAC[0]])
print(f"\nClosed trades: {n0}  (fill rate {n0 / len(base_cost) * 100:.1f}% "
      f"of emitted funnels)")

print(f"\n{BAR}\nPERFORMANCE by cost assumption (cost = fraction of ATR14)\n{BAR}")
print(f"{'cost':<8}{'leg':<8}{'n':>6}{'WR%':>8}{'avgR':>9}{'sdR':>8}{'totR':>9}"
      f"{'medHold':>9}{'gap%':>7}")
print("-" * 100)
for frac in COST_ATRFRAC:
    for leg in ("train", "TEST", "ALL"):
        d = closed[closed["cost"] == frac]
        if leg != "ALL":
            d = d[d["leg"] == leg]
        if not len(d):
            continue
        print(f"{frac:<8.2f}{leg:<8}{len(d):>6}{(d['R'] > 0).mean() * 100:>8.1f}"
              f"{d['R'].mean():>9.3f}{d['R'].std():>8.2f}{d['R'].sum():>9.1f}"
              f"{d['held'].median():>9.0f}{d['gapped'].mean() * 100:>7.1f}")
    print()

mid = closed[closed["cost"] == COST_ATRFRAC[1]]
print(f"{'per instrument @ cost ' + str(COST_ATRFRAC[1]):<24}{'n':>6}{'WR%':>8}"
      f"{'avgR':>9}{'totR':>9}{'TEST avgR':>12}")
print("-" * 100)
for sym, d in mid.groupby("sym"):
    t = d[d["leg"] == "TEST"]
    print(f"{sym:<24}{len(d):>6}{(d['R'] > 0).mean() * 100:>8.1f}"
          f"{d['R'].mean():>9.3f}{d['R'].sum():>9.1f}"
          f"{(t['R'].mean() if len(t) else float('nan')):>12.3f}")

sd, avg = mid["R"].std(), mid["R"].mean()
need = 7.85 * sd ** 2 / avg ** 2 if avg else float("inf")
print(f"\n{BAR}\nPOWER (spec 7.1) @ cost {COST_ATRFRAC[1]}: sd(R)={sd:.2f}, "
      f"avgR={avg:+.3f} -> N needed = {need:,.0f}; have {len(mid)}")
print(f"financing NOT modelled (MT5 unavailable) -- median hold "
      f"{mid['held'].median():.0f} bars")
print(BAR)
