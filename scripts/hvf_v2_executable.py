"""Is there an edge in the EXECUTABLE subset? (8.38d)
Keep only picks whose entry is genuinely still ahead of price at the arming bar,
and fill every level honestly. This is the strategy as it could actually be traded."""
import contextlib, io, pickle, sys
from pathlib import Path
import numpy as np
ROOT=Path("/Users/manu/Dev/hvf"); sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"scripts"))
with contextlib.redirect_stdout(io.StringIO()):
    from hvf_trader.detector.hvf_v2 import resample_ohlc
    from hvf_v2_spread import COST_BP
    from hvf_v2_wide_run import RATE, klass, universe
    from hvf_v2_gapfill import simulate_gap
S=Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")
pa=pickle.loads((S/"wide_picks.pkl").read_bytes())
NSEED,LO,HI=60,50,1500

frames={}
for name,f,hours,df in universe():
    if name not in pa or not pa[name] or name=="BTCUSD": continue
    fr=resample_ohlc(df,hours) if hours!=1.0 else df
    if len(fr)>=600: frames[name]=(fr,hours)

def netof(fr,picks,hours,name):
    det=simulate_gap(fr,picks,hours,0.0)
    if len(det)<15: return None
    rate,bp=RATE[klass(name)],COST_BP[klass(name)]
    return float(np.mean([x[0]-x[1]*rate/100.0/365.0-x[3]*bp*1e-4 for x in det])), len(det)

real,null,kept,tot=[],[],0,0
names=[]
for name,(fr,hours) in frames.items():
    cl=fr["close"].to_numpy(float)
    ex=[p for p in pa[name] if p["d"]*p["e_off"]>0]
    tot+=len(pa[name]); kept+=len(ex)
    if not ex: continue
    r=netof(fr,ex,hours,name)
    if r is None: continue
    real.append(r[0]); names.append((name,r[1]))
    rng=np.random.default_rng(abs(hash(name))%(2**31)); n=len(fr); dr=[]
    for _ in range(NSEED):
        sh=[]
        for p in ex:
            q=dict(p); stp=rng.integers(LO,HI)*(1 if rng.random()<0.5 else -1)
            q["arm"]=int(np.clip(p["arm"]+stp,0,n-2)); sh.append(q)
        v=netof(fr,sh,hours,name)
        if v is not None: dr.append(v[0])
    null.append(np.mean(dr) if dr else 0.0)

real=np.array(real); null=np.array(null); L=real-null
NE=15.7*len(real)/80; se=L.std(ddof=1)/np.sqrt(NE)
print(f"EXECUTABLE SUBSET, honest fills, all costs")
print(f"  picks retained                {kept:,} / {tot:,} = {100*kept/tot:.1f}%")
print(f"  instruments                   {len(real)}")
print(f"  trades                        {sum(n for _,n in names):,}")
print(f"  mean net R                    {real.mean():>7.3f}")
print(f"  shift-null mean               {null.mean():>7.3f}")
print(f"  LIFT                          {L.mean():>7.3f}")
print(f"  t on lift (N_eff {NE:.1f})        {L.mean()/se:>7.2f}   (need ~1.65)")
print(f"  instruments net > 0           {int((real>0).sum())} / {len(real)}")
print(f"  instruments lift > 0          {int((L>0).sum())} / {len(real)}")
