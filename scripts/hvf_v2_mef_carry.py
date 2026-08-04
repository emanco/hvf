"""How long is the money at risk? (spec 8.27b)

8.27 priced the round trip and found it trivial next to these stops. But a
round-trip cost is charged once, and financing is charged every night. IC
Markets funds crypto CFDs at -20%/yr on *notional*, and notional here is ~46x
the trade's own risk (BTC risk is 2.24% of price), so the leverage works
against us: a cost that looks small per year is large per R per day.

Reported per instrument: bars held, calendar days held, and the swap-equivalent
drag in R per day and over the median hold.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hvf_v2_mef_exit as X  # noqa: E402

# Annual financing rate on notional, IC Markets global entity.
# Implied annual financing on notional. Crypto is published (-20%); gold is not,
# so it is swept across the range implied by broker swap tables at current rates
# (~$30-$74 per 100oz lot per night on a ~$2.6k ounce).
SWAP = {"GoldCFD 2h": 0.07, "BTCUSD 1h": 0.20, "XAUEUR 1h": 0.07, "USDJPY 4h": None}
SWEEP = {"GoldCFD 2h": [0.04, 0.07, 0.10], "BTCUSD 1h": [0.15, 0.20, 0.25]}


def held(frame, picks):
    hi, lo = frame["high"].to_numpy(float), frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    idx = frame["dt"].to_numpy()
    n, free, out = len(frame), -1, []
    for s in sorted(picks, key=lambda x: x["arm"]):
        arm = s["arm"]
        if arm + 1 >= n or arm <= free:
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
            done = ((d > 0 and lo[i] <= st) or (d < 0 and hi[i] >= st) or
                    (d > 0 and hi[i] >= tgt) or (d < 0 and lo[i] <= tgt))
            if done:
                days = (idx[i] - idx[fill]) / np.timedelta64(1, "D")
                out.append((i - fill, days, e, risk))
                free = i
                break
    return out


print(f"{'chart':<14}{'n':>4}{'bars: med':>11}{'p90':>7}"
      f"{'days: med':>11}{'mean':>8}{'p90':>8}{'max':>8}")
print("-" * 72)
BOOK = {}
for name in ["GoldCFD 2h", "BTCUSD 1h", "XAUEUR 1h", "USDJPY 4h"]:
    _, frame, _ = X.POOL[name]
    h = held(frame, X.PICKS[name])
    if not h:
        continue
    bars = np.array([x[0] for x in h], float)
    days = np.array([x[1] for x in h], float)
    BOOK[name] = h
    print(f"{name:<14}{len(h):>4}{np.median(bars):>11.0f}{np.percentile(bars,90):>7.0f}"
          f"{np.median(days):>11.1f}{days.mean():>8.1f}"
          f"{np.percentile(days,90):>8.1f}{days.max():>8.1f}")

print()
print("FINANCING DRAG at -20%/yr on notional (crypto only)")
print("-" * 72)
print(f"{'chart':<14}{'notional/risk':>15}{'R lost / day':>14}"
      f"{'over median hold':>18}{'over p90 hold':>15}")
print("-" * 72)
for name, rate in SWAP.items():
    if rate is None or name not in BOOK:
        continue
    h = BOOK[name]
    lev = np.array([x[2] / x[3] for x in h])       # notional / risk, per trade
    days = np.array([x[1] for x in h])
    per_day = rate / 365.0 * lev                    # R per day
    print(f"{name:<14}{np.median(lev):>15.1f}{np.median(per_day):>14.3f}"
          f"{np.median(per_day * days):>18.2f}{np.percentile(per_day*days,90):>15.2f}")

GROSS = {"GoldCFD 2h": 1.72, "BTCUSD 1h": 0.85, "XAUEUR 1h": 1.22}
print()
print("NET OF FINANCING")
print("-" * 72)
for name, rate in SWAP.items():
    if rate is None or name not in BOOK:
        continue
    h = BOOK[name]
    drag = np.array([rate / 365.0 * (x[2] / x[3]) * x[1] for x in h])
    print(f"{name:<14} mean drag {drag.mean():>6.2f}R   "
          f"gross {GROSS[name]:.2f}R -> net {GROSS[name] - drag.mean():>5.2f}R")


GROSS2 = {"GoldCFD 2h": 1.72, "BTCUSD 1h": 0.85, "XAUEUR 1h": 1.22}
print()
print("SENSITIVITY -- net mean R across plausible financing rates")
print("-" * 72)
for name, rates in SWEEP.items():
    h = BOOK[name]
    cells = []
    for rt in rates:
        drag = np.array([rt / 365.0 * (x[2] / x[3]) * x[1] for x in h]).mean()
        cells.append(f"{rt*100:>4.0f}%/yr -> {GROSS2[name] - drag:>5.2f}R")
    print(f"{name:<14}" + "   ".join(cells))
