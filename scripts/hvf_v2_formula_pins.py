"""Pin `hvf_trader.detector.hvf_v2`'s arithmetic to Hunt's own panel output.

This is the cheap half of the acceptance test and it runs on no market data at
all: for each of the 14 transcribed charts we know the printed fib coordinates,
entry, stop, target and RRR, so the anchors can be solved and the module's
formulas checked against the numbers the tool itself displayed.

If this fails, nothing downstream is worth running. It is deliberately separate
from the data-driven test so that a failure there can be attributed — a wrong
formula and a missing structure look identical when they are checked together.

Transcription provenance: two independent passes over the screenshots. Where
they disagreed the blind pass won, and each of those three corrections
strengthened the fit rather than weakening it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    project_target, select_projection,
)

BAR = "-" * 92

# name, tf, tf_hours, dir, slung, proj, RH2, RL2, RH3, RL3, RRR, entry, stop, target
PANEL = [
    ("USDKRW",  "2h",    2, +1, 0.47, "lin", 0.86, 0.12, 0.57, 0.38, 4.76, 1484.28, 1474.62, 1530.30),
    ("USDKRW",  "1M",  730, +1, 0.45, "log", 0.73, 0.11, 0.57, 0.33, 5.64, 1445.80, 1216.40, 2740.15),
    ("BTCUSD",  "1h",    1, +1, 0.39, "lin", 0.84, 0.08, 0.65, 0.14, 1.45, 70805.0, 69376.0, 72875.0),
    ("AU10Y",   "1W",  168, +1, 0.46, "log", 0.77, 0.22, 0.66, 0.27, 2.41,   4.583,   4.096,   5.756),
    ("US20Y",   "1W",  168, +1, 0.53, "log", 0.84, 0.37, 0.66, 0.40, 4.02,   4.908,   4.536,   6.402),
    ("XAUEUR",  "1h",    1, -1, 0.38, "lin", 0.82, 0.09, 0.63, 0.12, 1.43, 3990.733, 4032.228, 3931.239),
    ("XAU/XAG", "8h",    8, +1, 0.38, "lin", 0.77, 0.18, 0.47, 0.28, 4.75,  63.759,  60.543,  79.038),
    ("US30Y",   "3D",   72, +1, 0.68, "log", 0.98, 0.49, 0.82, 0.55, 3.99,   4.948,   4.599,   6.339),
    ("US5Y",    "3D",   72, +1, 0.37, "log", 0.77, 0.06, 0.47, 0.27, 5.27,   4.147,   3.817,   5.887),
    ("GoldCFD", "2h",    2, +1, 0.44, "lin", 0.78, 0.12, 0.69, 0.19, 1.48, 4349.762, 4317.250, 4397.746),
    ("WTI",     "18h",  18, -1, 0.49, "lin", 0.84, 0.05, 0.70, 0.29, 1.97,   88.66,  105.21,   56.04),
    ("HYG",     "4h",    4, -1, 0.54, "lin", 0.82, 0.30, 0.73, 0.36, 2.23,   79.36,   80.16,   77.56),
    ("USDJPY",  "4h",    4, +1, 0.66, "lin", 0.94, 0.34, 0.85, 0.47, 2.16, 162.482, 161.599, 164.394),
    ("USDJPY",  "1W",  168, +1, 0.39, "log", 0.86, 0.01, 0.51, 0.26, 3.87, 150.918, 145.483, 171.353),
]
COLS = "name tf tf_hours dir slung proj rh2 rl2 rh3 rl3 rrr entry stop target".split()
ROWS = [dict(zip(COLS, r)) for r in PANEL]

# USDJPY 1W's stop is not legible on its screenshot and was held out of the
# original 13-chart validation for that reason. The two transcription passes
# read 143.483 and 145.483; both appear as axis tags. Neither satisfies the
# printed RRR, which implies 145.638 -- so the true value is a third number
# that was never read, and the disagreement is a legibility failure rather
# than a transcription error to adjudicate.
#
# It is therefore excluded from the RRR pin specifically. It is KEPT in the
# slung and projection pins, which do not depend on the stop at all. It is
# also kept in the target pin, where the assumed 145.483 fits to 0.008% --
# noted, but not treated as confirmation, since a wrong stop that happens to
# fit one formula is exactly what a coincidence looks like.
STOP_NOT_LEGIBLE = {("USDJPY", "1W")}


def solve_anchors(r):
    """Recover (a, b) from the printed levels.

    Entry sits at RH3 and stop at RL3 for a long, mirrored for a short, so the
    price distance between them divides by the fib distance to give the range.
    """
    span = abs(r["entry"] - r["stop"]) / (r["rh3"] - r["rl3"])
    a = (r["stop"] - r["rl3"] * span) if r["dir"] > 0 else (r["entry"] - r["rl3"] * span)
    return a, a + span


fails = []

print(BAR)
print("1. SLUNG = (fib(RH3) + fib(RL3)) / 2      [spec 2.1]")
print(BAR)
print(f"{'chart':<14}{'printed':>9}{'computed':>10}{'resid':>9}")
for r in ROWS:
    got = (r["rh3"] + r["rl3"]) / 2
    resid = got - r["slung"]
    # The panel prints 2dp, so +/-0.005 is the tightest the evidence permits.
    ok = abs(resid) <= 0.0051
    fails.append(("slung", r["name"], resid)) if not ok else None
    print(f"{r['name']+' '+r['tf']:<14}{r['slung']:>9.2f}{got:>10.3f}{resid:>9.4f}"
          f"{'' if ok else '   <-- FAIL'}")

print()
print(BAR)
print("2. PROJECTION MODE from bar period      [spec 2.6]")
print(BAR)
for r in ROWS:
    got = select_projection(r["tf_hours"])
    ok = got == r["proj"]
    fails.append(("proj", r["name"], got)) if not ok else None
    print(f"  {r['name']+' '+r['tf']:<14}{r['tf_hours']:>5}h  flag {r['proj']}  "
          f"selected {got}  {'ok' if ok else '<-- FAIL'}")

print()
print(BAR)
print("3. TARGET = AMP1 displacement from the final-contraction midpoint   [spec 2.5]")
print(BAR)
print(f"{'chart':<14}{'proj':>5}{'printed':>12}{'computed':>12}{'err %':>9}")
errs = {"lin": [], "log": []}
for r in ROWS:
    a, b = solve_anchors(r)
    mid = a + r["slung"] * (b - a)
    got = project_target(mid, a, b, r["dir"], r["proj"])
    err = 100.0 * (got - r["target"]) / r["target"]
    errs[r["proj"]].append(abs(err))
    print(f"{r['name']+' '+r['tf']:<14}{r['proj']:>5}{r['target']:>12.3f}{got:>12.3f}{err:>9.3f}")
for mode in ("lin", "log"):
    e = errs[mode]
    print(f"\n  {mode}: n={len(e)}  mean |err| {sum(e)/len(e):.3f}%  max {max(e):.3f}%")
# Spec 2.5 records 0.106% mean (lin) and 0.347% (log). Allow headroom for the
# 2dp fib rounding that propagates into the solved anchors, but not much.
for mode, bound in (("lin", 0.60), ("log", 0.80)):
    if max(errs[mode]) > bound:
        fails.append(("target", mode, max(errs[mode])))

print()
print(BAR)
print("4. RRR = |target - entry| / |entry - stop|      [spec 2.4]")
print(BAR)
print(f"{'chart':<14}{'printed':>9}{'computed':>10}{'resid':>9}")
n_rrr = 0
for r in ROWS:
    if (r["name"], r["tf"]) in STOP_NOT_LEGIBLE:
        implied = r["entry"] - abs(r["target"] - r["entry"]) / r["rrr"]
        print(f"{r['name']+' '+r['tf']:<14}{'--':>9}{'--':>10}{'--':>9}"
              f"   EXCLUDED: stop not legible (panel RRR implies {implied:.3f},"
              f" transcribed {r['stop']:.3f})")
        continue
    n_rrr += 1
    got = abs(r["target"] - r["entry"]) / abs(r["entry"] - r["stop"])
    resid = got - r["rrr"]
    ok = abs(resid) <= 0.021
    fails.append(("rrr", r["name"], resid)) if not ok else None
    print(f"{r['name']+' '+r['tf']:<14}{r['rrr']:>9.2f}{got:>10.4f}{resid:>9.4f}"
          f"{'' if ok else '   <-- FAIL'}")
print(f"\n  {n_rrr}/{len(ROWS)} charts pinned; "
      f"{len(ROWS) - n_rrr} excluded for illegible stops.")

print()
print(BAR)
if fails:
    print(f"FAILED {len(fails)} pin(s):")
    for f in fails:
        print(f"   {f}")
    sys.exit(1)
print("ALL FORMULA PINS PASS")
