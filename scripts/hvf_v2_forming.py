"""Does arming on a FORMING funnel fix the fill defect? (spec 8.40)

8.38's killer: 34.1% of picks had the entry already breached at the arming bar, because
a percentage ZigZag cannot confirm RL3 until price has retraced by the box amount, and by
then price has often gone through the entry. The backtest filled those anyway -- buying
below market -- and that impossible fill WAS the measured edge.

Hunt does not wait for confirmation; he posts setups on funnels still forming. This tests
the same thing mechanically.

THE TWO ARMS, and why the comparison is fair. Both take the identical entry price. The
funnel geometry makes entry = RH3 exactly, whatever the stop is:

    C = (RH3 + stop)/2      entry = C + amp3/2 = RH3      independent of `stop`

so the arms differ ONLY in when they arm and therefore what the stop is:

  confirmed  arms at RL3.confirm   stop = RL3            (what 8.36-8.39 measured)
  forming    arms at RH3.confirm   stop = running low to that bar, provisional

PARAMETER-FREE BY CONSTRUCTION. The forming arm arms at the first bar where the entry is
knowable (RH3 confirmed) and requires only what the MEF rule already requires -- the
provisional low must sit between RL2 and RH3. No waiting rule, no contraction threshold,
no minimum risk. If that produces unusable leverage, that is the finding, not something
to patch out: 8.39 established that an unbounded risk denominator manufactures numbers,
so `lev` is reported rather than silently trimmed.

CAUSALITY IS ASSERTED, NOT ASSUMED. A forming arm is exactly where lookahead would hide,
and this programme's record says to expect it. `_assert_causal` checks that every pivot a
pick depends on was CONFIRMED at or before the arming bar, and that the provisional low
scans no bar after it. It raises rather than warns.

Pre-registered before the first run: fresh 72-instrument universe (never used), forming
vs confirmed, paired on the same instruments, shift-null charged to both arms, bar phase
swept as a robustness check and not as a selection. One look.
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
    from hvf_trader.detector.hvf_mef import mef_candidates
    from hvf_trader.detector.hvf_signal import DEFAULT_BOX_PCT, slung_of
    from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc, zigzag_pct
    from hvf_v2_fetch_fresh import FRESH
    from hvf_v2_fetch_universe import OUT
    from hvf_v2_gapfill import simulate_gap

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
               "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")
HOURS = 72.0                 # 3D, as the wide run
WAIT = 20                    # bars allowed for the entry to fill, both arms alike
NSEED, LO, HI = 60, 50, 1500
MIN_TRADES = 15

# Same published-typical table as 8.37, mapped onto the fresh names.
COST_BP = {"fx": 0.8, "index": 1.0, "commodity": 4.0, "etf": 2.0}
RATE = {"fx": 2.0, "index": 5.0, "commodity": 7.0, "etf": 5.0}

_COMMODITY = {"HEATOIL", "GASOLINE", "OATS", "SOYOIL", "SOYMEAL", "LEANHOGS",
              "COCOA", "ORANGEJUICE", "ROUGHRICE", "FEEDER", "ALUMINIUM"}


def klass(name):
    if name.endswith("_ETF"):
        return "etf"
    if name in _COMMODITY:
        return "commodity"
    if len(name) == 6 and name.isalpha() and name.isupper():
        return "fx"
    return "index"


def _assert_causal(piv, idx, arm, prov_scan_end):
    """Every dependency confirmed by `arm`; nothing read from after it."""
    for j in idx:
        p = piv[j]
        if p.confirm < 0 or p.confirm > arm:
            raise AssertionError(
                f"pivot {j} confirms at {p.confirm}, after arming bar {arm}")
    if prov_scan_end > arm:
        raise AssertionError(
            f"provisional low scanned to {prov_scan_end}, after arming bar {arm}")


def picks_for(frame, direction, arm_on):
    """Picks in simulate_gap's format. `arm_on` is 'confirmed' or 'forming'."""
    piv = zigzag_pct(frame, DEFAULT_BOX_PCT)
    if len(piv) < 6:
        return []
    close = frame["close"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    n = len(frame)
    out, seen = [], set()

    for idx in mef_candidates(piv, direction):
        w = [piv[j] for j in idx]
        h1, rl1, rh2, rl2, rh3, rl3 = w
        entry = rh3.price

        if arm_on == "confirmed":
            arm = rl3.confirm
            stop = rl3.price
            scan_end = arm
            dep = idx
        else:
            # The entry is knowable the moment RH3 confirms; the stop is whatever
            # the running extreme has reached by then, and may still extend.
            arm = rh3.confirm
            if arm < 0 or arm >= n:
                continue
            lo_i = rh3.index + 1
            if lo_i > arm:
                continue
            seg = low[lo_i:arm + 1] if direction > 0 else high[lo_i:arm + 1]
            if seg.size == 0:
                continue
            stop = float(seg.min() if direction > 0 else seg.max())
            # The MEF retraction condition, applied to the provisional pivot.
            if direction > 0 and not (rl2.price < stop < entry):
                continue
            if direction < 0 and not (entry < stop < rl2.price):
                continue
            scan_end = arm
            dep = idx[:5]

        if arm < 0 or arm >= n - 1:
            continue
        _assert_causal(piv, dep, arm, scan_end)

        risk = abs(entry - stop)
        if risk <= 0:
            continue
        key = (arm, round(entry, 10), round(stop, 10))
        if key in seen:
            continue
        seen.add(key)

        out.append(dict(
            arm=int(arm), d=direction,
            e_off=entry - close[arm], s_off=stop - close[arm],
            amp=abs(h1.price - rl1.price), amp2=abs(rh2.price - rl2.price),
            wait=WAIT, risk=risk, slung=slung_of(w, direction)))
    return out


def net_of(frame, picks, name):
    det = simulate_gap(frame, picks, HOURS, 0.0)
    if len(det) < MIN_TRADES:
        return None
    c = klass(name)
    net = [x[0] - x[1] * RATE[c] / 100.0 / 365.0 - x[3] * COST_BP[c] * 1e-4
           for x in det]
    return float(np.mean(net)), len(det), float(np.mean([x[3] for x in det]))


def direction_for(frame):
    """Prior trend on the instrument's own multi-year history: up -> long.

    Spec 8.13/8.16: direction follows the trend into the exhaustion point, never the
    funnel's shape. Left to itself the geometry emits 17-50:1 shorts in a bull market.
    """
    c = frame["close"].to_numpy(float)
    if len(c) < 200:
        return 0
    return 1 if c[-1] > c[max(0, len(c) - 500)] else -1


def evaluate(frames, arm_on, with_null=True):
    real, null, ntr, levs = [], [], 0, []
    for name, (fr, d) in frames.items():
        pk = picks_for(fr, d, arm_on)
        r = net_of(fr, pk, name)
        if r is None:
            continue
        real.append(r[0])
        ntr += r[1]
        levs.append(r[2])
        if not with_null:
            null.append(0.0)
            continue
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


def report(tag, real, null, ntr, levs, n_eff):
    L = real - null
    se = L.std(ddof=1) / np.sqrt(n_eff) if len(real) > 1 else np.nan
    tn = real.mean() / (real.std(ddof=1) / np.sqrt(n_eff)) if len(real) > 1 else np.nan
    print(f"\n  {tag}")
    print(f"    instruments {len(real):<4} trades {ntr:,}   mean lev {levs.mean():.0f}x"
          f"  (max {levs.max():.0f}x)")
    print(f"    net R          {real.mean():>7.3f}   (t {tn:>5.2f})")
    print(f"    shift-null     {null.mean():>7.3f}")
    print(f"    LIFT           {L.mean():>7.3f}   (t {L.mean() / se:>5.2f})")
    print(f"    net > 0        {int((real > 0).sum()):>4} / {len(real)}")
    print(f"    lift > 0       {int((L > 0).sum()):>4} / {len(real)}")


def load_frames(phase):
    frames = {}
    for name in sorted(FRESH):
        p = OUT / f"{name}_D1.csv"
        if not p.exists():
            continue
        try:
            df = load_ohlc(str(p))
        except Exception:                                        # noqa: BLE001
            continue
        if df is None or len(df) < 900:
            continue
        fr = resample_ohlc(df, HOURS, phase)
        if len(fr) < 600:
            continue
        d = direction_for(fr)
        if d:
            frames[name] = (fr, d)
    return frames


def main():
    phase = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    frames = load_frames(phase)
    # N_eff scaled from 8.36's measured 15.7 of 79 by instrument count.
    n_eff = 15.7 * len(frames) / 79.0
    print("=" * 78)
    print(f"8.40  FORMING vs CONFIRMED -- fresh universe, bar phase {phase}h")
    print("=" * 78)
    print(f"  {len(frames)} instruments, N_eff {n_eff:.1f}, box {DEFAULT_BOX_PCT}%, "
          f"{HOURS:.0f}h bars")

    res = {}
    for arm_on in ("confirmed", "forming"):
        r, u, ntr, levs = evaluate(frames, arm_on)
        report(f"{arm_on} arm", r, u, ntr, levs, n_eff)
        res[arm_on] = dict(real=r, null=u, n=ntr, lev=levs)
    pickle.dump(res, open(SCRATCH / f"forming_p{phase}.pkl", "wb"))


if __name__ == "__main__":
    main()
