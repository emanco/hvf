"""Direction from the MAIN trend: HVF is a continuation pattern (spec 2.2a).

Doctrine, from the trader: HVF almost always continues the prevailing trend and
rarely marks a reversal. A counter-trend funnel is not merely lower-probability
-- it fights the fundamentals as well as the tape, and legitimising one needs a
SECOND pattern (head-and-shoulders and the like) to price the risk. We have no
such pattern implemented, so counter-trend funnels are rejected outright rather
than part-credited. That is a [C] scope decision, recorded as one.

WHY 8.7's GATE CANNOT DO THIS. `extreme_of_m(50)` asks "is H1 the highest high
of the last 50 bars". That predicate is PERMISSIVE: it can be true of some high
and, at another index, of some low, so it admits longs and shorts over the same
window -- 818 and 16,327 respectively on gold in 2026 (spec 8.16). A direction
rule has to be EXCLUSIVE: a signed quantity whose sign picks one side and
therefore refuses the other by construction. All four candidates below are.

Evaluated at H1's bar using only bars up to it, so no lookahead. Recall is the
hard constraint -- a rule that misclassifies any of Hunt's eight is dead, no
matter what it does to emissions.
"""
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
    BOX_SIZES, LIVE_ANCHOR, LIVE_BARS, PASS_FIB, amp_gate, load_frame,
    mef_candidates, score,
)

BAR = "=" * 100
LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
ATR_LO, ATR_HI = 1.882, 10.196


def sig_sma(frame, n):
    """Close above / below its own n-bar mean."""
    c = frame["close"]
    return np.sign(c - c.rolling(n, min_periods=n).mean()).to_numpy(float)


def sig_slope(frame, n):
    """Sign of the OLS slope of close over the trailing n bars."""
    c = frame["close"].to_numpy(float)
    x = np.arange(n) - (n - 1) / 2.0
    den = (x ** 2).sum()
    out = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        out[i] = np.sign((x * (c[i - n + 1:i + 1] - c[i - n + 1:i + 1].mean())).sum() / den)
    return out


def sig_swing(frame, box, k):
    """Direction of the last CONFIRMED leg of a ZigZag k x coarser than the
    funnel's own box -- the trend one degree up, in the rule's own idiom."""
    piv = zigzag_pct(frame, box * k)
    out = np.full(len(frame), np.nan)
    for p in piv:
        if p.confirm is not None and p.confirm >= 0:
            out[p.confirm:] = 1.0 if p.kind == "H" else -1.0
    return out


def sig_hhhl(frame, n):
    """Higher highs and higher lows: (last n/2 extremes) vs (the n/2 before)."""
    h, l = frame["high"], frame["low"]
    m = n // 2
    up = (h.rolling(m).max() > h.rolling(m).max().shift(m)) & \
         (l.rolling(m).min() > l.rolling(m).min().shift(m))
    dn = (h.rolling(m).max() < h.rolling(m).max().shift(m)) & \
         (l.rolling(m).min() < l.rolling(m).min().shift(m))
    return np.where(up, 1.0, np.where(dn, -1.0, 0.0))


def rules(frame, box):
    return {
        "close vs SMA100": sig_sma(frame, 100),
        "close vs SMA200": sig_sma(frame, 200),
        "OLS slope 100": sig_slope(frame, 100),
        "swing, box x4": sig_swing(frame, box, 4),
        "swing, box x8": sig_swing(frame, box, 8),
        "HH/HL 100": sig_hhhl(frame, 100),
    }


def best_match(c0):
    """Hunt's funnel as the acceptance run finds it, with its frame and box."""
    _, _, _, ra, rb = reference_prices(c0)
    keep = amp_gate(c0, ra, rb)
    lf = LIVE_ANCHOR - pd.Timedelta(hours=LIVE_BARS * c0["hours"])
    if c0["src"].endswith("_W1"):
        c, offs = dict(c0, src=c0["src"].replace("_W1", "_D1")), list(range(0, 168, 24))
    elif c0["hours"] == 1:
        c, offs = c0, [None]
    else:
        c, offs = c0, list(range(int(c0["hours"])))
    best = None
    for off in offs:
        frame = load_frame(c, off)
        for box in BOX_SIZES:
            piv = zigzag_pct(frame, box)
            if len(piv) < 6:
                continue
            for idx in mef_candidates(piv, c0["dir"], keep_ab=keep):
                w = [piv[j] for j in idx]
                if w[-1].ts < lf:
                    continue
                s = score(w, c0, ra, rb)
                if s and (best is None or s[0] < best[0]):
                    best = (s[0], frame, piv, idx, box, off)
    return best


