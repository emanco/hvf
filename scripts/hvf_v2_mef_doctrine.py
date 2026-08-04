"""Two details from Hunt's own description that 8.26 did not test (spec 8.28).

The user described HVF as: three waves compressing into a tiny funnel, then a
move back with the same force and length for "TP1, TP2, etc.", with the stop
"just outside the tiny funnel". Two things there are not what 8.26 tested.

  A. THE STOP SITS *AT* THE SIXTH PIVOT, not outside it. There is no buffer
     anywhere in the implementation. 8.25 rejected a minimum stop distance in
     ATR units, but that is a different object -- it filters setups whose stop
     is too tight, it does not move the stop. 8.27 gave a reason to look: 2-7
     trades per chart gapped clean through the stop. A buffer widens risk, so
     it cuts R on every winner to save some losers; the trade is not obviously
     good in either direction.

  B. 8.26 TESTED PARTIALS ONLY IN COMBINATION WITH A BREAKEVEN STOP, and
     concluded partials lose. That conflates two changes. The breakeven move is
     independently known to be harmful -- it is the mechanism 8.26 blamed for
     clipping the tail that carries the whole result -- so a partial with the
     stop LEFT ALONE has never actually been measured. That is what "TP1, TP2"
     describes.

Same discipline as 8.26: chosen on the six calibration charts, reported blind on
the two pre-committed held-out ones, sequencing re-run per rule.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr  # noqa: E402
from hvf_v2_mef import HELD_OUT  # noqa: E402
import hvf_v2_mef_exit as X  # noqa: E402


def simulate(frame, picks, rule):
    """8.26's simulate plus two options.

    buf      stop pushed this many multiples of the original risk beyond the
             sixth pivot (buf_atr does the same in ATR14 units). Risk grows,
             so the AMP1 target is worth proportionally less in R.
    ladder   [(fraction, multiple of AMP1), ...] taken in order. The stop stays
             where the funnel put it -- that is the whole point of the test.
    """
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    atr = _atr(frame, 14).to_numpy(float)
    n = len(frame)
    free, out = -1, []

    for s in sorted(picks, key=lambda x: x["arm"]):
        arm = s["arm"]
        if arm + 1 >= n or arm <= free:
            continue
        d = s["d"]
        e = close[arm] + s["e_off"]
        st = close[arm] + s["s_off"]
        risk0 = abs(e - st)
        if risk0 <= 0:
            continue

        if rule.get("buf"):
            st = st - d * rule["buf"] * risk0
        elif rule.get("buf_atr"):
            a0 = atr[arm]
            if not np.isfinite(a0):
                continue
            st = st - d * rule["buf_atr"] * a0
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

        full_R = s["amp"] / risk            # 1 x AMP1 expressed in R
        ladder = rule.get("ladder") or [(1.0, 1.0)]
        legs = list(ladder)
        banked, size, res = 0.0, 1.0, None

        for i in range(fill, n):
            adv = (st - lo[i]) if d > 0 else (hi[i] - st)
            fav_px = hi[i] if d > 0 else lo[i]
            fav_R = d * (fav_px - e) / risk

            if adv >= 0:                                  # stop first on a tie
                res = banked + size * d * (st - e) / risk
                free = i
                break
            while legs and fav_R >= legs[0][1] * full_R:
                frac, mult = legs.pop(0)
                take = min(frac, size)
                banked += take * mult * full_R
                size -= take
                if size <= 1e-9:
                    break
            if size <= 1e-9:
                res, free = banked, i
                break
        if res is not None:
            out.append(res)
    return out


def run(rules, title, note):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)
    print(f"{'rule':<30}" + "".join(f"{h:>23}" for h in
          ("6 calibration", "2 held-out (blind)", "all 8")))
    print(f"{'':<30}" + "".join(f"{'n':>6}{'win%':>6}{'meanR':>11}" for _ in range(3)))
    print("-" * 100)
    tab = {}
    for lab, rule in rules:
        cal, tst = [], []
        for name, (_c, frame, _cd) in X.POOL.items():
            t = simulate(frame, X.PICKS[name], rule)
            (tst if name in HELD_OUT else cal).extend(t)
        tab[lab] = (cal, tst)
        print(f"{lab:<30}{X.fmt(cal)}{X.fmt(tst)}{X.fmt(cal + tst)}", flush=True)
    print("-" * 100)
    base = rules[0][0]
    bc, bt = np.mean(tab[base][0]), np.mean(tab[base][1])
    best = max(tab, key=lambda k: np.mean(tab[k][0]) if tab[k][0] else -9)
    wc, wt = np.mean(tab[best][0]), np.mean(tab[best][1])
    print(f"baseline           : calib {bc:+.2f}R   held-out {bt:+.2f}R")
    print(f"best on CALIBRATION: '{best}'  calib {wc:+.2f}R ({wc - bc:+.2f})   "
          f"held-out {wt:+.2f}R ({wt - bt:+.2f})")
    print("  -> transfers" if wt > bt else "  -> DOES NOT TRANSFER: reject")
    print(note)
    return tab


BUF = [
    ("stop AT 6th pivot (baseline)", dict()),
    ("+5% of risk beyond", dict(buf=0.05)),
    ("+10% of risk beyond", dict(buf=0.10)),
    ("+20% of risk beyond", dict(buf=0.20)),
    ("+33% of risk beyond", dict(buf=0.33)),
    ("+50% of risk beyond", dict(buf=0.50)),
    ("+0.25 ATR14 beyond", dict(buf_atr=0.25)),
    ("+0.50 ATR14 beyond", dict(buf_atr=0.50)),
    ("+1.00 ATR14 beyond", dict(buf_atr=1.00)),
]

LAD = [
    ("all at 1x AMP1 (baseline)", dict()),
    ("half 1x, half 1.5x", dict(ladder=[(0.5, 1.0), (0.5, 1.5)])),
    ("half 1x, half 2x", dict(ladder=[(0.5, 1.0), (0.5, 2.0)])),
    ("half 1x, half 3x", dict(ladder=[(0.5, 1.0), (0.5, 3.0)])),
    ("thirds 1x / 2x / 3x", dict(ladder=[(1/3, 1.0), (1/3, 2.0), (1/3, 3.0)])),
    ("thirds 1x / 1.5x / 2x", dict(ladder=[(1/3, 1.0), (1/3, 1.5), (1/3, 2.0)])),
    ("quarter 1x, 3/4 at 2x", dict(ladder=[(0.25, 1.0), (0.75, 2.0)])),
    ("3/4 at 1x, quarter 2x", dict(ladder=[(0.75, 1.0), (0.25, 2.0)])),
]

run(BUF, "A. STOP BUFFER -- 'just outside the funnel' vs exactly at the 6th pivot",
    "A buffer trades R on every winner for survival on some losers. Risk is\n"
    "recomputed per trade, so these R figures are already net of that.")

run(LAD, "B. TP LADDER with the stop LEFT AT THE 6th PIVOT (no breakeven move)",
    "8.26's partials all moved the stop to breakeven and all lost. This\n"
    "isolates the ladder from the breakeven move that 8.26 blamed.")
