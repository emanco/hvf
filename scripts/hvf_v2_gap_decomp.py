"""Which gap does the damage, and does refusing to chase fix it? (8.38b)"""
import contextlib, io, pickle, sys
from pathlib import Path
import numpy as np
ROOT = Path("/Users/manu/Dev/hvf"); sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"scripts"))
with contextlib.redirect_stdout(io.StringIO()):
    from hvf_trader.detector.hvf_v2 import resample_ohlc
    from hvf_v2_spread import COST_BP
    from hvf_v2_wide_run import RATE, klass, universe
S = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad")
picks_all = pickle.loads((S/"wide_picks.pkl").read_bytes())

def sim(frame, picks, hours, gap_entry=True, gap_stop=True, gap_tp=True, max_chase=None):
    op=frame["open"].to_numpy(float); hi=frame["high"].to_numpy(float)
    lo=frame["low"].to_numpy(float); close=frame["close"].to_numpy(float)
    day=hours/24.0; n,free,out=len(frame),-1,[]
    skipped=0
    for s_ in sorted(picks,key=lambda x:x["arm"]):
        arm=s_["arm"]
        if arm<0 or arm+1>=n or arm<=free: continue
        d=s_["d"]; e,st=close[arm]+s_["e_off"],close[arm]+s_["s_off"]
        risk=abs(e-st)
        if risk<=0: continue
        fill=None
        for i in range(arm+1,min(arm+1+s_["wait"],n)):
            if (d>0 and hi[i]>=e) or (d<0 and lo[i]<=e):
                thr=(d>0 and op[i]>e) or (d<0 and op[i]<e)
                if thr and max_chase is not None and abs(op[i]-e)/risk > max_chase:
                    fill="SKIP"; break          # stop-limit: refuse the gapped fill
                e_fill=op[i] if (thr and gap_entry) else e
                fill=i; break
        if fill is None: continue
        if fill=="SKIP": skipped+=1; continue
        C=(e+st)/2.0
        legs=[(1/3,C+d*risk),(1/3,C+d*s_["amp2"]),(1/3,C+d*s_["amp"])]
        legs=[(f,t) for f,t in legs if d*(t-e)>0]
        if not legs: continue
        legs.sort(key=lambda x:d*x[1]); tp1=C+d*risk; lev=abs(e)/risk
        banked,size,stop,carry=0.0,1.0,st,0.0
        for i in range(fill,n):
            carry+=size*lev*day
            if (d>0 and lo[i]<=stop) or (d<0 and hi[i]>=stop):
                thr=(d>0 and op[i]<stop) or (d<0 and op[i]>stop)
                px=op[i] if (thr and gap_stop) else stop
                banked+=size*d*(px-e_fill)/risk; size,free=0.0,i; break
            while legs and ((d>0 and hi[i]>=legs[0][1]) or (d<0 and lo[i]<=legs[0][1])):
                f,t=legs.pop(0)
                thr=(d>0 and op[i]>t) or (d<0 and op[i]<t)
                px=op[i] if (thr and gap_tp) else t
                take=min(f,size); banked+=take*d*(px-e_fill)/risk; size-=take
            if stop!=e and ((d>0 and hi[i]>=tp1) or (d<0 and lo[i]<=tp1)): stop=e
            if size<=1e-9: free=i; break
        if size>1e-9: continue
        out.append((banked,carry,(i-fill+1)*day,lev))
    return out, skipped

frames={}
for name,f,hours,df in universe():
    if name not in picks_all or not picks_all[name] or name=="BTCUSD": continue
    fr=resample_ohlc(df,hours) if hours!=1.0 else df
    if len(fr)>=600: frames[name]=(fr,hours)

def uni(**kw):
    nets=[]; tot_sk=0; tot_n=0
    for name,(fr,hours) in frames.items():
        det,sk=sim(fr,picks_all[name],hours,**kw)
        if len(det)<15: continue
        rate,bp=RATE[klass(name)],COST_BP[klass(name)]
        nets.append(float(np.mean([x[0]-x[1]*rate/100.0/365.0-x[3]*bp*1e-4 for x in det])))
        tot_sk+=sk; tot_n+=len(det)
    return np.mean(nets), sum(1 for x in nets if x>0), len(nets), tot_sk, tot_n

