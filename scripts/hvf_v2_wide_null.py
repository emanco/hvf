"""Shift-null over the wide universe (spec 8.36, step 5b).

8.36 step 5 returned +0.125R per instrument at t = 2.21, clearing the bar 8.34
pre-registered. That bar tests the wrong null. `t` here only asks "is the mean
different from zero", and there is an obvious way to score above zero without the
funnel meaning anything: 58 of 80 instruments are positive, indices and metals lead the
table, and the direction gate is trend-following. On an asset that rose for twenty years
the gate says "long" and collects drift. Drift is not edge -- buy-and-hold has it.

The shift-null (8.23) is the control. Keep everything about each trade except **where**
it happens: same direction, same entry and stop offsets from the anchor close, same
target distances, same wait window -- only the anchor bar moves, by a random 50-1500 bars.
If the funnel geometry carries information, the real placement beats its own shuffles. If
we are only harvesting drift, the shuffles score the same, because they are long in the
same rising market.

Detection is the expensive half (~40 min for the universe) and does not depend on the
seed, so picks are detected once, cached, and then re-simulated 200 times.

The bar is pre-registered as the **95th percentile**, exactly as in 8.23 and 8.32.
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
    import hvf_v2_mef_waves as W
    from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc
    from hvf_v2_mef_carry_blind import simulate_detail
    from hvf_v2_wide_run import RATE, klass, universe

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
                "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")
PICKS = SCRATCH / "wide_picks.pkl"
NSEED = 200
LO, HI = 50, 1500          # 8.23's displacement window, unchanged


def mean_net(frame, picks, hours, rate):
    det = simulate_detail(frame, picks, hours, "waves")
    if len(det) < 15:
        return None
    return float(np.mean([x[0] - x[1] * rate / 100.0 / 365.0 for x in det]))


def main():
    store = pickle.loads(PICKS.read_bytes()) if PICKS.exists() else {}

    real, null = {}, {}
    for name, f, hours, df in universe():
        frame = resample_ohlc(df, hours) if hours != 1.0 else df
        if len(frame) < 600:
            continue
        if name not in store:
            c0 = dict(name=name, hours=hours, src=f.stem, ratio=None)
            try:
                store[name] = W.top(W.enumerate_window(c0, W.BOX, frame))
            except Exception as e:                              # noqa: BLE001
                print(f"  {name:<12} FAILED {type(e).__name__}: {e}", flush=True)
                store[name] = []
            PICKS.write_bytes(pickle.dumps(store))
            print(f"  detected {name:<12} {len(store[name]):>4} picks", flush=True)

        picks = store[name]
        if not picks:
            continue
        rate = RATE[klass(name)]
        r = mean_net(frame, picks, hours, rate)
        if r is None:
            continue
        real[name] = r

        rng = np.random.default_rng(abs(hash(name)) % (2 ** 31))
        n = len(frame)
        draws = []
        for _ in range(NSEED):
            shifted = []
            for p in picks:
                q = dict(p)
                step = rng.integers(LO, HI) * (1 if rng.random() < 0.5 else -1)
                q["arm"] = int(np.clip(p["arm"] + step, 0, n - 2))
                shifted.append(q)
            v = mean_net(frame, shifted, hours, rate)
            if v is not None:
                draws.append(v)
        null[name] = draws
        pct = 100.0 * np.mean([r > d for d in draws]) if draws else float("nan")
        print(f"  {name:<12} real {r:>6.3f}   null med "
              f"{np.median(draws):>6.3f}   pct {pct:>5.1f}", flush=True)

    names = sorted(real)
    obs = float(np.mean([real[k] for k in names]))
    # Universe-level null: one draw is the universe mean under seed s. Instruments are
    # shuffled independently, which is the same independence 8.36 step 4 measured, so
    # this understates nothing that N_eff already accounts for.
    k = min(len(null[n_]) for n_ in names)
    uni = [float(np.mean([null[n_][s] for n_ in names])) for s in range(k)]
    pct = 100.0 * float(np.mean([obs > u for u in uni]))

    print(f"\n{'=' * 74}\nWIDE SHIFT-NULL  ({len(names)} instruments, {k} seeds)\n{'=' * 74}")
    print(f"  observed universe mean net      {obs:>8.3f} R")
    print(f"  null mean                       {np.mean(uni):>8.3f} R")
    print(f"  null 95th percentile            {np.percentile(uni, 95):>8.3f} R")
    print(f"  observed percentile             {pct:>8.1f}   (need >= 95)")
    print(f"  instruments beating own 95th    "
          f"{sum(1 for n_ in names if real[n_] > np.percentile(null[n_], 95)):>8} / {len(names)}")

    by = {}
    for n_ in names:
        by.setdefault(klass(n_), []).append(
            (real[n_], float(np.mean(null[n_]))))
    print(f"\n{'class':<12}{'k':>4}{'real':>9}{'null':>9}{'lift':>9}")
    for c in sorted(by):
        r_ = np.mean([x[0] for x in by[c]]); u_ = np.mean([x[1] for x in by[c]])
        print(f"{c:<12}{len(by[c]):>4}{r_:>9.3f}{u_:>9.3f}{r_ - u_:>9.3f}")

    (SCRATCH / "wide_null.pkl").write_bytes(pickle.dumps(dict(real=real, null=null)))


if __name__ == "__main__":
    main()
