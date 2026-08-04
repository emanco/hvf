"""Is the short side of the MEF rule a true mirror of the long side? (spec 8.18)

Spec 8.16 found geometry emitting ~17:1 shorts on gold and ~21:1 on BTC, both
markets that have risen for years. That is either real structure or a defect in
the bearish branch of `mef_candidates`, and until it is settled the wrong-way
percentages in 8.16 mean nothing.

Inspection does not settle it: `hi`/`lo` flip with direction and the walls are
kind-relative, so the two branches LOOK symmetric. So test it instead. Reflect
the price series and count again. If the code is symmetric, reflection must swap
the long and short counts EXACTLY -- a long funnel in p is a short funnel in -p.

Three levels, to localise any break:

  A  mef_candidates alone. Mirror the pivot list directly (price -> -price,
     H <-> L) and re-enumerate. No ZigZag involved.
  B  geometric reflection p -> C^2/p of the OHLC, then re-run zigzag_pct. This
     preserves PERCENTAGE moves exactly, so a %-box ZigZag mirrors exactly too.
     A break here but not at A is a ZigZag defect.
  C  arithmetic reflection p -> K - p. This does NOT preserve percentage moves,
     so a break here alone is not a bug -- it is the %-box behaving as designed,
     and it measures how much asymmetry that choice alone injects.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
import pandas as pd
from hvf_trader.detector.hvf_v2 import zigzag_pct
from hvf_v2_charts import CHARTS
from hvf_v2_mef import load_frame, mef_candidates

LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
CASES = [("GoldCFD 2h", 0.6153, 0), ("BTCUSD 1h", 1.8822, None),
         ("USDJPY 4h", 0.4652, 1), ("HYG 4h", 0.7076, 0)]
OHLC = ["open", "high", "low", "close"]


class P:
    """Enough of a Pivot for build_index/mef_candidates: price, kind, ts."""
    __slots__ = ("price", "kind", "ts", "index")

    def __init__(self, price, kind, ts, index):
        self.price, self.kind, self.ts, self.index = price, kind, ts, index


def mirror_pivots(piv):
    return [P(-p.price, "L" if p.kind == "H" else "H", p.ts, p.index)
            for p in piv]


def reflect(frame, mode):
    """Reflect the bars. Highs become lows, so the two columns swap as well."""
    f = frame.copy()
    if mode == "geom":                      # p -> C^2/p, % moves preserved
        c = float(frame["close"].iloc[0])
        m = lambda col: c * c / frame[col]
    else:                                   # p -> K - p, % moves NOT preserved
        k = float(frame["high"].max()) * 2.0
        m = lambda col: k - frame[col]
    f["open"], f["close"] = m("open"), m("close")
    f["high"], f["low"] = m("low"), m("high")
    return f


def counts(piv, live_only=True):
    out = {}
    for d in (1, -1):
        seen = set()
        for idx in mef_candidates(piv, d):
            if live_only and piv[idx[-1]].ts < LIVE_FROM:
                continue
            seen.add(tuple(piv[j].ts.value for j in idx))
        out[d] = len(seen)
    return out


print("=" * 96)
print("MIRROR TEST -- reflection must swap long and short counts exactly")
print("=" * 96)
print(f"{'chart':<13}{'level':<34}{'longs':>10}{'shorts':>10}{'S:L':>8}"
      f"{'symmetric?':>13}")
print("-" * 96)
for name, box, off in CASES:
    c0 = next(x for x in CHARTS if x["name"] == name)
    frame = load_frame(c0, off)
    piv = zigzag_pct(frame, box)
    base = counts(piv)
    r = base[-1] / base[1] if base[1] else float("inf")
    print(f"{name:<13}{'as traded':<34}{base[1]:>10,}{base[-1]:>10,}{r:>8.1f}"
          f"{'--':>13}", flush=True)

    a = counts(mirror_pivots(piv))
    ok = (a[1] == base[-1] and a[-1] == base[1])
    print(f"{'':<13}{'A  mirrored pivots (mef only)':<34}{a[1]:>10,}{a[-1]:>10,}"
          f"{a[-1] / a[1] if a[1] else 0:>8.1f}{'YES' if ok else 'NO':>13}",
          flush=True)

    for mode, label in (("geom", "B  p -> C^2/p, %-moves kept"),
                        ("arith", "C  p -> K - p, %-moves changed")):
        pm = zigzag_pct(reflect(frame, mode), box)
        m = counts(pm)
        ok = (m[1] == base[-1] and m[-1] == base[1])
        print(f"{'':<13}{label:<34}{m[1]:>10,}{m[-1]:>10,}"
              f"{m[-1] / m[1] if m[1] else 0:>8.1f}"
              f"{'YES' if ok else 'NO':>13}", flush=True)
    print("-" * 96, flush=True)
