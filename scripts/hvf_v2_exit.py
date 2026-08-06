"""Hunt's actual exit rule: no TP1 leg, half at TP2, breakeven, the rest to TP3. (8.44)

8.43 left one pre-specified idea. The exit measured through 8.36-8.43 banks a third at TP1
and moves the stop to breakeven there -- but TP1 is pinned at half the small funnel, so
after 8.41's wider stop it sits near 0.3R against a 2R structure. It caps the runner at
about 0.1R of realised gain while leaving the full downside open until it triggers. That
exit was built for a geometry that no longer exists.

Three exits are measured, all on the same gated RL2 picks so they are exactly paired:

  thirds   a third at each of TP1/TP2/TP3, breakeven once TP1 trades.   [8.43 baseline]
  hunt     no TP1 leg. Half at TP2, breakeven there, half runs to TP3.  [scale-out]
  split    TWO independent positions on the same entry and stop -- one whose only target
           is TP2, one whose only target is TP3 and whose stop goes to breakeven when TP2
           trades. Each is its own trade, with its own R, its own holding time and its
           OWN SPREAD CHARGE.

`split` and `hunt` have the same mean R per trade by construction when the legs are equal
weight -- (X+Y)/2 either way -- so this is not a third hypothesis. It is the same rule
under bookkeeping that separates the two targets, which is what makes the interesting
number visible: whether TP3 pays for itself at all, or whether the runner is dead weight
that the scale-out was hiding inside an average. The cost is honest and not free: two
positions pay the spread twice.

Pre-registered before running. PRIMARY comparison: `hunt` vs `thirds`, gated, RL2 stop,
third universe. Verdict declared in advance per 8.43 -- if this does not clear zero net,
the answer is no. `split` is reported as diagnostics on the same trades, not as a fourth
shot at a positive number. SECOND draw on the third universe.
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
    from hvf_v2_forming import COST_BP, HOURS, HI, LO, MIN_TRADES, NSEED
    from hvf_v2_shape import CLASS, load_frames, shape_gate
    from hvf_v2_widestop import RATE, picks_for, simulate

SCRATCH = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
               "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")


def simulate_single(frame, picks, target_idx, be_at=None):
    """One position, one target. `be_at` is a target index that moves the stop to entry.

    This is the `split` arm: the whole position exits at `tps[target_idx]` or at the
    stop. Overlap suppression runs per pass, so a long-held TP3 position blocks more
    subsequent setups than a quick TP2 one -- which is the real consequence of holding
    a runner and should not be papered over.
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
        tgt = close[arm] + s_["tps"][target_idx]
        if d * (tgt - e) <= 0:
            continue
        be = close[arm] + s_["tps"][be_at] if be_at is not None else None

        fill, e_fill = None, None
        for i in range(arm + 1, min(arm + 1 + s_["wait"], n)):
            if (d > 0 and hi[i] >= e) or (d < 0 and lo[i] <= e):
                through = (d > 0 and op[i] > e) or (d < 0 and op[i] < e)
                e_fill = op[i] if through else e
                fill = i
                break
        if fill is None:
            continue

        lev = abs(e) / risk
        stop, carry, done, won = st, 0.0, False, 0
        for i in range(fill, n):
            carry += lev * day
            if (d > 0 and lo[i] <= stop) or (d < 0 and hi[i] >= stop):
                through = (d > 0 and op[i] < stop) or (d < 0 and op[i] > stop)
                px = op[i] if through else stop
                banked = d * (px - e_fill) / risk
                done, free = True, i
                break
            if (d > 0 and hi[i] >= tgt) or (d < 0 and lo[i] <= tgt):
                through = (d > 0 and op[i] > tgt) or (d < 0 and op[i] < tgt)
                px = op[i] if through else tgt
                banked = d * (px - e_fill) / risk
                done, free, won = True, i, 1
                break
            if be is not None and stop != e and (
                    (d > 0 and hi[i] >= be) or (d < 0 and lo[i] <= be)):
                stop = e
        if not done:
            continue
        out.append((banked, carry, lev, won))
    return out


def cost(det, name):
    c = CLASS[name]
    return [x[0] - x[1] * RATE[c] / 100.0 / 365.0 - x[2] * COST_BP[c] * 1e-4
            for x in det]


