"""The MAIN trend, read off the DAILY series -- not off the funnel's own bars.

`hvf_v2_mef_maintrend` measured trend over 100-200 bars of the funnel's own
period and got at best 6/8 recall. That test was mis-specified: 100 bars of 2h
is eight days, which is not the main trend, it is the last fortnight's noise.
A trader reading "the main trend" for a 2h setup looks at the daily or weekly
chart. So measure it there, on calendar windows, independent of the funnel's
period -- which is also what makes the answer comparable across an 8h ratio
chart and a weekly FX chart.

Recall is the only thing this table decides. Eight charts, six of them
calibration, and any rule scoring below 8/8 cannot be used to REJECT
counter-trend funnels -- it would throw away setups Hunt actually took.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import load_ohlc, ratio_series, zigzag_pct  # noqa: E402
from hvf_v2_charts import CHARTS  # noqa: E402
from hvf_v2_mef_maintrend import best_match  # noqa: E402

DATA = ROOT / "backtests" / "data" / "hvf_v2"
BAR = "=" * 104
DAILY = {"GoldCFD 2h": ("XAUUSD_D1", None), "BTCUSD 1h": ("BTCUSD_D1", None),
         "XAU/XAG 8h": ("XAUUSD_D1", "XAGUSD_D1"), "USDJPY 4h": ("USDJPY_D1", None),
         "USDJPY 1W": ("USDJPY_D1", None), "WTI 18h": ("XTIUSD_D1", None),
         "XAUEUR 1h": ("XAUEUR_D1", None), "HYG 4h": ("HYG_NYSE_D1", None)}


def daily(name):
    src, den = DAILY[name]
    d = load_ohlc(str(DATA / f"{src}.csv"))
    return ratio_series(d, load_ohlc(str(DATA / f"{den}.csv"))) if den else d


def measures(d, i):
    """Signed trend readings at daily bar i, using only bars <= i."""
    c = d["close"].to_numpy(float)
    out = {}
    for n in (50, 200):
        if i >= n:
            out[f"D close vs SMA{n}"] = np.sign(c[i] - c[i - n + 1:i + 1].mean())
        else:
            out[f"D close vs SMA{n}"] = np.nan
    for days, lbl in ((90, "3m"), (180, "6m"), (365, "1y")):
        out[f"D net move {lbl}"] = np.sign(c[i] - c[i - days]) if i >= days else np.nan
    for pct, lbl in ((5.0, "5%"), (10.0, "10%")):
        piv = zigzag_pct(d.iloc[:i + 1].reset_index(drop=True), pct)
        conf = [p for p in piv if p.confirm is not None and 0 <= p.confirm <= i]
        out[f"D zigzag {lbl} leg"] = (1.0 if conf[-1].kind == "H" else -1.0) if conf else np.nan
    return out


NAMES = list(measures(daily("GoldCFD 2h"), 900).keys())
print(BAR)
print("MAIN TREND ON THE DAILY SERIES -- does it agree with the way Hunt traded?")
print(BAR)
print(f"{'chart':<13}{'Hunt':>7}" + "".join(f"{n.replace('D ', ''):>13}" for n in NAMES))
print("-" * 104)
hits = {n: 0 for n in NAMES}
tot = 0
for c0 in CHARTS:
    b = best_match(c0)
    if b is None:
        continue
    _, frame, piv, idx, box, off = b
    ts = piv[idx[0]].ts
    d = daily(c0["name"])
    j = int(d["dt"].searchsorted(ts, side="right")) - 1
    if j < 0:
        continue
    m = measures(d, j)
    tot += 1
    cells = ""
    for n in NAMES:
        v = m[n]
        ok = np.isfinite(v) and v == c0["dir"]
        hits[n] += ok
        cells += f"{('OK' if ok else 'WRONG') if np.isfinite(v) else 'n/a':>13}"
    print(f"{c0['name']:<13}{('long' if c0['dir'] > 0 else 'short'):>7}{cells}",
          flush=True)
print("-" * 104)
print(f"{'recall':<13}{'':>7}" + "".join(f"{f'{hits[n]}/{tot}':>13}" for n in NAMES))
print(BAR)