print("DECOMPOSITION: turn each gap correction on one at a time")
print(f"  {'model':<44}{'net R':>9}{'positive':>11}")
for lbl,kw in [("8.37 baseline (all fills at the level)", dict(gap_entry=False,gap_stop=False,gap_tp=False)),
               ("+ entry gap only",                       dict(gap_entry=True, gap_stop=False,gap_tp=False)),
               ("+ stop gap only",                        dict(gap_entry=False,gap_stop=True, gap_tp=False)),
               ("+ TP gap only (favourable)",             dict(gap_entry=False,gap_stop=False,gap_tp=True)),
               ("all three = honest fills",               dict(gap_entry=True, gap_stop=True, gap_tp=True))]:
    m,p,k,_,_=uni(**kw); print(f"  {lbl:<44}{m:>9.3f}{p:>7} / {k}")

print("\nREMEDY: stop-limit entry -- refuse to chase a gap beyond X x risk")
print(f"  {'max chase':<44}{'net R':>9}{'positive':>11}{'skipped':>10}")
for mc in [None,2.0,1.0,0.5,0.25,0.1,0.0]:
    m,p,k,sk,n=uni(max_chase=mc)
    lbl="no limit (take every gap)" if mc is None else f"skip if gap > {mc:g} x risk"
    print(f"  {lbl:<44}{m:>9.3f}{p:>7} / {k}{sk:>10}")

print("\n\nSPLIT BY BAR SIZE: is the entry precision achievable intraday? (8.38c)")
src={}
for name,f,hours,df in universe():
    if name in frames: src[name]=hours
print(f"  {'subset':<30}{'k':>4}{'baseline':>11}{'honest':>10}{'delta':>9}{'positive':>11}")
for lbl,sel in [("4h bars (H1-sourced)", lambda h: h==4.0),
                ("3D bars (D1-sourced)", lambda h: h==72.0),
                ("Hunt's own 6 charts (1-18h)", lambda h: h not in (4.0,72.0))]:
    b_,h_,ps,kk=[],[],0,0
    for name,(fr,hours) in frames.items():
        if not sel(src[name]): continue
        rate,bp=RATE[klass(name)],COST_BP[klass(name)]
        d0,_=sim(fr,picks_all[name],hours,gap_entry=False,gap_stop=False,gap_tp=False)
        d1,_=sim(fr,picks_all[name],hours)
        if len(d1)<15 or len(d0)<15: continue
        n0=float(np.mean([x[0]-x[1]*rate/100.0/365.0-x[3]*bp*1e-4 for x in d0]))
        n1=float(np.mean([x[0]-x[1]*rate/100.0/365.0-x[3]*bp*1e-4 for x in d1]))
        b_.append(n0); h_.append(n1); kk+=1; ps+= (n1>0)
    if kk: print(f"  {lbl:<30}{kk:>4}{np.mean(b_):>11.3f}{np.mean(h_):>10.3f}{np.mean(h_)-np.mean(b_):>9.3f}{ps:>7} / {kk}")

print("\n  entry-gap rate by bar size:")
for lbl,sel in [("4h",lambda h:h==4.0),("3D",lambda h:h==72.0),("1-18h",lambda h:h not in (4.0,72.0))]:
    g=[]
    for name,(fr,hours) in frames.items():
        if not sel(src[name]): continue
        op=fr["open"].to_numpy(float); hi=fr["high"].to_numpy(float); lo=fr["low"].to_numpy(float); cl=fr["close"].to_numpy(float)
        n=len(fr); hits=0; thr=0
        for s_ in sorted(picks_all[name],key=lambda x:x["arm"])[:4000]:
            a=s_["arm"]
            if a<0 or a+1>=n: continue
            d=s_["d"]; e=cl[a]+s_["e_off"]
            for i in range(a+1,min(a+1+s_["wait"],n)):
                if (d>0 and hi[i]>=e) or (d<0 and lo[i]<=e):
                    hits+=1; thr+= int((d>0 and op[i]>e) or (d<0 and op[i]<e)); break
        if hits: g.append(thr/hits)
    if g: print(f"    {lbl:<8}{100*np.mean(g):>6.1f}% of entries gap through")