NAMES = list(rules(load_frame(CHARTS[0], 0), 1.0).keys())

print(BAR)
print("A -- RECALL: does the rule call Hunt's own eight the way Hunt called them?")
print(BAR)
print(f"{'chart':<13}{'Hunt':>7}" + "".join(f"{n:>17}" for n in NAMES))
print("-" * 100)
hits = {n: 0 for n in NAMES}
total = 0
for c0 in CHARTS:
    b = best_match(c0)
    if b is None:
        continue
    _, frame, piv, idx, box, off = b
    i = piv[idx[0]].index
    r = rules(frame, box)
    total += 1
    cells = ""
    for n in NAMES:
        v = r[n][i] if i < len(r[n]) else np.nan
        ok = np.isfinite(v) and v == c0["dir"]
        hits[n] += ok
        cells += f"{('OK' if ok else ('0' if v == 0 else 'WRONG')) + f' ({v:+.0f})' if np.isfinite(v) else 'n/a':>17}"
    print(f"{c0['name']:<13}{('long' if c0['dir'] > 0 else 'short'):>7}{cells}",
          flush=True)
print("-" * 100)
print(f"{'recall':<13}{'':>7}" + "".join(f"{f'{hits[n]}/{total}':>17}" for n in NAMES))

print(f"\n{BAR}")
print("B -- SELECTIVITY: 2026, reproducing box, ATR band, one direction per bar")
print(BAR)
CASES = [("GoldCFD 2h", 0.6153, 0), ("USDJPY 4h", 0.4652, 1),
         ("HYG 4h", 0.7076, 0), ("BTCUSD 1h", 1.8822, None)]
print(f"{'chart':<13}{'rule':<18}{'right-way':>11}{'wrong-way':>11}{'/mo':>8}"
      f"{'Hunt kept?':>12}")
print("-" * 100)
for name, box, off in CASES:
    c0 = next(x for x in CHARTS if x["name"] == name)
    frame = load_frame(c0, off)
    _, _, _, ra, rb = reference_prices(c0)
    atr = _atr(frame, 14).to_numpy(float)
    piv = zigzag_pct(frame, box)
    r = rules(frame, box)
    span = (frame["dt"].iloc[-1] - max(frame["dt"].iloc[0], LIVE_FROM)).days / 30.44
    acc = {n: {1: set(), -1: set()} for n in ["(none)"] + NAMES}
    bestfib = {n: None for n in ["(none)"] + NAMES}
    for d in (1, -1):
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            if w[-1].ts < LIVE_FROM:
                continue
            i = w[0].index
            a = atr[i]
            if not (a and ATR_LO <= abs(w[0].price - w[1].price) / a <= ATR_HI):
                continue
            key = tuple(p.ts.value for p in w)
            s = score(w, c0, ra, rb) if d == c0["dir"] else None
            for n in ["(none)"] + NAMES:
                if n != "(none)" and not (i < len(r[n]) and r[n][i] == d):
                    continue
                acc[n][d].add(key)
                if s and (bestfib[n] is None or s[0] < bestfib[n]):
                    bestfib[n] = s[0]
    for n in ["(none)"] + NAMES:
        right = len(acc[n][c0["dir"]])
        wrong = len(acc[n][-c0["dir"]])
        kept = "yes" if bestfib[n] is not None and bestfib[n] <= PASS_FIB else "NO"
        print(f"{name if n == '(none)' else '':<13}{n:<18}{right:>11,}{wrong:>11,}"
              f"{(right + wrong) / span:>8.1f}{kept:>12}", flush=True)
print(BAR)
print("v8.7 detector rates: gold 1.1, USDJPY 4h 0.4, HYG 4h 0.2 per month")