def run(frames, mode):
    """Returns per-instrument mean net, plus pooled trades / leverage / hit rate."""
    real, ntr, levs, wins = [], 0, [], []
    per_inst = {}
    for name, (fr, d) in frames.items():
        pk = picks_for(fr, d, "forming", "rl2", shape_gate)
        if mode in ("thirds", "hunt"):
            det = simulate(fr, pk, mode)
            won = [np.nan] * len(det)
        elif mode == "tp2":
            det = simulate_single(fr, pk, 1)
            won = [x[3] for x in det]
        elif mode == "tp3":
            det = simulate_single(fr, pk, 2, be_at=1)
            won = [x[3] for x in det]
        if len(det) < MIN_TRADES:
            continue
        net = cost(det, name)
        real.append(float(np.mean(net)))
        per_inst[name] = (pk, float(np.mean(net)))
        ntr += len(det)
        levs.append(float(np.mean([x[2] for x in det])))
        wins += [w for w in won if w == w]
    return np.array(real), ntr, np.array(levs), wins, per_inst


def shift_null(frames, mode):
    out = []
    for name, (fr, d) in frames.items():
        pk = picks_for(fr, d, "forming", "rl2", shape_gate)
        if len(pk) < MIN_TRADES:
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
            if mode in ("thirds", "hunt"):
                det = simulate(fr, sh, mode)
            else:
                det = simulate_single(fr, sh, 1 if mode == "tp2" else 2,
                                      be_at=None if mode == "tp2" else 1)
            if len(det) >= MIN_TRADES:
                dr.append(float(np.mean(cost(det, name))))
        if dr:
            out.append(float(np.mean(dr)))
    return np.array(out)


def main():
    frames = load_frames()
    n_eff = 15.7 * len(frames) / 79.0
    print("=" * 94)
    print("8.44  EXIT RULE -- gated, RL2 stop, third universe (second draw)")
    print("=" * 94)
    print(f"  {len(frames)} instruments, N_eff {n_eff:.1f}\n")
    print(f"{'exit':<26}{'trades':>8}{'lev':>7}{'hit':>7}{'net R':>9}{'t':>7}"
          f"{'null':>9}{'LIFT':>9}{'t':>7}{'net>0':>9}")
    print("-" * 94)

    res = {}
    rows = [("thirds", "thirds  (8.43 baseline)"),
            ("hunt", "hunt  half TP2 / run TP3"),
            ("tp2", "  split: TP2 only"),
            ("tp3", "  split: TP3 only (BE@TP2)")]
    for mode, label in rows:
        r, ntr, levs, wins, _ = run(frames, mode)
        if len(r) < 2:
            print(f"{label:<26}{ntr:>8,}   too few instruments")
            continue
        u = shift_null(frames, mode)
        m = min(len(r), len(u))
        L = r[:m] - u[:m]
        se = L.std(ddof=1) / np.sqrt(n_eff)
        tn = r.mean() / (r.std(ddof=1) / np.sqrt(n_eff))
        hit = f"{100 * np.mean(wins):.0f}%" if wins else "  -"
        print(f"{label:<26}{ntr:>8,}{levs.mean():>6.0f}x{hit:>7}"
              f"{r.mean():>9.3f}{tn:>7.2f}{u.mean():>9.3f}"
              f"{L.mean():>9.3f}{L.mean() / se:>7.2f}"
              f"{int((r > 0).sum()):>6}/{len(r)}")
        res[mode] = dict(real=r, null=u, lev=levs, n=ntr, wins=wins)

    if "tp2" in res and "tp3" in res:
        a, b = res["tp2"]["real"], res["tp3"]["real"]
        m = min(len(a), len(b))
        comb = (a[:m] + b[:m]) / 2.0
        t = comb.mean() / (comb.std(ddof=1) / np.sqrt(n_eff))
        print("-" * 94)
        print(f"{'  split: both legs':<26}{res['tp2']['n'] + res['tp3']['n']:>8,}"
              f"{'':>6} {'':>7}{comb.mean():>9.3f}{t:>7.2f}")
    pickle.dump(res, open(SCRATCH / "exit.pkl", "wb"))


if __name__ == "__main__":
    main()
