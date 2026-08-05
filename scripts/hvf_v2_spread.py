"""What does the spread cost, and what does it cost it *of*? (spec 8.37)

8.36 left one unmodelled cost: the bid/ask. It is the last thing between "+0.081R of real
structure" and "tradeable".

**First, a correction to 8.33's parenthetical.** It claimed the three-wave exit "pays the
spread four times" because it fills four times. That is wrong. Spread is charged on
*volume*, not on ticket count: entering one unit and exiting in three thirds crosses the
spread on exactly the same total volume as a single exit. Worse, the direction of the
error was pessimistic in the wrong place -- the three-wave exit is not penalised at all
relative to a single exit.

In fact each round trip crosses the spread **exactly once**, whichever way it is taken.
OHLC feeds quote the bid. A long triggers when the bid reaches the entry but *buys at the
ask*, then sells back at the bid -- one spread, at entry. A short sells at the bid, then
buys back at the ask -- one spread, at exit. Neither pays it twice.

**What the cost actually scales with.** Filling at `e + d*spread` while having sized on
the planned risk `|e - st|` shifts every outcome by the same amount:

    cost in R  =  spread / risk  =  (spread / price) * (price / risk)  =  spread_frac * LEV

`LEV = |e| / risk` is the notional carried per unit of risk -- the same quantity that made
financing expensive in 8.33. HVF puts its stop just outside the smallest funnel, so `risk`
is tiny and `LEV` is large, which means **HVF is unusually spread-sensitive for a swing
strategy**. Commission adds `2 * comm_frac * LEV` (charged both sides).

So the honest output is not a single net number resting on a spread table I would have to
guess. It is a **breakeven cost**: how many basis points of round-trip cost each
instrument can absorb before its edge is gone. A published spread table can then be laid
over it, and the reader can substitute their own.

One thing spread does *not* change: the 8.36a lift. Cost is a near-constant subtraction
per trade and the shuffled trades carry the same LEV, so it cancels. **Spread decides
tradeability, not validity.**
"""
import contextlib
import io
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

with contextlib.redirect_stdout(io.StringIO()):
    from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc
    from hvf_v2_mef_carry_blind import simulate_detail
    from hvf_v2_wide_run import RATE, klass, universe

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
                "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")

# IC Markets Raw Spread, typical, expressed as ROUND-TRIP basis points of notional
# (spread once + commission both sides). These are the reference overlay, not an input to
# any fitted quantity -- 8.37's output is the breakeven, which is table-independent.
#   fx        0.1 pip (~0.09bp) + $7/100k commission (0.7bp)
#   index     ~1.2 index points on a mid-teens-thousand index, commission-free
#   metal     ~$0.15 on gold + commission
#   commodity energy/ags CFDs are wider and commission-free
#   crypto    the outlier by an order of magnitude
#   yield     NOT DIRECTLY TRADEABLE -- see the caveat printed below
COST_BP = {"fx": 0.8, "index": 1.0, "metal": 1.5, "commodity": 4.0,
           "etf": 2.0, "crypto": 25.0, "yield": 3.0}


