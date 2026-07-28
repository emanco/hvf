"""LONDON_BO fill-model audit: does the incumbent backtest fill at a price live never gets?

Motivation (2026-07-28): all 12 live LBO fills landed past the breakout level
(0.4p .. 21.5p chase), inflating realised risk 1.02x..1.84x while SL/TP/lots
stayed pinned to the level. Live is 7W/5L PF 0.69 at a 58% WR -- the win rate
matches lbo_geometry_validation.py (PF 1.63), so the edge is real and the
payoff is being eaten.

Root cause: _scan_london_bo_symbol gates on `hour >= 8`, so a range broken
during 07:00-08:00 UTC is invisible until 08:00; then place_market_order fills
at whatever price is current. The 08:00 bar simply opens through the level.
lbo_geometry_validation.py fills every trade exactly AT the level, including on
days that opened through it -- a price that was never available.

Ladder (each row changes ONE thing from the row above):
  A INCUMBENT     lbo_geometry_validation.py LIVE variant, verbatim:
                  band 12-20, pips, fill at level always. Sanity row -- must
                  reproduce N=260 PF 1.63 full / N=131 PF 1.62 2023+.
  B +R metric     same trades, scored in R vs INTENDED risk (level-to-edge),
                  which is what calculate_lot_size actually sizes off.
  C +live band    band 10-22 / 19-42 as deployed since 2026-07-15.
  D +chase        already-through days fill at the window open, not the level.
                  SL/TP/size still derive from the level. == deployed code.
  E +skip instead already-through days are SKIPPED (pending stop resting at the
                  level is rejected, IC retcode 10015). == ASB today, == the
                  proposed fix.

Caveat: on H1 data an intra-window fast run through the level cannot be
resolved, so non-gapped fills are credited at the level in every row. That is
generous to D, so D's measured damage is a floor, not a ceiling.

Read-only.
Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/lbo_fill_model_compare.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

SYMS = {
    "GBPUSD": {"pip": 0.0001, "live_band": (10, 22), "spread_p": 1.0, "comm_p": 0.7},
    "GBPJPY": {"pip": 0.01,   "live_band": (19, 42), "spread_p": 1.9, "comm_p": 1.05},
}
INCUMBENT_BAND = (12, 20)
TP_MULT = 1.0
DAYS = (0, 1)  # Mon/Tue

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


def eu_dst_offset(dt_utc):
    """IC broker offset vs UTC: +3 during EU DST (last Sun Mar -> last Sun Oct), else +2."""
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load_bars(sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
    out = []
    for r in rates:
        t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)  # mislabeled UTC
        off = eu_dst_offset(t_broker - timedelta(hours=3))
        t_utc = t_broker - timedelta(hours=off)
        out.append({"bh": t_broker.hour, "uh": t_utc.hour,
                    "udate": t_utc.date(), "uwd": t_utc.weekday(),
                    "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})
    return out


def simulate(sym, bars, band, gap_mode, since_year=None):
    """LIVE geometry: asian uh<7 and bh<7, window 8<=uh<13, UTC weekday, Mon/Tue.

    gap_mode: 'level' fill at the level even if already through (incumbent),
              'chase' fill at the window open (deployed),
              'skip'  no trade (pending stop rejected; proposed fix).
    """
    cfg = SYMS[sym]
    pip, (lo_band, hi_band) = cfg["pip"], band
    sp = cfg["spread_p"] * pip
    cost_p = cfg["spread_p"] + cfg["comm_p"]

    sessions = {}
    for b in bars:
        if b["uwd"] >= 5:
            continue
        sessions.setdefault(b["udate"], {"bars": [], "wd": b["uwd"]})["bars"].append(b)

    rows = []
    for d in sorted(sessions):
        s = sessions[d]
        if since_year and d.year < since_year:
            continue
        if s["wd"] not in DAYS:
            continue
        asian = [b for b in s["bars"] if b["uh"] < 7 and b["bh"] < 7]
        if len(asian) < 3:
            continue
        a_high = max(b["hi"] for b in asian)
        a_low = min(b["lo"] for b in asian)
        a_range = (a_high - a_low) / pip
        if not (lo_band <= a_range <= hi_band):
            continue
        london = [b for b in s["bars"] if 8 <= b["uh"] < 13]
        if not london:
            continue

        tp_dist = a_range * TP_MULT * pip
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

        # SL/TP/size always derive from the LEVEL, never the fill (as deployed).
        if direction == "LONG":
            lvl, sl, tp = up_lvl, dn_lvl, up_lvl + tp_dist
        else:
            lvl, sl, tp = dn_lvl, up_lvl, dn_lvl - tp_dist
        intended_risk = abs(lvl - sl) / pip
        chase = (entry - lvl) / pip if direction == "LONG" else (lvl - entry) / pip

        pnl_p = None
        for rb in london[start:]:
            if direction == "LONG":
                if rb["lo"] <= sl:
                    pnl_p = (sl - entry) / pip
                    break
                if rb["hi"] >= tp:
                    pnl_p = (tp - entry) / pip
                    break
            else:
                if rb["hi"] >= sl:
                    pnl_p = (entry - sl) / pip
                    break
                if rb["lo"] <= tp:
                    pnl_p = (entry - tp) / pip
                    break
        if pnl_p is None:  # 13:00 time exit
            last = london[-1]["cl"]
            pnl_p = (last - entry) / pip if direction == "LONG" else (entry - last) / pip

        rows.append({"gapped": bool(gapped), "chase": chase,
                     "pips": pnl_p - cost_p,
                     "R": (pnl_p - cost_p) / intended_risk})
    return rows


def stats(rows, unit):
    if not rows:
        return "N=0"
    v = np.array([r[unit] for r in rows])
    w = (v > 0).sum()
    gp = v[v > 0].sum() if w else 0.0
    gl = abs(v[v <= 0].sum()) or 1e-9
    eq = np.cumsum(v)
    dd = (np.maximum.accumulate(eq) - eq).max() if len(v) > 1 else 0.0
    g = sum(r["gapped"] for r in rows)
    tot = f"{v.sum():>+7.0f}p" if unit == "pips" else f"{v.sum():>+7.1f}R"
    ddf = f"{dd:>5.0f}p" if unit == "pips" else f"{dd:>5.1f}R"
    return (f"N={len(v):>4} WR={w/len(v)*100:>3.0f}% PF={gp/gl:>5.2f} "
            f"tot={tot} dd={ddf} worst={v.min():>+6.1f} gap%={g*100//len(v):>3}")


LADDER = [
    ("A INCUMBENT   ", "incumbent", "level", "pips"),
    ("B  +R metric  ", "incumbent", "level", "R"),
    ("C  +live band ", "live",      "level", "R"),
    ("D  +chase(DEPLOYED)", "live",  "chase", "R"),
    ("E  +skip (FIX)", "live",      "skip",  "R"),
]

for since, label in ((None, "FULL history"), (2023, "2023+ only")):
    print(f"\n{'='*100}\n=== {label} ===\n{'='*100}")
    for sym in SYMS:
        bars = load_bars(sym)
        print(f"\n{sym}   spread {SYMS[sym]['spread_p']}p + comm {SYMS[sym]['comm_p']}p")
        for name, band_key, gap_mode, unit in LADDER:
            band = INCUMBENT_BAND if band_key == "incumbent" else SYMS[sym]["live_band"]
            print(f"  {name:<20}{stats(simulate(sym, bars, band, gap_mode, since), unit)}")

print(f"\n{'='*100}\n=== chase incidence & size (deployed model, live band, 2023+) ===\n{'='*100}")
print("Live reference: 6 of 12 fills (50%) chased >5p past the level; max 21.5p.")
for sym in SYMS:
    rows = simulate(sym, load_bars(sym), SYMS[sym]["live_band"], "chase", 2023)
    g = [r for r in rows if r["gapped"]]
    if rows and g:
        ch = np.array([r["chase"] for r in g])
        Rg = np.array([r["R"] for r in g])
        Rn = np.array([r["R"] for r in rows if not r["gapped"]])
        print(f"{sym}: {len(g)}/{len(rows)} ({len(g)*100//len(rows)}%) open already through | "
              f"chase med {np.median(ch):.1f}p p90 {np.percentile(ch,90):.1f}p max {ch.max():.1f}p")
        print(f"{'':>{len(sym)+2}}avgR gapped {Rg.mean():+.3f} (PF {Rg[Rg>0].sum()/max(abs(Rg[Rg<=0].sum()),1e-9):.2f})"
              f" vs clean {Rn.mean():+.3f} (PF {Rn[Rn>0].sum()/max(abs(Rn[Rn<=0].sum()),1e-9):.2f})")

mt5.shutdown()
