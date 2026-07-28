"""LONDON_BO: re-run the 2026-07-02 geometry comparison under an HONEST fill model.

Follow-up to scripts/lbo_fill_model_compare.py, which showed the incumbent
validation fills 62% of trades at a price that was never available (the window
opens already through the level) and that removing that fiction takes GBPUSD
2023+ from PF 1.75 to 0.57 (chase) / 0.89 (skip).

Hypothesis this script tests: the 2026-07-02 verdict -- "the accidentally
deployed LIVE geometry is the best of 4 variants" -- is itself an artifact of
that fill fiction. LIVE has the range ending 04:00 UTC but the window opening
08:00 UTC, a FOUR-hour blind gap, the longest of any variant. The longer the
gap, the more days open already through the level, and the more free impossible
fills the sim books. UTC-doc (range 00-07, window 08-13) has a 1h gap and
"lost" the 2026-07-02 comparison -- but it had far less free money to collect.

If the hypothesis holds, ranking the variants by honest fill should reorder
them, and the gap% column should track the size of the blind window.

Fill models: 'level' (incumbent fiction), 'chase' (deployed market order),
'skip' (pending stop rejected when already through).

Read-only.
Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/lbo_geometry_x_fill.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

PIP = 0.0001
SPREAD_P, COMM_P = 1.0, 0.7
BAND = (10, 22)      # as deployed since 2026-07-15
TP_MULT = 1.0
DAYS = (0, 1)
SYM = "GBPUSD"

# variant -> (asian predicate, window predicate, session key, blind-gap hours)
VARIANTS = {
    "LIVE    (rng~00-04, win 08-13)": ("live", "u", 4),
    "UTC-doc (rng 00-07, win 08-13)": ("doc",  "u", 1),
    "UTC-ldn (rng 00-07, win 07-13)": ("ldn",  "u", 0),
}

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


rates = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 50000)
bars = []
for r in rates:
    t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)
    off = eu_dst_offset(t_broker - timedelta(hours=3))
    t_utc = t_broker - timedelta(hours=off)
    bars.append({"bh": t_broker.hour, "uh": t_utc.hour, "udate": t_utc.date(),
                 "uwd": t_utc.weekday(), "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})


def simulate(kind, gap_mode, since_year=None):
    if kind == "live":
        asian_f = lambda b: b["uh"] < 7 and b["bh"] < 7
        window_f = lambda b: 8 <= b["uh"] < 13
    elif kind == "doc":
        asian_f = lambda b: b["uh"] < 7
        window_f = lambda b: 8 <= b["uh"] < 13
    elif kind == "ldn":
        asian_f = lambda b: b["uh"] < 7
        window_f = lambda b: 7 <= b["uh"] < 13

    sessions = {}
    for b in bars:
        if b["uwd"] >= 5:
            continue
        sessions.setdefault(b["udate"], {"bars": [], "wd": b["uwd"]})["bars"].append(b)

    sp, cost_p = SPREAD_P * PIP, SPREAD_P + COMM_P
    rows = []
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
        if not (BAND[0] <= a_range <= BAND[1]):
            continue
        london = [b for b in s["bars"] if window_f(b)]
        if not london:
            continue

        tp_dist = a_range * TP_MULT * PIP
        up_lvl, dn_lvl = a_high + sp, a_low - sp
        first = london[0]
        gapped = ("LONG" if first["o"] > up_lvl else
                  "SHORT" if first["o"] < dn_lvl else None)
        if gapped and gap_mode == "skip":
            continue

        if gapped:
            direction, start = gapped, 0
            entry = first["o"] if gap_mode == "chase" else (
                up_lvl if gapped == "LONG" else dn_lvl)
        else:
            direction = None
            for i, b in enumerate(london):
                if b["hi"] > up_lvl:
                    direction, entry, start = "LONG", up_lvl, i
                    break
                if b["lo"] < dn_lvl:
                    direction, entry, start = "SHORT", dn_lvl, i
                    break
            if direction is None:
                continue

        if direction == "LONG":
            lvl, sl, tp = up_lvl, dn_lvl, up_lvl + tp_dist
        else:
            lvl, sl, tp = dn_lvl, up_lvl, dn_lvl - tp_dist
        intended_risk = abs(lvl - sl) / PIP

        pnl_p = None
        for rb in london[start:]:
            if direction == "LONG":
                if rb["lo"] <= sl:
                    pnl_p = (sl - entry) / PIP
                    break
                if rb["hi"] >= tp:
                    pnl_p = (tp - entry) / PIP
                    break
            else:
                if rb["hi"] >= sl:
                    pnl_p = (entry - sl) / PIP
                    break
                if rb["lo"] <= tp:
                    pnl_p = (entry - tp) / PIP
                    break
        if pnl_p is None:
            last = london[-1]["cl"]
            pnl_p = (last - entry) / PIP if direction == "LONG" else (entry - last) / PIP

        rows.append({"gapped": bool(gapped), "R": (pnl_p - cost_p) / intended_risk})
    return rows


def stats(rows):
    if not rows:
        return "N=0"
    v = np.array([r["R"] for r in rows])
    w = (v > 0).sum()
    gp = v[v > 0].sum() if w else 0.0
    gl = abs(v[v <= 0].sum()) or 1e-9
    eq = np.cumsum(v)
    dd = (np.maximum.accumulate(eq) - eq).max() if len(v) > 1 else 0.0
    g = sum(r["gapped"] for r in rows)
    return (f"N={len(v):>4} WR={w/len(v)*100:>3.0f}% PF={gp/gl:>5.2f} "
            f"totR={v.sum():>+7.1f} ddR={dd:>5.1f} gap%={g*100//len(v):>3}")


for since, label in ((None, "FULL history"), (2023, "2023+ only")):
    print(f"\n{'='*104}\n=== {SYM} {label}  (band {BAND[0]}-{BAND[1]}p, spread {SPREAD_P}p + comm {COMM_P}p)"
          f"\n{'='*104}")
    for vname, (kind, _key, blind) in VARIANTS.items():
        print(f"\n  {vname}   blind gap = {blind}h")
        for gm, gl in (("level", "level  (incumbent fiction)"),
                       ("chase", "chase  (deployed)"),
                       ("skip",  "skip   (pending-stop fix)")):
            print(f"    {gl:<28}{stats(simulate(kind, gm, since))}")

mt5.shutdown()
