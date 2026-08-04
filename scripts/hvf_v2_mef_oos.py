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
                            gated=bool(np.sign(mv) == d),
                            e_off=w[4].price - close[arm],
                            s_off=w[5].price - close[arm],
                            wait=w[5].index - w[0].index,
                            month=w[5].ts.tz_localize(None).to_period("M")))
    return out


print(f"{'chart':<13}{'span':>26}{'n':>6}{'win%':>7}{'meanR':>8}{'totR':>9}"
      f"{'PF':>7}{'null mean':>11}{'pctile':>9}{'/yr':>6}")
print("-" * 102)
ALL = []
for c0 in CHARTS:
    if c0["name"] not in WANT:
        continue
    c, offs = offsets_for(c0)
    full = load_frame(c, offs[0] if offs[0] is not None else None)
    lo = pd.Timestamp(START[c0["name"]], tz="UTC")
    frame = full[(full["dt"] >= lo) & (full["dt"] < CUT)].reset_index(drop=True)
    if len(frame) < 500:
        print(f"{c0['name']:<13}{'insufficient history':>26}")
        continue
    cands = enumerate_window(c0, BOX, frame)
    picks = top(cands)
    t = simulate(frame, picks)
    if not t:
        print(f"{c0['name']:<13}{'no trades':>26}")
        continue
    a = np.array(t)
    yrs = (frame['dt'].iloc[-1] - frame['dt'].iloc[0]).days / 365.25
    span = (f"{frame['dt'].iloc[0].date()}..{frame['dt'].iloc[-1].date()}")
    wins, loss = a[a > 0].sum(), -a[a < 0].sum()
    pf = wins / loss if loss > 0 else float("inf")
    nulls = np.empty(NSEED)
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        sh = rng.integers(RAND_LO, RAND_HI) * rng.choice([-1, 1])
        tt = simulate(frame, picks, shift=int(sh))
        nulls[s] = np.mean(tt) if tt else 0.0
    pct = float((nulls < a.mean()).mean() * 100)
    ALL.append((c0["name"], a, nulls))
    print(f"{c0['name']:<13}{span:>26}{len(a):>6}{(a > 0).mean():>7.1%}"
          f"{a.mean():>8.2f}{a.sum():>9.1f}{pf:>7.2f}{nulls.mean():>11.2f}"
          f"{pct:>8.1f}%{len(a)/yrs:>6.1f}", flush=True)
print("-" * 102)
if ALL:
    w = np.array([len(a) for _, a, _ in ALL], float)
    pooled = float(np.average([a.mean() for _, a, _ in ALL], weights=w))
    pn = np.average(np.vstack([n for _, _, n in ALL]), axis=0, weights=w)
    print(f"{'POOLED':<13}{'':>26}{int(w.sum()):>6}{'':>7}{pooled:>8.2f}"
          f"{'':>9}{'':>7}{pn.mean():>11.2f}{(pn < pooled).mean()*100:>8.1f}%")
print()
print(f"Compare 8.29 in-sample (2023-2026, same rules): gold +1.57R at the 99th,")
print(f"pooled +0.51R at the 95th. Nothing was tuned between the two periods.")
