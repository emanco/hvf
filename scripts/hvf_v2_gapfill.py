"""Gap-aware fills, and what slippage actually costs (spec 8.38).

8.37c left slippage on stop exits unmodelled. It is the last cost, and for HVF it is
structurally the most dangerous one: the stop sits just outside the *smallest* funnel, so
`risk` is tiny, leverage is 61-75x, and `slippage in R = slippage_frac * LEV` amplifies
exactly as spread does.

But the dominant term is not tick-level slippage, and it is **not a parameter that has to
be guessed**. It is a defect in the fill model, and the data already on disk prices it
exactly. `simulate_detail` fills every level at the level itself:

    if (d > 0 and lo[i] <= stop) or (d < 0 and hi[i] >= stop):
        banked += size * d * (stop - e) / risk

If the bar *opened* through the stop, that fill never existed -- the real fill is the
open. On 3D bars, where a single bar spans a weekend, a gap through a funnel-tight stop is
routine. Three corrections follow, and they do not all point the same way:

* **entry** is a breakout stop order, so a gap through it fills *worse*  -> costs
* **stop** is a stop order, so a gap through it fills *worse*            -> costs
* **take-profits** are limit orders, so a gap through them fills *better* -> pays

The third is why this has to be measured rather than assumed pessimistic. Modelling only
the stop gap would overstate the damage.

Within-bar ordering stays as 8.33 had it -- stop checked before targets, the conservative
reading -- with one addition: if the bar opens beyond the stop, that fill happens at the
open before anything else can occur.

On top of the gaps, a residual per-fill slippage (ticks beyond the level, on entry and
stop only) is swept rather than fixed, so the answer can be read off at whatever level a
real fill log later shows.
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
    from hvf_trader.detector.hvf_v2 import resample_ohlc
    from hvf_v2_mef_carry_blind import simulate_detail
    from hvf_v2_spread import COST_BP
    from hvf_v2_wide_run import RATE, klass, universe

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
                "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")


def simulate_gap(frame, picks, hours, slip_bp=0.0):
    """simulate_detail, but every fill respects the bar's open.

    Returns (R, carry_units, days, lev, gapped_entry, gapped_stop, gapped_tp) per trade.
    `slip_bp` is residual slippage in basis points of price, charged on entry and stop
    (adverse only) -- never on limit exits, which do not slip against you.
    """
    op = frame["open"].to_numpy(float)
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

        # -- entry: breakout stop order. A bar that opens beyond it fills at the open.
        fill, e_fill, gap_e = None, None, 0
        for i in range(arm + 1, min(arm + 1 + s_["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                through = (d > 0 and op[i] > e) or (d < 0 and op[i] < e)
                e_fill = op[i] if through else e
                gap_e = int(through)
                fill = i
                break
        if fill is None:
            continue
        e_fill += d * abs(e_fill) * slip_bp * 1e-4        # residual, always adverse

        # Targets and stop are set from the PLANNED geometry -- what was sized on --
        # not from the slipped fill. Risk in the denominator is likewise the planned one.
        C = (e + st) / 2.0
        legs = [(1 / 3, C + d * risk), (1 / 3, C + d * s_["amp2"]), (1 / 3, C + d * s_["amp"])]
        legs = [(f, t) for f, t in legs if d * (t - e) > 0]
        if not legs:
            continue
        legs.sort(key=lambda x: d * x[1])
        tp1 = C + d * risk

        lev = abs(e) / risk
        banked, size, stop, carry = 0.0, 1.0, st, 0.0
        gap_s = gap_t = 0
        for i in range(fill, n):
            carry += size * lev * day
            # stop first (conservative), and a gap through it pre-empts everything
            if (d > 0 and lo[i] <= stop) or (d < 0 and hi[i] >= stop):
                through = (d > 0 and op[i] < stop) or (d < 0 and op[i] > stop)
                px = op[i] if through else stop
                px -= d * abs(px) * slip_bp * 1e-4        # residual, always adverse
                gap_s = int(through)
                banked += size * d * (px - e_fill) / risk
                size, free = 0.0, i
                break
            while legs and ((d > 0 and hi[i] >= legs[0][1]) or (d < 0 and lo[i] <= legs[0][1])):
                f, t = legs.pop(0)
                through = (d > 0 and op[i] > t) or (d < 0 and op[i] < t)
                px = op[i] if through else t              # limit gapped in our favour
                gap_t += int(through)
                take = min(f, size)
                banked += take * d * (px - e_fill) / risk
                size -= take
            if stop != e and ((d > 0 and hi[i] >= tp1) or (d < 0 and lo[i] <= tp1)):
                stop = e
            if size <= 1e-9:
                free = i
                break
        if size > 1e-9:
            continue
        out.append((banked, carry, (i - fill + 1) * day, lev, gap_e, gap_s, gap_t))
    return out


def main():
    picks_all = pickle.loads((SCRATCH / "wide_picks.pkl").read_bytes())
    frames = {}
    for name, f, hours, df in universe():
        if name not in picks_all or not picks_all[name] or name == "BTCUSD":
            continue
        fr = resample_ohlc(df, hours) if hours != 1.0 else df
        if len(fr) >= 600:
            frames[name] = (fr, hours)

    def run(slip):
        rows = []
        for name, (fr, hours) in frames.items():
            det = simulate_gap(fr, picks_all[name], hours, slip)
            if len(det) < 15:
                continue
            rate, bp = RATE[klass(name)], COST_BP[klass(name)]
            net = [x[0] - x[1] * rate / 100.0 / 365.0 - x[3] * bp * 1e-4 for x in det]
            rows.append(dict(name=name, klass=klass(name), n=len(det),
                             net=float(np.mean(net)),
                             ge=np.mean([x[4] for x in det]),
                             gs=np.mean([x[5] for x in det]),
                             gt=np.mean([x[6] for x in det])))
        return rows

    # -- baseline: 8.37's own fill model, for a like-for-like difference
    base = []
    for name, (fr, hours) in frames.items():
        det = simulate_detail(fr, picks_all[name], hours, "waves")
        if len(det) < 15:
            continue
        rate, bp = RATE[klass(name)], COST_BP[klass(name)]
        base.append(dict(name=name, klass=klass(name),
                         net=float(np.mean([x[0] - x[1] * rate / 100.0 / 365.0
                                            - x[3] * bp * 1e-4 for x in det]))))
    b = {r["name"]: r["net"] for r in base}

    g0 = run(0.0)
    print(f"{'=' * 84}\nHOW OFTEN DOES PRICE GAP THROUGH A LEVEL?\n{'=' * 84}")
    print(f"  entry gapped through   {100 * np.mean([r['ge'] for r in g0]):>6.1f}% of trades")
    print(f"  STOP gapped through    {100 * np.mean([r['gs'] for r in g0]):>6.1f}% of trades")
    print(f"  a TP gapped through    {100 * np.mean([r['gt'] for r in g0]):>6.1f}% per trade (favourable)")

    print(f"\n{'=' * 84}\nEFFECT OF HONEST FILLS (no residual slippage yet)\n{'=' * 84}")
    print(f"{'class':<11}{'k':>4}{'8.37 net':>11}{'gap-aware':>12}{'delta':>9}"
          f"{'stop gap%':>11}")
    by = {}
    for r in g0:
        by.setdefault(r["klass"], []).append(r)
    for c in sorted(by):
        gg = by[c]
        n1 = np.mean([b[r["name"]] for r in gg])
        n2 = np.mean([r["net"] for r in gg])
        print(f"{c:<11}{len(gg):>4}{n1:>11.3f}{n2:>12.3f}{n2 - n1:>9.3f}"
              f"{100 * np.mean([r['gs'] for r in gg]):>10.1f}%")
    n1 = np.mean([b[r["name"]] for r in g0])
    n2 = np.mean([r["net"] for r in g0])
    print("-" * 84)
    print(f"{'UNIVERSE':<11}{len(g0):>4}{n1:>11.3f}{n2:>12.3f}{n2 - n1:>9.3f}")
    print(f"  positive instruments: {sum(1 for r in g0 if r['net'] > 0)} / {len(g0)}")

    print(f"\n{'=' * 84}\nRESIDUAL SLIPPAGE SWEEP (bp beyond the level, entry + stop)\n{'=' * 84}")
    print(f"  {'slip bp':>9}{'net R':>10}{'positive':>12}")
    for s in [0, 0.5, 1, 2, 3, 5, 8]:
        rr = run(float(s))
        print(f"  {s:>9}{np.mean([r['net'] for r in rr]):>10.3f}"
              f"{sum(1 for r in rr if r['net'] > 0):>8} / {len(rr)}")

    (SCRATCH / "gap.pkl").write_bytes(pickle.dumps(g0))


if __name__ == "__main__":
    main()
