"""Guard: the shared rules module must still reproduce the geometry the backtests measured.

`hvf_trader/detector/hvf_rules.py` is now the single definition of HVF geometry, imported by
both the research scripts and the live scanner. Before that it was inlined in
`scripts/hvf_v2_widestop.picks_for`, and every result in spec 8.36-8.47 was produced by that
inlined copy. This script pins the shared module to it.

BASELINE is the last commit before the extraction. It is deliberately a fixed SHA and not
HEAD~1: the point is to compare against the code that generated the published numbers, and
that reference must not drift as more commits land.

Run it after any change to hvf_rules, the zigzag, or mef_candidates. A mismatch means the
live scanner and the backtest have parted company -- treat the backtest figures as void
until it is explained, because the demo account would then be validating something else.

    python scripts/hvf_v2_rules_parity.py
"""
import contextlib
import glob
import io
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BASELINE = "55976d4a2ca49d1e4ed3e5542c6c37d14a26b5fb"
TARGET = "scripts/hvf_v2_widestop.py"


def baseline_picks_for():
    """`picks_for` as it stood at BASELINE, loaded under its own module name."""
    src = subprocess.run(["git", "show", f"{BASELINE}:{TARGET}"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    mod = types.ModuleType("hvf_v2_widestop_baseline")
    mod.__file__ = str(ROOT / TARGET)
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, mod.__file__, "exec"), mod.__dict__)     # noqa: S102
    return mod.picks_for


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc
        from hvf_v2_fetch_universe import OUT
        from hvf_v2_forming import HOURS, direction_for
        from hvf_v2_shape import shape_gate
        from hvf_v2_widestop import picks_for as current
    old = baseline_picks_for()

    files = sorted(glob.glob(str(OUT / "*_D1.csv")))
    if not files:
        print(f"no data under {OUT} -- nothing to compare")
        return 1

    frames = compared = mismatches = 0
    for path in files:
        try:
            df = load_ohlc(path)
        except Exception:                                          # noqa: BLE001
            continue
        if df is None or len(df) < 900:
            continue
        frame = resample_ohlc(df, HOURS, 0)
        if len(frame) < 600:
            continue
        direction = direction_for(frame)
        if not direction:
            continue
        frames += 1
        name = Path(path).stem

        for arm_on in ("confirmed", "forming"):
            for stop_at in ("rl2", "rl3"):
                for gate in (shape_gate, None):
                    a = old(frame, direction, arm_on, stop_at, gate=gate)
                    b = current(frame, direction, arm_on, stop_at, gate=gate)
                    compared += len(a)
                    tag = f"{name} {arm_on}/{stop_at}/{'gated' if gate else 'open'}"
                    if len(a) != len(b):
                        mismatches += 1
                        print(f"  COUNT {tag}: baseline {len(a)}, current {len(b)}")
                        continue
                    for x, y in zip(a, b):
                        if (x["arm"] != y["arm"] or x["d"] != y["d"]
                                or x["wait"] != y["wait"]
                                or abs(x["e_off"] - y["e_off"]) > 1e-9
                                or abs(x["s_off"] - y["s_off"]) > 1e-9
                                or any(abs(u - v) > 1e-9
                                       for u, v in zip(x["tps"], y["tps"]))
                                or [p.index for p in x["w"]] != [p.index for p in y["w"]]):
                            mismatches += 1
                            print(f"  FIELD {tag} at arm {x['arm']}")

    print(f"\nbaseline {BASELINE[:7]}   frames {frames}   picks {compared}   "
          f"mismatches {mismatches}")
    ok = mismatches == 0 and compared > 0
    print("PARITY OK" if ok else "PARITY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
