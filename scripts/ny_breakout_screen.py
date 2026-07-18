"""NY-open range breakout screen — EURUSD primary, GBPUSD family-diagnostic.

Pre-registered geometry (LBO-family, third instance of quiet-range ->
active-session breakout): range = true UTC 08:00-13:00 London morning
(M15), breakout window 13:00-17:00, SL = opposite edge, TP = 1.0x range,
EOD force-close 20:00, Mon-Fri. Band = same relative selectivity as the
validated GBPUSD LBO band (10-22p on a 23p median = 0.43-0.96x median)
applied to each pair's own London-morning median. Costs: fixed spread
(EURUSD 0.8p, GBPUSD 1.0p) + 0.7p commission; same-bar SL/TP resolved
against the strategy; all stats in equal-risk R units.

PASS bar (pre-committed, same as pair screen): 2023+ PF >= 1.4 AND
avgR > 0 in each full year (2023, 2024, 2025) AND test-2025+ PF >= 1.2
with train (<2025) avgR > 0. Weekday/exit tables are diagnostics only.

Read-only. Run: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < ny_breakout_screen.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

PAIRS = {"EURUSD": 0.8, "GBPUSD": 1.0}   # fixed spread pips
COMM = 0.7
BAND_FRAC = (10.0 / 23.0, 22.0 / 23.0)   # validated LBO selectivity vs median
RANGE_H = (8, 13)                        # true UTC London morning
TRADE_H = (13, 17)                       # true UTC NY-open window
EOD_H = 20
SPLIT = datetime(2025, 1, 1).date()
FULL_YEARS = (2023, 2024, 2025)
PIP = 0.0001

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


def stats(rows):
    if len(rows) < 5:
        return None
    r = np.array([x[1] for x in rows])
    w = (r > 0).sum()
    gp = r[r > 0].sum() if w else 0.0
    gl = abs(r[r <= 0].sum()) or 0.001
    eq = np.cumsum(r)
    dd = (np.maximum.accumulate(eq) - eq).max()
    return dict(N=len(r), WR=w / len(r) * 100, PF=gp / gl, avgR=r.mean(),
                totR=r.sum(), ddR=dd)


def fmt(s, label):
    if s is None:
        return f"{label:<16} (too few trades)"
    return (f"{label:<16} N={s['N']:>4} WR={s['WR']:>3.0f}% PF={s['PF']:>5.2f} "
            f"avgR={s['avgR']:>+6.3f} totR={s['totR']:>+7.1f} ddR={s['ddR']:>5.1f}")


for sym, spread_p in PAIRS.items():
    m15 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 99000))
    if len(m15) < 20000:
        print(f"{sym}: insufficient data")
        continue
    m15["bt"] = pd.to_datetime(m15["time"], unit="s")
    # true-UTC time per bar
    offs = m15["bt"].apply(
        lambda t: eu_dst_offset(t.to_pydatetime().replace(tzinfo=timezone.utc)
                                - timedelta(hours=3)))
    m15["ut"] = m15["bt"] - pd.to_timedelta(offs, unit="h")
    m15["udate"] = m15["ut"].dt.date
    m15["uh"] = m15["ut"].dt.hour

    by_date = {d: g.sort_values("ut").reset_index(drop=True)
               for d, g in m15.groupby("udate")}

    # First pass: London-morning range per eligible day -> median for band
    ranges = {}
    for d, g in by_date.items():
        if datetime(d.year, d.month, d.day).weekday() >= 5:
            continue
        rng_bars = g[(g["uh"] >= RANGE_H[0]) & (g["uh"] < RANGE_H[1])]
        if len(rng_bars) < 16:
            continue
        hi, lo = float(rng_bars["high"].max()), float(rng_bars["low"].min())
        if hi > lo:
            ranges[d] = (hi, lo, (hi - lo) / PIP)
    med = float(np.median([v[2] for v in ranges.values()]))
    lo_b, hi_b = BAND_FRAC[0] * med, BAND_FRAC[1] * med
    print(f"\n{'='*70}\n{sym}: {len(ranges)} sessions, median 08-13 range "
          f"{med:.0f}p -> band {lo_b:.0f}-{hi_b:.0f}p, spread {spread_p}p, "
          f"comm {COMM}p\n{'='*70}")

    rows = []          # (date, R, weekday, exit_reason)
    for d in sorted(ranges):
        hi, lo, rng_p = ranges[d]
        if not (lo_b <= rng_p <= hi_b):
            continue
        g = by_date[d]
        win = g[(g["uh"] >= TRADE_H[0]) & (g["uh"] < TRADE_H[1])]
        win = win.reset_index(drop=True)
        if win.empty:
            continue
        sp = spread_p * PIP
        long_lvl, short_lvl = hi + sp, lo - sp
        tp_dist = rng_p * PIP
        risk_p = rng_p + 2 * spread_p
        entry_i, direction = None, None
        for i in range(len(win)):
            b = win.iloc[i]
            lt = b["high"] > long_lvl
            st = b["low"] < short_lvl
            if lt and st:
                entry_i, direction = i, "BOTH"; break
            if lt:
                entry_i, direction = i, "LONG"; break
            if st:
                entry_i, direction = i, "SHORT"; break
        if entry_i is None:
            continue
        cost = spread_p + COMM
        wd = datetime(d.year, d.month, d.day).weekday()
        if direction == "BOTH":
            rows.append((d, (-risk_p - cost) / (risk_p + cost), wd, "SPAN"))
            continue
        # walk to TP/SL/EOD across the rest of the day (< 20:00 true UTC)
        after = g[(g["ut"] >= win.iloc[entry_i]["ut"]) & (g["uh"] < EOD_H)]
        after = after.reset_index(drop=True)
        entry_px = long_lvl if direction == "LONG" else short_lvl
        sl_px = short_lvl if direction == "LONG" else long_lvl
        tp_px = (long_lvl + tp_dist) if direction == "LONG" else (short_lvl - tp_dist)
        pnl, reason = None, None
        for j in range(len(after)):
            b = after.iloc[j]
            if direction == "LONG":
                if b["low"] <= sl_px:
                    pnl, reason = -risk_p - cost, "SL"; break
                if b["high"] >= tp_px:
                    pnl, reason = rng_p - cost, "TP"; break
            else:
                if b["high"] >= sl_px:
                    pnl, reason = -risk_p - cost, "SL"; break
                if b["low"] <= tp_px:
                    pnl, reason = rng_p - cost, "TP"; break
        if pnl is None:
            last_c = float(after.iloc[-1]["close"]) if len(after) else entry_px
            raw = (last_c - entry_px) if direction == "LONG" else (entry_px - last_c)
            pnl, reason = raw / PIP - cost, "EOD"
        rows.append((d, pnl / (risk_p + cost), wd, reason))

    all_s = stats(rows)
    print(fmt(all_s, "ALL"))
    print(fmt(stats([x for x in rows if x[0].year >= 2023]), "2023+"))
    print(fmt(stats([x for x in rows if x[0] < SPLIT]), "train<2025"))
    print(fmt(stats([x for x in rows if x[0] >= SPLIT]), "test 2025+"))
    print("-- per year --")
    years = sorted({x[0].year for x in rows})
    for y in years:
        print(fmt(stats([x for x in rows if x[0].year == y]), f"  {y}"))
    print("-- per weekday (diagnostic only) --")
    for wd, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"]):
        print(fmt(stats([x for x in rows if x[2] == wd]), f"  {nm}"))
    print("-- by exit (diagnostic only) --")
    for rs in ("TP", "SL", "EOD", "SPAN"):
        sub = [x for x in rows if x[3] == rs]
        if sub:
            print(fmt(stats(sub), f"  {rs}"))
    # verdict
    s23 = stats([x for x in rows if x[0].year >= 2023])
    tr = stats([x for x in rows if x[0] < SPLIT])
    te = stats([x for x in rows if x[0] >= SPLIT])
    yr_ok = all(
        (sy := stats([x for x in rows if x[0].year == y])) is not None
        and sy["avgR"] > 0 for y in FULL_YEARS
    )
    c1 = s23 is not None and s23["PF"] >= 1.4
    c3 = tr is not None and tr["avgR"] > 0 and te is not None and te["PF"] >= 1.2
    print(f"VERDICT {sym}: PF2023+>=1.4:{'Y' if c1 else 'N'} "
          f"yearly+:{'Y' if yr_ok else 'N'} traintest:{'Y' if c3 else 'N'} "
          f"=> {'PASS' if (c1 and yr_ok and c3) else 'FAIL'}")

mt5.shutdown()
