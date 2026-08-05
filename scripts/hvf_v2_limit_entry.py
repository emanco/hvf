"""Limit entry at the funnel centre: the one principled fix (spec 8.39).

8.38 killed the breakout entry and diagnosed exactly why. Of the four fills in a trade,
three are limits and one is a stop, and only the stop is adversely selected:

    take-profits (limit)   gaps pay you        +0.054R
    breakout entry (stop)  gaps cost you       -0.251R

A stop order can only ever be gapped *through*; a limit order is either filled at your
price or better. The entry is the sole gap-exposed leg in the trade and it is the leg that
loses the money.

**The fix is structural, not fitted.** The original entry sits at `C + d*risk/2` -- half a
funnel above the anchor close, which 8.38 showed is inside one bar's opening move at every
timeframe. Entering at `C` instead:

* is where the three waves project from anyway (8.31's geometry, and Hunt's own
  description of the pattern),
* is **reachable by construction**, so ZigZag confirmation lag stops mattering and the
  34.1% of picks that 8.38a found unexecutable become tradeable rather than discarded,
* and, measured on the data, `C - close[arm]` has a median of -0.01*risk -- **C is the
  anchor close**. So "limit at C" is simply "take the trade when the funnel completes",
  the simplest executable entry there is.

Filling is strictly causal: the pattern is known at the close of `arm`, so the fill is the
**open of arm+1**. That still carries gap risk, but symmetric gap risk -- as likely to help
as hurt -- rather than the adversely-selected kind a stop order collects.

Everything else is untouched. Stop stays at the 6th pivot, targets stay projected from C
at the three wave amplitudes, financing and spread as 8.33/8.37. Risk halves (entry moves
from C+risk/2 to C), so leverage doubles and costs in R double -- that is a real penalty
and it is charged, not waved away.

**Discipline.** A third of the universe is held out on a fixed seed *before this file was
run*. The variant is chosen on the other two thirds and validated once. Only two arms are
compared -- the new entry and the old one as control -- because a sweep over entry
variants against 79 instruments is precisely how 8.20's rank and 8.26's exit rules died.
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
    from hvf_v2_spread import COST_BP
    from hvf_v2_wide_run import RATE, klass, universe

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
                "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")
HOLDOUT_SEED = 20260805          # fixed before the first run; never changed
HOLDOUT_FRAC = 1 / 3
NSEED, LO, HI = 60, 50, 1500


def simulate(frame, picks, hours, entry="centre", slip_bp=0.0):
    """Honest fills throughout. `entry` is 'centre' (new) or 'breakout' (8.38 control)."""
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
        e0, st = close[arm] + s_["e_off"], close[arm] + s_["s_off"]
        risk0 = abs(e0 - st)
        if risk0 <= 0:
            continue
        C = (e0 + st) / 2.0

        if entry == "breakout":
            fill, e_fill, e_plan = None, None, e0
            for i in range(arm + 1, min(arm + 1 + s_["wait"], n)):
                if (d > 0 and hi[i] >= e0) or (d < 0 and lo[i] <= e0):
                    through = (d > 0 and op[i] > e0) or (d < 0 and op[i] < e0)
                    e_fill = op[i] if through else e0
                    fill = i
                    break
            if fill is None:
                continue
        else:
            # Known at the close of `arm`; the first tradeable price is the next open.
            fill, e_fill, e_plan = arm + 1, op[arm + 1], C

        e_fill += d * abs(e_fill) * slip_bp * 1e-4
        # Size on the PLANNED geometry, never on the realised fill -- identically to the
        # breakout arm. Sizing on |fill - stop| lets risk go to zero when the open lands
        # near the stop, and leverage diverges (the null blew up to 7e8 that way, the same
        # defect as BTCUSD's in 8.36a). A bad fill must cost more than 1R, not resize.
        risk = abs(e_plan - st)
        if risk <= 0 or (d > 0 and e_fill <= st) or (d < 0 and e_fill >= st):
            continue

        legs = [(1 / 3, C + d * risk0), (1 / 3, C + d * s_["amp2"]), (1 / 3, C + d * s_["amp"])]
        legs = [(f, t) for f, t in legs if d * (t - e_fill) > 0]
        if not legs:
            continue
        legs.sort(key=lambda x: d * x[1])
        tp1 = legs[0][1]

        lev = abs(e_fill) / risk
        banked, size, stop, carry = 0.0, 1.0, st, 0.0
        for i in range(fill, n):
            carry += size * lev * day
            if (d > 0 and lo[i] <= stop) or (d < 0 and hi[i] >= stop):
                through = (d > 0 and op[i] < stop) or (d < 0 and op[i] > stop)
                px = op[i] if (through and i > fill) else stop
                px -= d * abs(px) * slip_bp * 1e-4
                banked += size * d * (px - e_fill) / risk
                size, free = 0.0, i
                break
            while legs and ((d > 0 and hi[i] >= legs[0][1]) or (d < 0 and lo[i] <= legs[0][1])):
                f, t = legs.pop(0)
                through = (d > 0 and op[i] > t) or (d < 0 and op[i] < t)
                px = op[i] if (through and i > fill) else t
                take = min(f, size)
                banked += take * d * (px - e_fill) / risk
                size -= take
            if stop != e_fill and ((d > 0 and hi[i] >= tp1) or (d < 0 and lo[i] <= tp1)):
                stop = e_fill
            if size <= 1e-9:
                free = i
                break
        if size > 1e-9:
            continue
        out.append((banked, carry, (i - fill + 1) * day, lev))
    return out


def net_of(frame, picks, hours, name, entry):
    det = simulate(frame, picks, hours, entry)
    if len(det) < 15:
        return None
    rate, bp = RATE[klass(name)], COST_BP[klass(name)]
    return float(np.mean([x[0] - x[1] * rate / 100.0 / 365.0 - x[3] * bp * 1e-4
                          for x in det])), len(det), float(np.mean([x[3] for x in det]))


def evaluate(frames, picks_all, subset, entry, with_null=True):
    real, null, ntr = [], [], 0
    for name in subset:
        fr, hours = frames[name]
        r = net_of(fr, picks_all[name], hours, name, entry)
        if r is None:
            continue
        real.append(r[0])
        ntr += r[1]
        if not with_null:
            null.append(0.0)
            continue
        rng = np.random.default_rng(abs(hash(name)) % (2 ** 31))
        n, dr = len(fr), []
        for _ in range(NSEED):
            sh = []
            for p in picks_all[name]:
                q = dict(p)
                stp = rng.integers(LO, HI) * (1 if rng.random() < 0.5 else -1)
                q["arm"] = int(np.clip(p["arm"] + stp, 0, n - 2))
                sh.append(q)
            v = net_of(fr, sh, hours, name, entry)
            if v is not None:
                dr.append(v[0])
        null.append(float(np.mean(dr)) if dr else 0.0)
    return np.array(real), np.array(null), ntr


def report(tag, real, null, ntr, k_total):
    L = real - null
    ne = 15.7 * len(real) / k_total
    se = L.std(ddof=1) / np.sqrt(ne) if len(real) > 1 else np.nan
    t_net = real.mean() / (real.std(ddof=1) / np.sqrt(ne)) if len(real) > 1 else np.nan
    print(f"\n  {tag}")
    print(f"    instruments {len(real):<4} trades {ntr:,}")
    print(f"    net R            {real.mean():>7.3f}   (t {t_net:>5.2f})")
    print(f"    shift-null       {null.mean():>7.3f}")
    print(f"    LIFT             {L.mean():>7.3f}   (t {L.mean() / se:>5.2f})")
    print(f"    net > 0          {int((real > 0).sum()):>4} / {len(real)}")
    print(f"    lift > 0         {int((L > 0).sum()):>4} / {len(real)}")
    return real.mean(), t_net, L.mean(), L.mean() / se


def main():
    picks_all = pickle.loads((SCRATCH / "wide_picks.pkl").read_bytes())
    frames = {}
    for name, f, hours, df in universe():
        if name not in picks_all or not picks_all[name] or name == "BTCUSD":
            continue
        fr = resample_ohlc(df, hours) if hours != 1.0 else df
        if len(fr) >= 600:
            frames[name] = (fr, hours)

    names = sorted(frames)
    rng = np.random.default_rng(HOLDOUT_SEED)
    idx = rng.permutation(len(names))
    n_hold = int(round(len(names) * HOLDOUT_FRAC))
    hold = sorted(names[i] for i in idx[:n_hold])
    train = sorted(names[i] for i in idx[n_hold:])

    print(f"{'=' * 78}\n8.39  PRE-REGISTERED SPLIT (seed {HOLDOUT_SEED})\n{'=' * 78}")
    print(f"  train {len(train)} instruments, HELD OUT {len(hold)}")
    print(f"  held out: {', '.join(hold)}")

    print(f"\n{'=' * 78}\nTRAIN ONLY -- choose here, and only here\n{'=' * 78}")
    for entry in ("breakout", "centre"):
        r, u, n_ = evaluate(frames, picks_all, train, entry)
        report(f"{entry} entry", r, u, n_, len(names))

    print(f"\n{'=' * 78}\nHELD OUT -- one look, no going back\n{'=' * 78}")
    out = {}
    for entry in ("breakout", "centre"):
        r, u, n_ = evaluate(frames, picks_all, hold, entry)
        out[entry] = report(f"{entry} entry", r, u, n_, len(names))

    print(f"\n{'=' * 78}\nFULL UNIVERSE (reported for completeness, not for deciding)\n{'=' * 78}")
    for entry in ("breakout", "centre"):
        r, u, n_ = evaluate(frames, picks_all, names, entry)
        report(f"{entry} entry", r, u, n_, len(names))
        if entry == "centre":
            pickle.dump(dict(real=r, null=u), open(SCRATCH / "centre.pkl", "wb"))


if __name__ == "__main__":
    main()
