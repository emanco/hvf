"""Does gating on Hunt's funnel SHAPE fix the strategy? (spec 8.42)

8.42 established that the detector has been finding the wrong object. Hunt's eight funnels
span a median 68 bars with wave3/wave1 = 0.35 in time and amp3/amp1 = 0.41 in price. Ours
span 430 bars with wave3/wave1 = 0.01 -- a median third wave of ONE bar -- and
amp3/amp1 = 0.06. The MEF rule is ordinal and scale-free, so left unconstrained the
cheapest way to satisfy it is a huge first leg plus a tiny final wiggle.

That single defect accounts for the tight stops, the 56-70x leverage, the financing drag
and a TP3 sitting ~16R away instead of Hunt's ~2.4R. This tests the fix.

THE GATE, fixed before running and not to be adjusted:

    wave3 / wave1  in TIME   within [0.14, 0.55]
    amp3  / amp1   in PRICE  within [0.20, 0.52]

Both are the full range of Hunt's eight, not a percentile of it and not tuned. He states
"low time and price symmetry" as an invalidation criterion (spec 6); the bounds only put a
scale on his own words. The gate is applied to the CONFIRMED six pivots in both arms, so
it can never depend on the provisional pivot.

DESIGN. 2x2: stop {RL3, RL2} x gate {off, on}, forming arm throughout. Including the stop
is not a second bite -- 8.41 already settled it -- but it answers the question the shape
finding raises: with a funnel that is actually a funnel, is Hunt's own tight stop at RL3
fine after all? Shift-null charged to every cell. THIRD universe, first draw. One look.

Four instruments are excluded by name: GOLD, SILVER, WTI and USDJPY are the underlyings of
Hunt's own charts, which is where the gate's bounds came from. Leaving them in would be
testing the filter on its own calibration data.
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
    from hvf_v2_fetch_third import CLASS, THIRD
    from hvf_v2_fetch_universe import OUT
    from hvf_v2_forming import COST_BP, HOURS, HI, LO, MIN_TRADES, NSEED, direction_for
    from hvf_v2_widestop import RATE, picks_for, simulate

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
               "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")

T3_T1 = (0.14, 0.55)
AMP3_AMP1 = (0.20, 0.52)
CALIBRATION = {"GOLD", "SILVER", "WTI", "USDJPY"}


def shape_gate(w):
    h1, rl1, rh2, rl2, rh3, rl3 = w
    t1 = rl1.index - h1.index
    t3 = rl3.index - rh3.index
    a1 = abs(h1.price - rl1.price)
    a3 = abs(rh3.price - rl3.price)
    if t1 <= 0 or a1 <= 0:
        return False
    return (T3_T1[0] <= t3 / t1 <= T3_T1[1]
            and AMP3_AMP1[0] <= a3 / a1 <= AMP3_AMP1[1])


def load_frames():
    frames = {}
    for name in sorted(THIRD):
        if name in CALIBRATION:
            continue
        p = OUT / f"{name}_D1.csv"
        if not p.exists():
            continue
        try:
            df = load_ohlc(str(p))
        except Exception:                                        # noqa: BLE001
            continue
        if df is None or len(df) < 900:
            continue
        fr = resample_ohlc(df, HOURS, 0)
        if len(fr) < 600:
            continue
        d = direction_for(fr)
        if d:
            frames[name] = (fr, d)
    return frames


def net_of(frame, picks, name):
    det = simulate(frame, picks)
    if len(det) < MIN_TRADES:
        return None
    c = CLASS[name]
    net = [x[0] - x[1] * RATE[c] / 100.0 / 365.0 - x[2] * COST_BP[c] * 1e-4
           for x in det]
    return float(np.mean(net)), len(det), float(np.mean([x[2] for x in det]))


def evaluate(frames, stop_at, gated):
    gate = shape_gate if gated else None
    real, null, ntr, levs, rr = [], [], 0, [], []
    for name, (fr, d) in frames.items():
        pk = picks_for(fr, d, "forming", stop_at, gate)
        for p in pk:
            r = abs(p["e_off"] - p["s_off"])
            if r > 0:
                rr.append(abs(p["tps"][2] - p["e_off"]) / r)
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
    return (np.array(real), np.array(null), ntr, np.array(levs),
            float(np.median(rr)) if rr else float("nan"))


def main():
    frames = load_frames()
    n_eff = 15.7 * len(frames) / 79.0
    print("=" * 92)
    print("8.42  SHAPE GATE -- third universe, first draw")
    print("=" * 92)
    print(f"  gate: wave3/wave1 in {T3_T1},  amp3/amp1 in {AMP3_AMP1}")
    print(f"  {len(frames)} instruments (excl. {sorted(CALIBRATION)}), "
          f"N_eff {n_eff:.1f}, {HOURS:.0f}h bars\n")
    print(f"{'stop':<6}{'gate':<6}{'trades':>9}{'lev':>7}{'TP3(R)':>9}"
          f"{'net R':>9}{'t':>7}{'null':>9}{'LIFT':>9}{'t':>7}{'net>0':>9}")
    print("-" * 92)

    res = {}
    for stop_at in ("rl3", "rl2"):
        for gated in (False, True):
            r, u, ntr, levs, tp3 = evaluate(frames, stop_at, gated)
            if len(r) < 2:
                print(f"{stop_at:<6}{'on' if gated else 'off':<6}"
                      f"{ntr:>9,}   too few instruments")
                continue
            L = r - u
            se = L.std(ddof=1) / np.sqrt(n_eff)
            tn = r.mean() / (r.std(ddof=1) / np.sqrt(n_eff))
            print(f"{stop_at.upper():<6}{'on' if gated else 'off':<6}{ntr:>9,}"
                  f"{levs.mean():>6.0f}x{tp3:>9.1f}{r.mean():>9.3f}{tn:>7.2f}"
                  f"{u.mean():>9.3f}{L.mean():>9.3f}{L.mean() / se:>7.2f}"
                  f"{int((r > 0).sum()):>6}/{len(r)}")
            res[(stop_at, gated)] = dict(real=r, null=u, lev=levs, n=ntr, tp3=tp3)
    pickle.dump(res, open(SCRATCH / "shape.pkl", "wb"))


if __name__ == "__main__":
    main()
