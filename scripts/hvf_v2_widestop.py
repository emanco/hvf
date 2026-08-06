"""Is the stop too tight? Widen it to the second funnel and measure. (spec 8.41)

8.40 left the mechanism unambiguous: every fix tried so far TIGHTENED the risk distance
and every one lost, because `cost in R = spread_frac * LEV` and `LEV = |entry| / risk`.
Two measurements on the fresh universe say the stop is the problem:

  * median stop distance is 1.25 ATR, and 33.1% of setups have a stop inside a SINGLE
    bar's range -- taken out by noise before the structure can resolve;
  * the shift-null is -0.38 to -0.47R. The same geometry placed at random times loses
    badly on its own. A structure with a -0.4R random-placement expectancy is broken
    structurally; the funnel only makes it lose less.

THE VARIANT. Stop moves from RL3 (outside the third funnel) to RL2 (outside the second).
Median amp2/amp3 is 3.44x, so leverage should fall ~56x -> ~16x. Targets DO NOT MOVE:
the three-wave projection from the small funnel's centre is validated doctrine -- it
reproduces Hunt's own published levels to 0.02R in hvf_signal_parity -- so widening the
stop must not be allowed to drag the targets out with it. That is why this file carries
its own simulator rather than reusing simulate_gap, whose legs are derived from
`C = (e+st)/2` and would move with the stop.

The cost is RRR: the same target at 3.44x the risk is 3.44x less reward per unit risk.
That is the whole question -- does surviving the noise pay for the smaller multiple?

DESIGN. A 2x2, not a sweep: arming {confirmed, forming} x stop {RL3, RL2}. Two binary
factors with a stated mechanism, decided before running. This is the SECOND draw on the
fresh 72 (8.40 was the first) and it is recorded as such.
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
    from hvf_trader.detector.hvf_rules import find_setups
    from hvf_v2_forming import (
        COST_BP, HOURS, LO, MIN_TRADES, NSEED, RATE, WAIT, HI,
        klass, load_frames,
    )

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
               "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")


def picks_for(frame, direction, arm_on, stop_at, gate=None):
    """Picks carrying EXPLICIT target prices, so the stop can move and they cannot.

    The geometry now lives in `hvf_trader.detector.hvf_rules`, shared with the live
    scanner, so what the demo account trades is what this file measured. This is a thin
    adapter: absolute prices in, offsets-from-the-arming-close out. Parity against the
    version that was inlined here was checked over 18,094 picks on 60 instruments across
    both arming modes and both stops -- zero mismatches.

    `gate` is an optional predicate on the six pivots (spec 8.42's shape filter). It is
    applied to the CONFIRMED window in both arms, so gating never depends on the
    provisional pivot and cannot smuggle in lookahead.
    """
    close = frame["close"].to_numpy(float)
    return [s.as_pick(close[s.arm], WAIT)
            for s in find_setups(frame, direction, arm_on=arm_on, stop_at=stop_at,
                                 gate=gate)]


def simulate(frame, picks, exit_style="thirds"):
    """Gap-aware fills, explicit targets. Mirrors simulate_gap's fill discipline.

    exit_style:
      "thirds"  a third at each of TP1/TP2/TP3, stop to breakeven once TP1 trades.
                What 8.36-8.43 measured.
      "hunt"    no TP1 leg. Half at TP2, stop to breakeven there, the rest runs to
                TP3. This is the rule the trader actually described.

    The breakeven trigger is the NEAREST live leg either way, so it follows the leg
    structure automatically rather than being a second knob.
    """
    op = frame["open"].to_numpy(float)
    hi = frame["high"].to_numpy(float)
    lo = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    day = HOURS / 24.0
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

        fill, e_fill = None, None
        for i in range(arm + 1, min(arm + 1 + s_["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                through = (d > 0 and op[i] > e) or (d < 0 and op[i] < e)
                e_fill = op[i] if through else e
                fill = i
                break
        if fill is None:
            continue

        if exit_style == "hunt":
            legs = [(0.5, close[arm] + s_["tps"][1]), (0.5, close[arm] + s_["tps"][2])]
        else:
            legs = [(1 / 3, close[arm] + t) for t in s_["tps"]]
        legs = [(f, t) for f, t in legs if d * (t - e) > 0]
        if not legs:
            continue
        legs.sort(key=lambda x: d * x[1])
        # NOT renormalised. If a target sits the wrong side of entry its leg is
        # dropped, residual size never exits, and the trade is discarded by the
        # `size > 1e-9` check below. That is the semantics 8.36-8.43 measured, and
        # both exit styles inherit it so the arms stay comparable.
        tp1 = legs[0][1]

        lev = abs(e) / risk
        banked, size, stop, carry = 0.0, 1.0, st, 0.0
        for i in range(fill, n):
            carry += size * lev * day
            if (d > 0 and lo[i] <= stop) or (d < 0 and hi[i] >= stop):
                through = (d > 0 and op[i] < stop) or (d < 0 and op[i] > stop)
                px = op[i] if through else stop
                banked += size * d * (px - e_fill) / risk
                size, free = 0.0, i
                break
            while legs and ((d > 0 and hi[i] >= legs[0][1]) or (d < 0 and lo[i] <= legs[0][1])):
                f, t = legs.pop(0)
                through = (d > 0 and op[i] > t) or (d < 0 and op[i] < t)
                px = op[i] if through else t
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
        # `arm` is carried so callers can date a trade: this loop skips picks that
        # overlap an open position, so the output is NOT aligned with `picks`.
        # `d` is carried because real swap is direction-dependent -- IC Markets pays
        # +3.3%/yr to hold gold short and charges -4.8%/yr to hold it long (8.45).
        # Callers that index x[0..2] only are unaffected.
        out.append((banked, carry, lev, arm, d))
    return out


def net_of(frame, picks, name):
    det = simulate(frame, picks)
    if len(det) < MIN_TRADES:
        return None
    c = klass(name)
    net = [x[0] - x[1] * RATE[c] / 100.0 / 365.0 - x[2] * COST_BP[c] * 1e-4
           for x in det]
    return float(np.mean(net)), len(det), float(np.mean([x[2] for x in det]))


def evaluate(frames, arm_on, stop_at):
    real, null, ntr, levs = [], [], 0, []
    for name, (fr, d) in frames.items():
        pk = picks_for(fr, d, arm_on, stop_at)
        r = net_of(fr, pk, name)
        if r is None:
            continue
        real.append(r[0])
        ntr += r[1]
        levs.append(r[2])
        rng = np.random.default_rng(abs(hash(name)) % (2 ** 31))
        n, dr = len(fr), []
        for _ in range(NSEED):
            sh = []
            for p in pk:
                q = dict(p)
                stp = rng.integers(LO, HI) * (1 if rng.random() < 0.5 else -1)
                q["arm"] = int(np.clip(p["arm"] + stp, 0, n - 2))
                sh.append(q)
            v = net_of(fr, sh, name)
            if v is not None:
                dr.append(v[0])
        null.append(float(np.mean(dr)) if dr else 0.0)
    return np.array(real), np.array(null), ntr, np.array(levs)


def main():
    frames = load_frames(0)
    n_eff = 15.7 * len(frames) / 79.0
    print("=" * 84)
    print("8.41  WIDE STOP -- targets held at the three-wave geometry, stop moved out")
    print("=" * 84)
    print(f"  {len(frames)} instruments (fresh, draw 2), N_eff {n_eff:.1f}\n")
    print(f"{'arm':<11}{'stop':<7}{'trades':>9}{'lev':>7}{'net R':>9}{'t':>7}"
          f"{'null':>9}{'LIFT':>9}{'t':>7}{'net>0':>8}")
    print("-" * 84)

    res = {}
    for arm_on in ("confirmed", "forming"):
        for stop_at in ("rl3", "rl2"):
            r, u, ntr, levs = evaluate(frames, arm_on, stop_at)
            if len(r) < 2:
                print(f"{arm_on:<11}{stop_at:<7}  too few instruments")
                continue
            L = r - u
            se = L.std(ddof=1) / np.sqrt(n_eff)
            tn = r.mean() / (r.std(ddof=1) / np.sqrt(n_eff))
            print(f"{arm_on:<11}{stop_at:<7}{ntr:>9,}{levs.mean():>6.0f}x"
                  f"{r.mean():>9.3f}{tn:>7.2f}{u.mean():>9.3f}"
                  f"{L.mean():>9.3f}{L.mean() / se:>7.2f}"
                  f"{int((r > 0).sum()):>5}/{len(r)}")
            res[(arm_on, stop_at)] = dict(real=r, null=u, lev=levs, n=ntr)
    pickle.dump(res, open(SCRATCH / "widestop.pkl", "wb"))


if __name__ == "__main__":
    main()