def main():
    picks_all = pickle.loads((SCRATCH / "wide_picks.pkl").read_bytes())
    nulls = pickle.loads((SCRATCH / "wide_null.pkl").read_bytes())["real"]

    rows = []
    for name, f, hours, df in universe():
        if name not in picks_all or not picks_all[name] or name == "BTCUSD":
            continue
        frame = resample_ohlc(df, hours) if hours != 1.0 else df
        if len(frame) < 600:
            continue
        det = simulate_detail(frame, picks_all[name], hours, "waves")
        if len(det) < 15:
            continue
        rate = RATE[klass(name)]
        # 8.36's net: gross minus financing, before spread
        net0 = np.array([x[0] - x[1] * rate / 100.0 / 365.0 for x in det])
        lev = np.array([x[3] for x in det])
        # R lost per basis point of round-trip cost, averaged over this instrument's trades
        r_per_bp = float(np.mean(lev)) * 1e-4
        rows.append(dict(name=name, klass=klass(name), n=len(det),
                         net0=float(net0.mean()), lev=float(np.mean(lev)),
                         lev_med=float(np.median(lev)), r_per_bp=r_per_bp,
                         be_bp=float(net0.mean()) / r_per_bp if r_per_bp > 0 else np.nan))

    print(f"{'=' * 86}\nLEVERAGE: notional carried per unit of risk (this is the "
          f"spread multiplier)\n{'=' * 86}")
    lv = np.array([r["lev"] for r in rows])
    print(f"  instruments {len(rows)},  mean LEV {lv.mean():>7.0f}x,  "
          f"median {np.median(lv):>6.0f}x,  range {lv.min():.0f}-{lv.max():.0f}x")
    print(f"  => 1 bp of round-trip cost = {np.median(lv) * 1e-4:.4f} R at the median "
          f"instrument")

    print(f"\n{'class':<11}{'k':>4}{'LEV':>8}{'net pre':>10}{'R / bp':>9}"
          f"{'breakeven':>11}{'IC bp':>8}{'net post':>10}")
    print("-" * 86)
    tot = []
    by = {}
    for r in rows:
        by.setdefault(r["klass"], []).append(r)
    for c in sorted(by):
        g = by[c]
        lev_ = np.mean([x["lev"] for x in g])
        n0 = np.mean([x["net0"] for x in g])
        rpb = np.mean([x["r_per_bp"] for x in g])
        bp = COST_BP[c]
        n1 = n0 - rpb * bp
        tot += [(x, bp) for x in g]
        print(f"{c:<11}{len(g):>4}{lev_:>8.0f}{n0:>10.3f}{rpb:>9.4f}"
              f"{n0 / rpb:>10.1f}bp{bp:>8.1f}{n1:>10.3f}")
    print("-" * 86)

    n0 = np.mean([x["net0"] for x, _ in tot])
    n1 = np.mean([x["net0"] - x["r_per_bp"] * bp for x, bp in tot])
    print(f"{'UNIVERSE':<11}{len(tot):>4}{'':>8}{n0:>10.3f}{'':>9}{'':>11}{'':>8}{n1:>10.3f}")
    print(f"\n  spread+commission takes {100 * (n0 - n1) / n0:.0f}% of the pre-spread net")
    print(f"  instruments still positive: "
          f"{sum(1 for x, bp in tot if x['net0'] - x['r_per_bp'] * bp > 0)} / {len(tot)}")

    print(f"\n{'=' * 86}\nSENSITIVITY: universe net vs a flat round-trip cost applied to "
          f"every instrument\n{'=' * 86}")
    print(f"  {'bp':>6}{'net R':>10}{'positive':>11}")
    for bp in [0, 0.5, 1, 2, 3, 5, 8, 12, 20]:
        v = [x["net0"] - x["r_per_bp"] * bp for x in rows]
        print(f"  {bp:>6}{np.mean(v):>10.3f}{sum(1 for z in v if z > 0):>7} / {len(v)}")

    print(f"\nworst 12 by breakeven (thinnest margin for cost):")
    for r in sorted(rows, key=lambda x: x["be_bp"])[:12]:
        print(f"  {r['name']:<10}{r['klass']:<11}LEV {r['lev']:>6.0f}x  "
              f"net {r['net0']:>6.3f}  breakeven {r['be_bp']:>7.1f}bp  "
              f"(IC ~{COST_BP[r['klass']]:.1f}bp)")
    print(f"\nbest 12 by breakeven (most cost headroom):")
    for r in sorted(rows, key=lambda x: -x["be_bp"])[:12]:
        print(f"  {r['name']:<10}{r['klass']:<11}LEV {r['lev']:>6.0f}x  "
              f"net {r['net0']:>6.3f}  breakeven {r['be_bp']:>7.1f}bp  "
              f"(IC ~{COST_BP[r['klass']]:.1f}bp)")

    print("\nCAVEAT: the yield block is not directly tradeable. Those rows price the "
          "\n  *series*, not an instrument -- expressing them means bond futures or ETFs, "
          "\n  whose cost and financing differ. 8.36 already showed yields are 84% drift, "
          "\n  so little is lost by dropping them.")
    (SCRATCH / "spread.pkl").write_bytes(pickle.dumps(rows))


if __name__ == "__main__":
    main()
