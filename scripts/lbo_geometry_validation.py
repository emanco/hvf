"""LONDON_BO geometry-variant comparison on IC H1 GBPUSD data.

Variants (all: rng 12-20p, TP 1.0x range, SL opposite edge, spread 1p,
Mon/Tue only, one trade/day, SL-checked-first):
  BT-orig   - as the original backtest: broker-hour geometry (asian h<7,
              window 8<=h<13 broker, broker-date weekday)
  LIVE      - as deployed: asian bars = UTC 00-07 AND broker h<7 (4-5 bars),
              window UTC 08-13, UTC weekday
  UTC-doc   - documented intent: asian = UTC 00-07 (7 bars), window UTC
              08-13, UTC weekday
  UTC-ldn   - same but window from 07:00 UTC (actual London open in summer)
Each variant reported with spread-only and +0.7p commission ($7/lot RT).
Also split full-history vs 2023+ (MetaQuotes backfill caution for old years).
Read-only.

Results 2026-07-02 (IC H1 GBPUSD, 50k bars ~ 8.3y):
                       FULL (+0.7p comm)              2023+ (+0.7p comm)
  BT-orig   N=140 PF 1.69 +508p dd 124p     N= 72 PF 1.62 +225p dd  62p
  LIVE      N=260 PF 1.63 +929p dd 108p     N=131 PF 1.62 +443p dd  73p
  UTC-doc   N=111 PF 1.21 +157p dd 125p     N= 60 PF 0.99   -4p dd 125p
  UTC-ldn   N=111 PF 0.83 -166p dd 214p     N= 60 PF 0.74 -137p dd 214p

Verdict: the ACCIDENTALLY-deployed geometry (broker-time/UTC mislabel gave a
4-bar UTC 00-04 range traded UTC 08-13) is the best variant — same PF as the
original claim after commission, ~2x the trades, smaller DD, stable in 2023+.
The documented "00-07 UTC range" intent is breakeven-to-losing. LONDON_BO was
therefore KEPT as deployed (2026-07-02); do not "fix" its clock handling to
match the docstrings without re-running this comparison.

Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/lbo_geometry_validation.py
"""
import os
import time as _time
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

PIP = 0.0001
MIN_RNG, MAX_RNG, TP_MULT, SPREAD_P = 12, 20, 1.0, 1.0
COMM = 0.7
DAYS = (0, 1)  # Mon/Tue

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()

rates = mt5.copy_rates_from_pos("GBPUSD", mt5.TIMEFRAME_H1, 0, 50000)
print(f"bars: {len(rates)}")


def eu_dst_offset(dt_utc):
    """IC broker offset vs UTC: +3 during EU DST (last Sun Mar -> last Sun Oct), else +2."""
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


bars = []
for r in rates:
    t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)  # broker time mislabeled UTC
    # iterate: offset depends on true UTC; broker-3h is close enough to pick DST rule
    off = eu_dst_offset(t_broker - timedelta(hours=3))
    t_utc = t_broker - timedelta(hours=off)
    bars.append({
        "bh": t_broker.hour, "bdate": t_broker.date(), "bwd": t_broker.weekday(),
        "uh": t_utc.hour, "udate": t_utc.date(), "uwd": t_utc.weekday(),
        "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4], "t_utc": t_utc,
    })


def build_sessions(key):
    """Group bars by broker date ('b') or UTC date ('u')."""
    sessions = {}
    for b in bars:
        d = b["bdate"] if key == "b" else b["udate"]
        wd = b["bwd"] if key == "b" else b["uwd"]
        if wd >= 5:
            continue
        sessions.setdefault(d, {"bars": [], "wd": wd})["bars"].append(b)
    return sessions


def simulate(variant, since_year=None):
    if variant == "BT-orig":
        sessions = build_sessions("b")
        asian_f = lambda b: b["bh"] < 7
        window_f = lambda b: 8 <= b["bh"] < 13
    elif variant == "LIVE":
        sessions = build_sessions("u")
        asian_f = lambda b: b["uh"] < 7 and b["bh"] < 7
        window_f = lambda b: 8 <= b["uh"] < 13
    elif variant == "UTC-doc":
        sessions = build_sessions("u")
        asian_f = lambda b: b["uh"] < 7
        window_f = lambda b: 8 <= b["uh"] < 13
    elif variant == "UTC-ldn":
        sessions = build_sessions("u")
        asian_f = lambda b: b["uh"] < 7
        window_f = lambda b: 7 <= b["uh"] < 13
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if since_year and d.year < since_year:
            continue
        if s["wd"] not in DAYS:
            continue
        asian = [b for b in s["bars"] if asian_f(b)]
        if len(asian) < 3:
            continue
        a_high = max(b["hi"] for b in asian)
        a_low = min(b["lo"] for b in asian)
        a_range = (a_high - a_low) / PIP
        if not (MIN_RNG <= a_range <= MAX_RNG):
            continue
        london = [b for b in s["bars"] if window_f(b)]
        if not london:
            continue
        tp_dist = a_range * TP_MULT * PIP
        sp = SPREAD_P * PIP
        for i, b in enumerate(london):
            if b["hi"] > a_high + sp:
                entry, sl, tp = a_high + sp, a_low - sp, a_high + sp + tp_dist
                risk = (entry - sl) / PIP
                pnl, hit = None, None
                for rb in london[i:]:
                    if rb["lo"] <= sl:
                        pnl, hit = -risk - SPREAD_P, "SL"; break
                    if rb["hi"] >= tp:
                        pnl, hit = (tp - entry) / PIP - SPREAD_P, "TP"; break
                if pnl is None:
                    pnl = (london[-1]["cl"] - entry) / PIP - SPREAD_P
                trades.append(pnl)
                break
            if b["lo"] < a_low - sp:
                entry, sl, tp = a_low - sp, a_high + sp, a_low - sp - tp_dist
                risk = (sl - entry) / PIP
                pnl = None
                for rb in london[i:]:
                    if rb["hi"] >= sl:
                        pnl = -risk - SPREAD_P; break
                    if rb["lo"] <= tp:
                        pnl = (entry - tp) / PIP - SPREAD_P; break
                if pnl is None:
                    pnl = (entry - london[-1]["cl"]) / PIP - SPREAD_P
                trades.append(pnl)
                break
    return np.array(trades)


def stats(pnls):
    if len(pnls) == 0:
        return "n=0"
    w = (pnls > 0).sum()
    gp = pnls[pnls > 0].sum() if w else 0.0
    gl = abs(pnls[pnls <= 0].sum()) or 0.001
    eq = np.cumsum(pnls)
    dd = (np.maximum.accumulate(eq) - eq).max() if len(pnls) > 1 else 0
    return (f"N={len(pnls):>4} WR={w/len(pnls)*100:>3.0f}% PF={gp/gl:>5.2f} "
            f"tot={pnls.sum():>+7.0f}p dd={dd:>5.0f}p")


for since, label in ((None, "FULL history"), (2023, "2023+ only")):
    print(f"\n=== {label} ===")
    print(f"{'variant':<10}{'cost':<14}stats")
    for v in ("BT-orig", "LIVE", "UTC-doc", "UTC-ldn"):
        p = simulate(v, since)
        print(f"{v:<10}{'spread only':<14}{stats(p)}")
        print(f"{v:<10}{'+0.7p comm':<14}{stats(p - COMM if len(p) else p)}")
mt5.shutdown()
