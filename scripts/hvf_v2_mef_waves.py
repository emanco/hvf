"""Out-of-sample in time (spec 8.30).

Everything from 8.22 to 8.29 lives in 2023-2026 -- one regime, about three and a
half years, and the period whose charts Hunt drew. 8.29 removed the last fitted
parameter, so the rule set is now fully specified with nothing left to tune:
MEF detection at a universal 0.5% box, the 8.19 direction gate, entry at the 5th
pivot, stop at the 6th, target at the AMP1 measured move.

That makes a clean test possible for the first time. Run it on years it has
never seen. The frame is TRUNCATED at 2023-01-01 before enumeration, so no trade
can resolve into the known period -- the alternative, letting a December 2022
setup run on into 2023, would quietly leak the very data being held back.

Real hourly coverage limits how far back this goes (8.30a): gold H1 is genuine
hourly only from 2016, BTC from 2017. Earlier rows in those files are daily bars
sitting in an H1 file, so the 2h chart cannot be built before 2016.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import _atr, zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef import load_frame, mef_candidates  # noqa: E402
from hvf_v2_mef_ablation import NSEED, RAND_HI, RAND_LO  # noqa: E402
from hvf_v2_mef_backtest import FIT, coarse_table  # noqa: E402
from hvf_v2_mef_rank import GRID, K, offsets_for  # noqa: E402

# simulate/top are copied rather than imported: importing hvf_v2_mef_universalbox
# pulls in its 1.2 GB enumeration cache and re-runs its whole report.
from collections import defaultdict  # noqa: E402


def top(cands, n=3):
    by = defaultdict(list)
    for s in cands:
        if s["gated"]:
            by[s["month"]].append(s)
    out = []
    for m, g in by.items():
        out += sorted(g, key=lambda x: x["z"])[:n]
    return out


def simulate(frame, picks, shift=0, mode="waves"):
    """Hunt's three-wave exit.

    The three waves H1-L1, H2-L2, H3-L3 are each projected from C, the centre
    of the smallest funnel, giving TP3/TP2/TP1. Entry sits at the top of the
    tip (C + wave3/2), so TP1 is always exactly +0.5R. Verified to the cent on
    the USD/KRW 2h panel: 1489.11 / 1517.14 / 1530.30.

    mode: "legacy" = old single target at entry+AMP1, hard stop  (8.22-8.30)
          "tp3"    = single target at C+AMP1, hard stop
          "be"     = single target at C+AMP1, stop -> breakeven once TP1 trades
          "waves"  = thirds at TP1/TP2/TP3, stop -> breakeven once TP1 trades
    When one bar spans both a target and the stop, the stop is taken first.
    """
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    n, free, out = len(frame), -1, []
    for s_ in sorted(picks, key=lambda x: x["arm"] + shift):
        arm = s_["arm"] + shift
        if arm < 0 or arm + 1 >= n or arm <= free:
            continue
        d = s_["d"]
        e, st = close[arm] + s_["e_off"], close[arm] + s_["s_off"]
        risk = abs(e - st)
        if risk <= 0:
            continue
        fill = None
        for i in range(arm + 1, min(arm + 1 + s_["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                fill = i
                break
        if fill is None:
            continue

        C = (e + st) / 2.0
        if mode == "legacy":
            legs = [(1.0, e + d * s_["amp"])]
        elif mode in ("tp3", "be"):
            legs = [(1.0, C + d * s_["amp"])]
        else:
            legs = [(1 / 3, C + d * risk),
                    (1 / 3, C + d * s_["amp2"]),
                    (1 / 3, C + d * s_["amp"])]
        legs = [(f, t) for f, t in legs if d * (t - e) > 0]
        if not legs:
            continue
        legs.sort(key=lambda x: d * x[1])
        tp1 = C + d * risk                      # the +0.5R breakeven trigger

        banked, size, stop = 0.0, 1.0, st
        for i in range(fill, n):
            if (d > 0 and lo[i] <= stop) or (d < 0 and hi[i] >= stop):
                banked += size * d * (stop - e) / risk
                size, free = 0.0, i
                break
            while legs and ((d > 0 and hi[i] >= legs[0][1])
                            or (d < 0 and lo[i] <= legs[0][1])):
                f, t = legs.pop(0)
                take = min(f, size)
                banked += take * d * (t - e) / risk
                size -= take
            if mode in ("be", "waves") and stop != e and (
                    (d > 0 and hi[i] >= tp1) or (d < 0 and lo[i] <= tp1)):
                stop = e
            if size <= 1e-9:
                free = i
                break
        if size > 1e-9:
            continue                            # still open at the data edge
        out.append(banked)
    return out


BOX = 0.50                                   # 8.29: Hunt's stated setting
CUT = pd.Timestamp("2023-01-01", tz="UTC")
# These H1 source files carry DAILY bars in their early years (~260 rows/yr where
# the timeframe expects thousands). Only the genuinely dense era is usable.
START = {"GoldCFD 2h": "2016-01-01", "BTCUSD 1h": "2017-01-01",
         "XAU/XAG 8h": "2016-01-01", "USDJPY 4h": "2011-01-01",
         "WTI 18h": "2017-01-01", "XAUEUR 1h": "2016-01-01"}   # everything at or after this is known
WANT = ["GoldCFD 2h", "BTCUSD 1h", "USDJPY 4h", "XAUEUR 1h", "XAU/XAG 8h", "WTI 18h"]


def enumerate_window(c0, box, frame):
    piv = zigzag_pct(frame, box)
    tab = coarse_table(frame)
    atr = _atr(frame, 14).to_numpy(float)
    close = frame["close"].to_numpy(float)
    out, seen = [], set()
    for d in (1, -1):
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
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
                            amp2=abs(w[2].price - w[3].price),
                            gated=bool(np.sign(mv) == d),
                            e_off=w[4].price - close[arm],
                            s_off=w[5].price - close[arm],
                            wait=w[5].index - w[0].index,
                            month=w[5].ts.tz_localize(None).to_period("M")))
    return out


MODES = ["legacy", "tp3", "be", "waves"]
LABEL = {"legacy": "8.22-8.30 (entry+AMP1, hard stop)",
         "tp3":    "TP3 only  (centre+AMP1, hard stop)",
         "be":     "TP3 + breakeven at +0.5R",
         "waves":  "thirds TP1/TP2/TP3 + breakeven"}


def stats(a):
    a = np.asarray(a, float)
    win, los = a[a > 0].sum(), -a[a < 0].sum()
    return len(a), (a > 0).mean(), a.mean(), win / los if los > 0 else float("inf")



if __name__ == "__main__":
    for period, lo_of, hi_of, note in [
            ("OUT-OF-SAMPLE (pre-2023, blind)", lambda nm: pd.Timestamp(START[nm], tz="UTC"), CUT, True),
            ("IN-SAMPLE (2023-2026)", lambda nm: CUT, None, False)]:
        print("\n" + "=" * 104)
        print(period)
        print("=" * 104)
        print(f"{'chart':<13}{'n':>5}" + "".join(f"{LABEL[m][:22]:>24}" for m in MODES))
        print(f"{'':<13}{'':>5}" + "".join(f"{'win%':>9}{'meanR':>8}{'PF':>7}" for m in MODES))
        print("-" * 104)
        acc = {m: [] for m in MODES}
        keep = {}
        for c0 in CHARTS:
            nm = c0["name"]
            if nm not in WANT:
                continue
            c, offs = offsets_for(c0)
            full = load_frame(c, offs[0] if offs[0] is not None else None)
            m0 = full["dt"] >= lo_of(nm)
            if hi_of is not None:
                m0 &= full["dt"] < hi_of
            frame = full[m0].reset_index(drop=True)
            if len(frame) < 500:
                print(f"{nm:<13}  insufficient history")
                continue
            picks = top(enumerate_window(c0, BOX, frame))
            res = {m: simulate(frame, picks, mode=m) for m in MODES}
            if not res["waves"]:
                print(f"{nm:<13}  no trades")
                continue
            row = f"{nm:<13}{len(res['waves']):>5}"
            for m in MODES:
                if res[m]:
                    n_, w_, r_, pf_ = stats(res[m])
                    row += f"{w_:>9.1%}{r_:>8.2f}{pf_:>7.2f}"
                    acc[m].append(np.asarray(res[m], float))
                else:
                    row += f"{'--':>24}"
            print(row, flush=True)
            keep[nm] = (frame, picks, res)
        print("-" * 104)
        row = f"{'POOLED':<13}{'':>5}"
        for m in MODES:
            if acc[m]:
                a = np.concatenate(acc[m]); n_, w_, r_, pf_ = stats(a)
                row += f"{w_:>9.1%}{r_:>8.2f}{pf_:>7.2f}"
            else:
                row += f"{'--':>24}"
        print(row)

        if note:
            print("\n" + "=" * 104)
            print("SHIFT-NULL on the blind years -- 200 random shifts, legacy vs waves")
            print("=" * 104)
            print(f"{'chart':<13}{'legacy R':>10}{'null':>8}{'pctile':>9}"
                  f"{'   ':>4}{'waves R':>10}{'null':>8}{'pctile':>9}")
            print("-" * 104)
            agg = []
            for nm, (frame, picks, res) in keep.items():
                out = [nm]
                cell = {}
                for m in ("legacy", "waves"):
                    real = float(np.mean(res[m])) if res[m] else 0.0
                    nulls = np.empty(NSEED)
                    for sd in range(NSEED):
                        rng = np.random.default_rng(sd)
                        sh = rng.integers(RAND_LO, RAND_HI) * rng.choice([-1, 1])
                        tt = simulate(frame, picks, shift=int(sh), mode=m)
                        nulls[sd] = np.mean(tt) if tt else 0.0
                    cell[m] = (real, nulls)
                agg.append((nm, cell, len(res["waves"])))
                print(f"{nm:<13}"
                      f"{cell['legacy'][0]:>10.2f}{cell['legacy'][1].mean():>8.2f}"
                      f"{(cell['legacy'][1] < cell['legacy'][0]).mean()*100:>8.1f}%"
                      f"{'':>4}"
                      f"{cell['waves'][0]:>10.2f}{cell['waves'][1].mean():>8.2f}"
                      f"{(cell['waves'][1] < cell['waves'][0]).mean()*100:>8.1f}%", flush=True)
            print("-" * 104)
            if agg:
                wts = np.array([k for _, _, k in agg], float)
                out = f"{'POOLED':<13}"
                for m in ("legacy", "waves"):
                    pr = np.average([c[m][0] for _, c, _ in agg], weights=wts)
                    pn = np.average(np.vstack([c[m][1] for _, c, _ in agg]), axis=0, weights=wts)
                    out += f"{pr:>10.2f}{pn.mean():>8.2f}{(pn < pr).mean()*100:>8.1f}%{'':>4}"
                print(out)
    print("\n8.30 for reference: legacy pooled +0.21R at the 57.5th percentile blind.")
