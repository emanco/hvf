"""How big a backtest would actually settle this? (spec 8.34)

Everything from 8.22 to 8.33 is already a backtest. The question is not whether to run
another one on the same six charts -- that adds no information and is exactly how the
previous implementation ended up tuning MIN_RRR on eighteen trades. The question is how
many INDEPENDENT draws it takes to separate the blind net edge from zero.

So: measure the trade-level dispersion, then invert the standard power formula for how
many trades, and therefore how many instruments, are needed.

Two corrections applied to the naive number:

1. HVF trades overlap and cluster in regime, so they are not independent. The effective
   sample is estimated from the between-chart variance of the per-chart means against
   the within-chart variance -- a design-effect style inflation factor.
2. The effect being detected is the NET edge after financing (8.33), not the gross.
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

with contextlib.redirect_stdout(io.StringIO()):
    import hvf_v2_mef_waves as W
    from hvf_v2_charts import CHARTS
    from hvf_v2_mef import load_frame
    from hvf_v2_mef_rank import offsets_for
    from hvf_v2_mef_carry_blind import RATES, simulate_detail

ALPHA, POWER = 1.645, 1.282          # one-sided 95%, 90% power

if __name__ == "__main__":
    per = {}
    for nm in W.WANT:
        c0 = next(c for c in CHARTS if c["name"] == nm)
        c, offs = offsets_for(c0)
        full = load_frame(c, offs[0] if offs[0] is not None else None)
        lo_ = pd.Timestamp(W.START[nm], tz="UTC")
        frame = full[(full["dt"] >= lo_) & (full["dt"] < W.CUT)].reset_index(drop=True)
        picks = W.top(W.enumerate_window(c0, W.BOX, frame))
        rate = RATES[nm][1]
        for mode in ("legacy", "waves"):
            det = simulate_detail(frame, picks, c0["hours"], mode)
            net = np.array([x[0] - x[1] * rate / 100.0 / 365.0 for x in det])
            per.setdefault(mode, {})[nm] = net

    print(f"{'':<14}{'LEGACY':>28}{'WAVES':>28}")
    print(f"{'chart':<14}{'n':>7}{'net R':>10}{'sd':>11}{'n':>7}{'net R':>10}{'sd':>11}")
    print("-" * 70)
    for nm in W.WANT:
        row = f"{nm:<14}"
        for mode in ("legacy", "waves"):
            a = per[mode][nm]
            row += f"{len(a):>7}{a.mean():>10.2f}{a.std(ddof=1):>11.2f}"
        print(row)
    print("-" * 70)

    for mode in ("legacy", "waves"):
        alln = np.concatenate([per[mode][nm] for nm in W.WANT])
        eff, sd, k = alln.mean(), alln.std(ddof=1), len(W.WANT)
        # Design effect: how much the per-chart means scatter relative to what
        # independent sampling within a chart would predict.
        means = np.array([per[mode][nm].mean() for nm in W.WANT])
        ns = np.array([len(per[mode][nm]) for nm in W.WANT], float)
        between = means.var(ddof=1)
        within = np.average([per[mode][nm].var(ddof=1) for nm in W.WANT], weights=ns)
        deff = max(1.0, between / (within / ns.mean()))
        need = ((ALPHA + POWER) * sd / eff) ** 2 if eff > 0 else np.inf
        print(f"\n{mode.upper()}")
        print(f"  pooled net edge      {eff:>8.3f} R over {len(alln)} trades")
        print(f"  trade-level sd       {sd:>8.3f} R")
        print(f"  observed t-stat      {eff / (sd / np.sqrt(len(alln))):>8.2f}"
              "   (need ~1.65)")
        print(f"  design effect        {deff:>8.2f}   (trades are not independent)")
        print(f"  trades needed        {need:>8.0f} naive, "
              f"{need * deff:>7.0f} corrected")
        print(f"  trades per chart     {len(alln) / k:>8.0f}")
        print(f"  => INSTRUMENTS       {need * deff / (len(alln) / k):>8.0f}"
              f"   (have {k})")
