"""Financing against the BLIND gross (spec 8.33).

8.27 priced carry and concluded "costs do not kill this". That verdict is stale for
a reason that has nothing to do with the cost model: it compared a drag of 0.24-0.31R
against a GROSS of 1.72R (gold) and 0.85R (BTC), both measured in the 2023-2026
in-sample window with the legacy exit. 8.30 then showed the blind gross is 0.19-0.31R
and 8.31 showed the exit geometry was wrong.

Financing drag is an ABSOLUTE number of R, not a fraction of it. A 0.27R drag against
1.72R is 16%. The same 0.27R against a blind +0.31R is the whole edge. So the question
has to be re-asked against the numbers that survived.

Two things this models that 8.27 did not:

1. The corrected three-wave exit. Taking a third off at TP1 (always +0.5R, and reached
   early) retires a third of the notional, so carry is integrated over the DECAYING
   position, not a flat one. This is a genuine advantage of trading it Hunt's way and
   8.27 could not have seen it.
2. Per-trade integration rather than mean-hold x rate. The hold distribution is
   long-tailed (8.27: median 6.2d, mean 12.3d on gold), and drag scales with time, so
   the mean of the product is not the product of the means.

Financing is charged on calendar days elapsed, which includes weekends. That is correct
for crypto and slightly pessimistic for gold/FX, where a weekend is charged as the
triple-swap Wednesday instead -- same weekly total, different distribution.
"""
import contextlib
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# hvf_v2_mef_backtest / _ablation / _rank print their whole reports at import time
# (only _waves is __main__-guarded), so swallow it.
with contextlib.redirect_stdout(io.StringIO()):
    import hvf_v2_mef_waves as W  # noqa: E402
    from hvf_v2_charts import CHARTS  # noqa: E402
    from hvf_v2_mef import load_frame  # noqa: E402
    from hvf_v2_mef_rank import offsets_for  # noqa: E402

# Annual financing on notional, %/yr. Central estimate then a low/high sweep.
# BTC is published by IC Markets at -20%/yr, tripled Fridays [I]. Gold is not
# published; 4-10% is the band implied by broker swap tables (8.27). XAUEUR and
# XAU/XAG carry two metal legs, WTI is a rolled commodity CFD -- all treated as
# gold-like. USDJPY is an interest differential, small and sometimes positive;
# charged at 2% central as a conservative cost rather than a credit.
RATES = {"GoldCFD 2h": (4.0, 7.0, 10.0),
         "BTCUSD 1h": (15.0, 20.0, 25.0),
         "XAU/XAG 8h": (4.0, 7.0, 10.0),
         "USDJPY 4h": (0.0, 2.0, 4.0),
         "WTI 18h": (4.0, 7.0, 10.0),
         "XAUEUR 1h": (4.0, 7.0, 10.0)}


def simulate_detail(frame, picks, hours, mode="waves"):
    """W.simulate, but returning (R, carry_units) per trade instead of just R.

    carry_units = integral of (position size x notional/risk) dt, in units of
    days x leverage. Multiply by rate/365 to get R lost to financing. Notional
    is marked at the ENTRY price and held flat for the life of the trade; a
    broker marks it daily, but the difference is second-order next to the
    rate uncertainty and it keeps the number reproducible.
    """
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    day = hours / 24.0
    n, free, out = len(frame), -1, []
    for s_ in sorted(picks, key=lambda x: x["arm"]):
        arm = s_["arm"]
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
        else:
            legs = [(1 / 3, C + d * risk),
                    (1 / 3, C + d * s_["amp2"]),
                    (1 / 3, C + d * s_["amp"])]
        legs = [(f, t) for f, t in legs if d * (t - e) > 0]
        if not legs:
            continue
        legs.sort(key=lambda x: d * x[1])
        tp1 = C + d * risk

        lev = abs(e) / risk                  # notional per unit of risk
        banked, size, stop, carry = 0.0, 1.0, st, 0.0
        for i in range(fill, n):
            carry += size * lev * day        # held through this bar
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
            if mode == "waves" and stop != e and (
                    (d > 0 and hi[i] >= tp1) or (d < 0 and lo[i] <= tp1)):
                stop = e
            if size <= 1e-9:
                free = i
                break
        if size > 1e-9:
            continue
        out.append((banked, carry, (i - fill + 1) * day, lev))
    return out


if __name__ == "__main__":
    rows = []
    for nm in W.WANT:
        c0 = next(c for c in CHARTS if c["name"] == nm)
        c, offs = offsets_for(c0)
        full = load_frame(c, offs[0] if offs[0] is not None else None)
        lo_ = pd.Timestamp(W.START[nm], tz="UTC")
        frame = full[(full["dt"] >= lo_) & (full["dt"] < W.CUT)].reset_index(drop=True)
        cands = W.enumerate_window(c0, W.BOX, frame)
        picks = W.top(cands)
        print(f"{nm}: {len(frame):,} bars, {len(cands):,} candidates, "
              f"{len(picks)} picks", flush=True)
        for mode in ("legacy", "waves"):
            det = simulate_detail(frame, picks, c0["hours"], mode)
            if not det:
                continue
            R = np.array([x[0] for x in det])
            car = np.array([x[1] for x in det])
            dur = np.array([x[2] for x in det])
            lev = np.array([x[3] for x in det])
            for tag, rate in zip(("lo", "mid", "hi"), RATES[nm]):
                rows.append(dict(chart=nm, mode=mode, tag=tag, n=len(R),
                                 gross=R.mean(),
                                 drag=(car * rate / 100.0 / 365.0).mean(),
                                 med_d=np.median(dur), mean_d=dur.mean(),
                                 lev=np.median(lev), rate=rate))
        del cands

    df = pd.DataFrame(rows)
    df["net"] = df["gross"] - df["drag"]

    for mode in ("legacy", "waves"):
        print(f"\n\n{'=' * 92}\n{mode.upper()} exit -- blind years (pre-2023)\n{'=' * 92}")
        print(f"{'chart':<14}{'n':>5}{'lev':>7}{'med d':>8}{'mean d':>8}"
              f"{'gross':>8}{'rate':>7}{'drag':>8}{'net':>8}")
        print("-" * 92)
        m = df[df["mode"] == mode]
        for nm in W.WANT:
            g = m[m["chart"] == nm]
            for _, r in g.iterrows():
                lab = nm if r["tag"] == "lo" else ""
                print(f"{lab:<14}{r['n']:>5}{r['lev']:>7.0f}{r['med_d']:>8.1f}"
                      f"{r['mean_d']:>8.1f}{r['gross']:>8.2f}{r['rate']:>6.0f}%"
                      f"{r['drag']:>8.2f}{r['net']:>8.2f}")
            print("-" * 92)
        # Pooled: weight each chart by its trade count, at the central rate.
        c = m[m["tag"] == "mid"]
        w = c["n"].to_numpy(float)
        print(f"{'POOLED (mid)':<14}{int(w.sum()):>5}{'':>7}{'':>8}{'':>8}"
              f"{np.average(c['gross'], weights=w):>8.2f}{'':>7}"
              f"{np.average(c['drag'], weights=w):>8.2f}"
              f"{np.average(c['net'], weights=w):>8.2f}")
