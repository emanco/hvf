"""What does this cost to trade? (spec 8.27)

Every number from 8.22 to 8.26 assumed a fill at the trigger price with zero
spread, zero commission and zero slippage. 8.26 made that assumption more
dangerous, not less: the exit turned out to have no slack in it at all, so
there is nothing in the trade management to absorb a bad fill.

Two questions, in the order that matters.

  1. How much round-trip cost does each instrument absorb before mean R is
     zero? Reported in the instrument's own units, so it can be checked
     against a broker's spread sheet directly instead of guessed at.
  2. Does the edge survive a pessimistic fill -- next bar's OPEN rather than
     the trigger price? The entry sits at a level price is actively moving
     through (8.21: median fill 1 bar after RL3.confirm), which is exactly
     where a resting order gets the worst of it.

Costs are charged as `net_R = gross_R - C / risk`, C being the all-in
round-trip cost in price units. Slightly conservative: it ignores that a
wider effective entry also moves the stop marginally further away.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_mef import HELD_OUT  # noqa: E402
import hvf_v2_mef_exit as X  # noqa: E402

# Contract sizes, for turning a per-unit cost into money on one lot.
LOT = {"GoldCFD 2h": 100, "BTCUSD 1h": 1, "XAUEUR 1h": 100,
       "USDJPY 4h": 100_000, "XAU/XAG 8h": 1, "WTI 18h": 1000, "USDJPY 1W": 100_000}


def priced(frame, picks, open_fill=False):
    """Baseline trades, but also returning entry price and risk in price units."""
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    op = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
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
        if open_fill:
            # The pessimistic fill: you are not filled at your price, you are
            # filled at the next bar's open. Stop and target stay where the
            # funnel put them, so this changes R as well as the entry.
            if fill + 1 >= n:
                continue
            e2 = op[fill + 1]
            if (d > 0 and e2 <= st) or (d < 0 and e2 >= st):
                continue                      # gapped through the stop
            e, risk, fill = e2, abs(e2 - st), fill + 1
        tgt = e + d * (s["amp"] / abs(close[arm] + s["e_off"] - st)) * risk
        res = None
        for i in range(fill, n):
            if (d > 0 and lo[i] <= st) or (d < 0 and hi[i] >= st):
                res, free = d * (st - e) / risk, i
                break
            if (d > 0 and hi[i] >= tgt) or (d < 0 and lo[i] <= tgt):
                res, free = d * (tgt - e) / risk, i
                break
        if res is not None:
            out.append((res, e, risk))
    return out


PICK = ["GoldCFD 2h", "BTCUSD 1h", "XAUEUR 1h", "USDJPY 4h"]

print("=" * 104)
print("1. WHAT THE TRADES ACTUALLY RISK -- baseline top-3/month, in native units")
print("=" * 104)
print(f"{'chart':<13}{'':<3}{'n':>5}{'median price':>14}{'median risk':>13}"
      f"{'risk % price':>14}{'risk $ / lot':>14}{'mean R':>9}")
print("-" * 104)
BOOK = {}
for name in PICK:
    c0, frame, cands = X.POOL[name]
    t = priced(frame, X.PICKS[name])
    if not t:
        continue
    r = np.array([x[0] for x in t])
    e = np.array([x[1] for x in t])
    k = np.array([x[2] for x in t])
    BOOK[name] = (r, e, k)
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{len(t):>5}"
          f"{np.median(e):>14,.2f}{np.median(k):>13,.4f}"
          f"{np.median(k / e):>13.2%}{np.median(k) * LOT[name]:>14,.0f}"
          f"{r.mean():>9.2f}")
print("-" * 104)

print()
print("=" * 104)
print("2. BREAKEVEN COST -- all-in round trip (spread + commission + slippage)")
print("=" * 104)
print(f"{'chart':<13}{'':<3}{'mean R':>9}{'median risk':>13}"
      f"{'breakeven cost':>17}{'per lot':>12}{'50% of it':>13}{'25% of it':>13}")
print("-" * 104)
for name, (r, e, k) in BOOK.items():
    # C such that mean(gross_R - C/risk) == 0
    c = r.mean() / np.mean(1.0 / k)
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{r.mean():>9.2f}"
          f"{np.median(k):>13,.4f}{c:>17,.4f}{c * LOT[name]:>12,.0f}"
          f"{c / 2:>13,.4f}{c / 4:>13,.4f}")
print("-" * 104)
print("Read: at the breakeven cost the strategy makes exactly nothing. You want")
print("actual round-trip cost well under the '25% of it' column -- that leaves")
print("three quarters of the edge intact.")

print()
print("=" * 104)
print("3. COST SWEEP -- mean R net of an all-in round trip, as a fraction of risk")
print("=" * 104)
FRAC = [0.0, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30]
print(f"{'chart':<13}{'':<3}" + "".join(f"{f'{f:.0%}':>11}" for f in FRAC))
print("-" * 104)
for name, (r, e, k) in BOOK.items():
    cells = "".join(f"{(r - f).mean():>11.2f}" for f in FRAC)
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{cells}")
print("-" * 104)
print("Columns are cost as a fraction of the trade's own risk, so 5% means the")
print("round trip eats 5% of the distance from entry to stop.")

print()
print("=" * 104)
print("4. PESSIMISTIC FILL -- next bar's OPEN instead of the trigger price")
print("=" * 104)
print(f"{'chart':<13}{'':<3}{'n':>6}{'trigger fill':>15}{'open fill':>12}"
      f"{'delta':>9}{'n':>7}{'gapped out':>13}")
print("-" * 104)
for name in BOOK:
    c0, frame, cands = X.POOL[name]
    a = np.array([x[0] for x in priced(frame, X.PICKS[name])])
    b = np.array([x[0] for x in priced(frame, X.PICKS[name], open_fill=True)])
    print(f"{name:<13}{'T' if name in HELD_OUT else '':<3}{len(a):>6}"
          f"{a.mean():>15.2f}{b.mean():>12.2f}{b.mean() - a.mean():>+9.2f}"
          f"{len(b):>7}{len(a) - len(b):>13}")
print("-" * 104)
print("Zero costs still. This isolates fill quality from spread.")
