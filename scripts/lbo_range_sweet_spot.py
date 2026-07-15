"""LONDON_BO range-band deep analysis: is 12-20p really the sweet spot?

LIVE geometry (UTC-grouped sessions, asian = UTC h<7 AND broker h<7,
window UTC 08-13, Mon/Tue), fill mechanics identical to
scripts/lbo_geometry_validation.py. Range filter REMOVED at simulation
level; every breakout is recorded with its session range so filters can
be applied post-hoc.

All performance in R-MULTIPLES (pnl / stop distance): the live risk
manager sizes lots off stop distance at fixed 1% risk, so equal-risk
units are the correct cross-range comparison (raw pips overweight wide
ranges: risk ~ range + 2*spread, reward ~ range, R:R ~constant).

Read-only. Run: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < lbo_range_sweet_spot.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

PIP = 0.0001
TP_MULT, SPREAD_P, COMM = 1.0, 1.0, 0.7
DAYS = (0, 1)

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()
rates = mt5.copy_rates_from_pos("GBPUSD", mt5.TIMEFRAME_H1, 0, 50000)
print(f"bars: {len(rates)}")


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


bars = []
for r in rates:
    t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)
    off = eu_dst_offset(t_broker - timedelta(hours=3))
    t_utc = t_broker - timedelta(hours=off)
    bars.append({"bh": t_broker.hour, "uh": t_utc.hour, "udate": t_utc.date(),
                 "uwd": t_utc.weekday(), "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

sessions = {}
for b in bars:
    if b["uwd"] >= 5:
        continue
    sessions.setdefault(b["udate"], {"bars": [], "wd": b["uwd"]})["bars"].append(b)

# Simulate EVERY Mon/Tue breakout, no range filter. Record (year, range_pips, pnl_pips, risk_pips).
trades = []
for d in sorted(sessions):
    s = sessions[d]
    if s["wd"] not in DAYS:
        continue
    asian = [b for b in s["bars"] if b["uh"] < 7 and b["bh"] < 7]
    if len(asian) < 3:
        continue
    a_high = max(b["hi"] for b in asian)
    a_low = min(b["lo"] for b in asian)
    a_range = (a_high - a_low) / PIP
    london = [b for b in s["bars"] if 8 <= b["uh"] < 13]
    if not london:
        continue
    tp_dist = a_range * TP_MULT * PIP
    sp = SPREAD_P * PIP
    for i, b in enumerate(london):
        if b["hi"] > a_high + sp:
            entry, sl, tp = a_high + sp, a_low - sp, a_high + sp + tp_dist
            risk = (entry - sl) / PIP
            pnl = None
            for rb in london[i:]:
                if rb["lo"] <= sl:
                    pnl = -risk - SPREAD_P; break
                if rb["hi"] >= tp:
                    pnl = (tp - entry) / PIP - SPREAD_P; break
            if pnl is None:
                pnl = (london[-1]["cl"] - entry) / PIP - SPREAD_P
            trades.append((d.year, a_range, pnl, risk))
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
            trades.append((d.year, a_range, pnl, risk))
            break

T = np.array(trades)  # cols: year, range, pnl_pips, risk_pips
years, rng, pnl, risk = T[:, 0], T[:, 1], T[:, 2], T[:, 3]
R = (pnl - COMM) / risk  # R-multiple net of commission
print(f"total breakout trades (no range filter): {len(T)}, "
      f"years {int(years.min())}-{int(years.max())}")


def rstats(mask, label):
    r = R[mask]
    if len(r) < 5:
        print(f"{label:<26} N={len(r):>4}  (too few)")
        return
    w = (r > 0).sum()
    gp = r[r > 0].sum() if w else 0.0
    gl = abs(r[r <= 0].sum()) or 0.001
    eq = np.cumsum(r)
    dd = (np.maximum.accumulate(eq) - eq).max()
    print(f"{label:<26} N={len(r):>4} WR={w/len(r)*100:>3.0f}% PF={gp/gl:>5.2f} "
          f"avgR={r.mean():>+6.3f} totR={r.sum():>+7.1f} ddR={dd:>5.1f}")


for since, tag in ((0, "FULL"), (2023, "2023+")):
    m0 = years >= since
    print(f"\n===== {tag}: EDGE DECAY BY RANGE BUCKET (R-multiples, +comm) =====")
    for lo, hi in ((0, 8), (8, 12), (12, 16), (16, 20), (20, 24), (24, 28),
                   (28, 35), (35, 50), (50, 999)):
        rstats(m0 & (rng >= lo) & (rng < hi), f"  range {lo:>2}-{hi:<3}p")

    print(f"----- {tag}: MIN x MAX SWEEP -----")
    for mn in (0, 10, 12, 14):
        for mx in (18, 20, 22, 25, 30, 999):
            if mx <= mn:
                continue
            rstats(m0 & (rng >= mn) & (rng <= mx), f"  min={mn:>2} max={mx:<3}")

print("\n===== PER-YEAR STABILITY (PF in R, +comm) =====")
print(f"{'year':<6}{'12-20p':>22}{'12-25p':>22}{'20-30p':>22}")
for y in range(int(years.min()), int(years.max()) + 1):
    row = f"{y:<6}"
    for mn, mx in ((12, 20), (12, 25), (20, 30)):
        m = (years == y) & (rng >= mn) & (rng <= mx)
        r = R[m]
        if len(r) < 5:
            row += f"{'n=' + str(len(r)):>22}"
            continue
        gp = r[r > 0].sum() if (r > 0).any() else 0.0
        gl = abs(r[r <= 0].sum()) or 0.001
        row += f"{f'N={len(r)} PF={gp/gl:.2f} avgR={r.mean():+.2f}':>22}"
    print(row)
mt5.shutdown()
