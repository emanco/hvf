"""Does the 8.36a lift survive cost? Cost must be charged to the shuffles too."""
import contextlib, io, pickle, sys
from pathlib import Path
import numpy as np
ROOT = Path("/Users/manu/Dev/hvf")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"scripts"))
with contextlib.redirect_stdout(io.StringIO()):
    from hvf_trader.detector.hvf_v2 import resample_ohlc
    from hvf_v2_mef_carry_blind import simulate_detail
    from hvf_v2_wide_run import RATE, klass, universe
    from hvf_v2_spread import COST_BP
S = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")
picks_all = pickle.loads((S/"wide_picks.pkl").read_bytes())
NSEED, LO, HI = 100, 50, 1500

def net_with_cost(frame, picks, hours, rate, bp):
    det = simulate_detail(frame, picks, hours, "waves")
    if len(det) < 15: return None
    return float(np.mean([x[0] - x[1]*rate/100.0/365.0 - x[3]*bp*1e-4 for x in det]))

real, null = {}, {}
for name, f, hours, df in universe():
    if name not in picks_all or not picks_all[name] or name == "BTCUSD": continue
    frame = resample_ohlc(df, hours) if hours != 1.0 else df
    if len(frame) < 600: continue
    picks, rate, bp = picks_all[name], RATE[klass(name)], COST_BP[klass(name)]
    r = net_with_cost(frame, picks, hours, rate, bp)
    if r is None: continue
    real[name] = r
    rng = np.random.default_rng(abs(hash(name)) % (2**31)); n = len(frame); dr = []
    for _ in range(NSEED):
        sh = []
        for p in picks:
            q = dict(p); st = rng.integers(LO,HI)*(1 if rng.random()<0.5 else -1)
            q["arm"] = int(np.clip(p["arm"]+st, 0, n-2)); sh.append(q)
        v = net_with_cost(frame, sh, hours, rate, bp)
        if v is not None: dr.append(v)
    null[name] = dr
    print(f"  {name:<11} real {r:>6.3f}  null {np.mean(dr):>6.3f}  lift {r-np.mean(dr):>6.3f}", flush=True)

names = sorted(real)
L = np.array([real[n]-np.mean(null[n]) for n in names])
NE = 15.7*len(names)/80; se = L.std(ddof=1)/np.sqrt(NE)
k = min(len(null[n]) for n in names)
uni = [float(np.mean([null[n][s] for n in names])) for s in range(k)]
obs = float(np.mean([real[n] for n in names]))
print(f"\n{'='*74}\n8.37 AFTER SPREAD + COMMISSION + FINANCING ({len(names)} instruments)\n{'='*74}")
print(f"  observed universe net           {obs:>7.3f} R")
print(f"  shift-null mean (also costed)   {np.mean(uni):>7.3f} R")
print(f"  null 95th percentile            {np.percentile(uni,95):>7.3f} R")
print(f"  observed percentile             {100*np.mean([obs>u for u in uni]):>7.1f}   (need >=95)")
print(f"  LIFT                            {L.mean():>7.3f} R   (was 0.081 pre-spread)")
print(f"  t on lift (N_eff {NE:.1f})          {L.mean()/se:>7.2f}   (need ~1.65)")
print(f"  instruments with lift > 0       {int((L>0).sum()):>7} / {len(names)}")
drop = [n for n in names if klass(n) in ("crypto","etf","yield")]
kp = [n for n in names if n not in drop]
Lk = np.array([real[n]-np.mean(null[n]) for n in kp])
print(f"\n  tradeable subset only (drop crypto/ETF/yield): {len(kp)} instruments")
print(f"    net {np.mean([real[n] for n in kp]):>7.3f} R    lift {Lk.mean():>7.3f} R"
      f"    t {Lk.mean()/(Lk.std(ddof=1)/np.sqrt(15.7*len(kp)/80)):>6.2f}")
