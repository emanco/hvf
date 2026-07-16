"""Pair-extension screen for LONDON_BO and ASB — pre-registered candidates.

LBO geometry (deployed LIVE variant, 10-22p band vol-scaled): candidates
EURUSD, GBPJPY, EURGBP, USDJPY (+ GBPUSD incumbent as harness sanity row).
ASB geometry (deployed: brackets, ADR filter, trend filter vol-scaled,
BE12 exit): candidates EURUSD, USDJPY, AUDJPY (+ GBPJPY incumbent).

Zero per-pair tuning: absolute thresholds scale by relative volatility
(pair median Asian range vs incumbent). Costs: vol-scaled fixed 1.0p spread
(LBO levels; recorded-median came out 0.0p on raw pricing and inflated the
first run) / entry-bar recorded spread (ASB) + commission
(0.7p majors, 1.0p JPY pairs). All stats in equal-risk R units.

PASS bar (pre-committed): 2023+ PF >= 1.4 AND avgR > 0 in each full year
(2023, 2024, 2025) AND test (2025+) PF >= 1.2 with train (<2025) avgR > 0.

Read-only. Run: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < pair_extension_screen.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()

SPLIT = datetime(2025, 1, 1).date()
FULL_YEARS = (2023, 2024, 2025)


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def pip_of(sym):
    return 0.01 if "JPY" in sym else 0.0001


def comm_of(sym):
    return 1.0 if "JPY" in sym else 0.7


def stats(rows):
    """rows: list of (date, R)."""
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
        return f"{label:<14} (too few trades)"
    return (f"{label:<14} N={s['N']:>4} WR={s['WR']:>3.0f}% PF={s['PF']:>5.2f} "
            f"avgR={s['avgR']:>+6.3f} totR={s['totR']:>+7.1f} ddR={s['ddR']:>5.1f}")


def verdict(rows, label):
    all_s = stats(rows)
    if all_s is None:
        print(f"  -> {label}: too few trades — FAIL")
        return
    s23 = stats([x for x in rows if x[0].year >= 2023])
    tr = stats([x for x in rows if x[0] < SPLIT])
    te = stats([x for x in rows if x[0] >= SPLIT])
    yr_ok, yr_detail = True, []
    for y in FULL_YEARS:
        sy = stats([x for x in rows if x[0].year == y])
        if sy is None or sy["avgR"] <= 0:
            yr_ok = False
        val = "--" if sy is None else f"{sy['avgR']:+.2f}"
        yr_detail.append(f"{y}:{val}")
    print(fmt(all_s, "  ALL"))
    print(fmt(s23, "  2023+"))
    print(fmt(tr, "  train<2025"))
    print(fmt(te, "  test 2025+"))
    print(f"  per-year avgR: {'  '.join(yr_detail)}")
    c1 = s23 is not None and s23["PF"] >= 1.4
    c2 = yr_ok
    c3 = (tr is not None and tr["avgR"] > 0 and te is not None and te["PF"] >= 1.2)
    print(f"  -> {label}: PF2023+>=1.4:{'Y' if c1 else 'N'} "
          f"yearly+:{'Y' if c2 else 'N'} traintest:{'Y' if c3 else 'N'} "
          f"=> {'PASS' if (c1 and c2 and c3) else 'FAIL'}")


# ═══════════════ LONDON_BO screen ═══════════════
LBO_PAIRS = ["GBPUSD", "EURUSD", "GBPJPY", "EURGBP", "USDJPY"]
BAND_LO, BAND_HI = 10.0, 22.0  # GBPUSD-absolute; vol-scaled per pair
DAYS = (0, 1)

print("=" * 72)
print("LONDON_BO SCREEN (LIVE geometry, band 10-22p vol-scaled, Mon/Tue)")
print("=" * 72)

lbo_med = {}
lbo_bars = {}
for sym in LBO_PAIRS:
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
    if rates is None or len(rates) < 10000:
        print(f"{sym}: insufficient H1 data"); continue
    pip = pip_of(sym)
    bars = []
    for r in rates:
        t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)
        off = eu_dst_offset(t_broker - timedelta(hours=3))
        t_utc = t_broker - timedelta(hours=off)
        bars.append({"bh": t_broker.hour, "uh": t_utc.hour, "udate": t_utc.date(),
                     "uwd": t_utc.weekday(), "hi": r[2], "lo": r[3], "cl": r[4],
                     "sp": r[6] if len(r) > 6 else 0})
    lbo_bars[sym] = bars
    # median Mon/Tue asian range (for vol scaling) + median window spread
    sess = {}
    for b in bars:
        if b["uwd"] >= 5: continue
        sess.setdefault(b["udate"], []).append(b)
    rngs, sps = [], []
    for d, bs in sess.items():
        if datetime(d.year, d.month, d.day).weekday() not in DAYS: continue
        asian = [b for b in bs if b["uh"] < 7 and b["bh"] < 7]
        if len(asian) < 3: continue
        rngs.append((max(b["hi"] for b in asian) - min(b["lo"] for b in asian)) / pip)
        sps += [b["sp"] for b in bs if 8 <= b["uh"] < 13]
    lbo_med[sym] = (np.median(rngs), np.median(sps) / 10.0)  # points->pips /10 both 5- and 3-digit

gbp_med = lbo_med["GBPUSD"][0]
for sym in LBO_PAIRS:
    if sym not in lbo_bars: continue
    pip = pip_of(sym)
    med_rng, _ = lbo_med[sym]
    f = med_rng / gbp_med
    med_sp = 1.0 * f  # incumbent conservatism: GBPUSD validated at 1.0p fixed; scale by vol
    lo_b, hi_b = BAND_LO * f, BAND_HI * f
    comm = comm_of(sym)
    print(f"\n--- {sym}: med asian range {med_rng:.0f}p, vol-scale x{f:.2f} -> "
          f"band {lo_b:.0f}-{hi_b:.0f}p, spread {med_sp:.1f}p, comm {comm}p ---")
    sess = {}
    for b in lbo_bars[sym]:
        if b["uwd"] >= 5: continue
        sess.setdefault(b["udate"], {"bars": [], "wd": b["uwd"]})["bars"].append(b)
    rows = []
    for d in sorted(sess):
        s = sess[d]
        if s["wd"] not in DAYS: continue
        asian = [b for b in s["bars"] if b["uh"] < 7 and b["bh"] < 7]
        if len(asian) < 3: continue
        a_high = max(b["hi"] for b in asian)
        a_low = min(b["lo"] for b in asian)
        a_range = (a_high - a_low) / pip
        if not (lo_b <= a_range <= hi_b): continue
        london = [b for b in s["bars"] if 8 <= b["uh"] < 13]
        if not london: continue
        tp_dist = a_range * pip
        sp = med_sp * pip
        for i, b in enumerate(london):
            pnl = None
            if b["hi"] > a_high + sp:
                entry, sl, tp = a_high + sp, a_low - sp, a_high + sp + tp_dist
                risk = (entry - sl) / pip
                for rb in london[i:]:
                    if rb["lo"] <= sl: pnl = -risk - med_sp; break
                    if rb["hi"] >= tp: pnl = (tp - entry) / pip - med_sp; break
                if pnl is None: pnl = (london[-1]["cl"] - entry) / pip - med_sp
            elif b["lo"] < a_low - sp:
                entry, sl, tp = a_low - sp, a_high + sp, a_low - sp - tp_dist
                risk = (sl - entry) / pip
                for rb in london[i:]:
                    if rb["hi"] >= sl: pnl = -risk - med_sp; break
                    if rb["lo"] <= tp: pnl = (entry - tp) / pip - med_sp; break
                if pnl is None: pnl = (entry - london[-1]["cl"]) / pip - med_sp
            if pnl is not None:
                rows.append((d, (pnl - comm) / (a_range + 2 * med_sp + comm)))
                break
    verdict(rows, f"LBO/{sym}")

# ═══════════════ ASB screen ═══════════════
ASB_PAIRS = ["GBPJPY", "EURUSD", "USDJPY", "AUDJPY"]
MIN_PCT, MAX_PCT = 0.4, 1.0
MIN_BUF, BUF_PCT = 2.0, 0.10
TREND_THR_BASE = 30.0  # GBPJPY-absolute
SKIP_WD = (4, 5, 6)

print("\n" + "=" * 72)
print("ASB SCREEN (deployed live geometry + BE12, filters vol-scaled)")
print("=" * 72)

asb_data = {}
for sym in ASB_PAIRS:
    m15 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 99000))
    h1 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000))
    if len(m15) < 20000:
        print(f"{sym}: insufficient M15 data"); continue
    for df in (m15, h1):
        df["bt"] = pd.to_datetime(df["time"], unit="s")
    m15["bdate"] = m15["bt"].dt.date
    m15["bh"] = m15["bt"].dt.hour
    asb_data[sym] = (m15, h1.sort_values("bt").reset_index(drop=True))

# GBPJPY median ADR for trend-threshold scaling
adr_med = {}
for sym, (m15, _) in asb_data.items():
    pip = pip_of(sym)
    daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
    adr_med[sym] = float(((daily["hi"] - daily["lo"]) / pip).median())

for sym in ASB_PAIRS:
    if sym not in asb_data: continue
    m15, h1 = asb_data[sym]
    pip = pip_of(sym)
    comm = comm_of(sym)
    vf = adr_med[sym] / adr_med["GBPJPY"]
    thr = TREND_THR_BASE * vf
    min_buf = MIN_BUF * vf
    print(f"\n--- {sym}: med ADR {adr_med[sym]:.0f}p, vol-scale x{vf:.2f} -> "
          f"trend_thr {thr:.0f}p, min_buf {min_buf:.1f}p, comm {comm}p ---")
    daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
    daily["rng"] = daily["hi"] - daily["lo"]
    ddates = list(daily.index)
    by_date = {d: g.sort_values("bt").reset_index(drop=True)
               for d, g in m15.groupby("bdate")}
    rows = []
    for di, D in enumerate(ddates):
        g = by_date[D]
        rep = datetime(D.year, D.month, D.day, 7, tzinfo=timezone.utc)
        off = eu_dst_offset(rep)
        if rep.weekday() in SKIP_WD: continue
        asian = g[(g["bh"] >= 0) & (g["bh"] < 7)]
        if len(asian) < 16: continue
        hi, lo = float(asian["high"].max()), float(asian["low"].min())
        rng_p = (hi - lo) / pip
        prior = [d for d in ddates[max(0, di - 45):di]][-30:]
        rngs = daily.loc[prior, "rng"].dropna()
        if len(rngs) < 14: continue
        adr_p = float(rngs.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]) / pip
        if not (MIN_PCT * adr_p <= rng_p <= MAX_PCT * adr_p): continue
        buf = max(min_buf, BUF_PCT * rng_p)
        long_stop, short_stop = hi + buf * pip, lo - buf * pip
        cap_bt = pd.Timestamp(datetime(D.year, D.month, D.day, 7 + off))
        hh = h1[h1["bt"] < cap_bt]
        if len(hh) < 200: continue
        closes = hh["close"].tail(719).tolist()
        form = h1[h1["bt"] == cap_bt]
        closes.append(float(form["open"].iloc[0]) if len(form) else closes[-1])
        ema = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1]
        diff_p = (closes[-1] - ema) / pip
        place_long = diff_p >= -thr
        place_short = diff_p <= thr
        win = g[(g["bh"] >= 7 + off) & (g["bh"] < 11 + off)].reset_index(drop=True)
        if win.empty: continue
        risk_p = rng_p + 2 * buf
        tp_long = long_stop + rng_p * pip
        tp_short = short_stop - rng_p * pip
        entry_i, direction = None, None
        for i in range(len(win)):
            b = win.iloc[i]
            lt = place_long and b["high"] >= long_stop
            st = place_short and b["low"] <= short_stop
            if lt and st: entry_i, direction = i, "BOTH"; break
            if lt: entry_i, direction = i, "LONG"; break
            if st: entry_i, direction = i, "SHORT"; break
        if entry_i is None: continue
        sp = float(win.iloc[entry_i]["spread"]) / 10.0
        cost = sp + comm
        if direction == "BOTH":
            rows.append((D, (-risk_p - cost) / (risk_p + cost)))
            continue
        after = g[(g["bt"] >= win.iloc[entry_i]["bt"]) & (g["bh"] < 20 + off)]
        after = after.reset_index(drop=True)
        entry_px = long_stop if direction == "LONG" else short_stop
        sl_px = short_stop if direction == "LONG" else long_stop
        tp_px = tp_long if direction == "LONG" else tp_short
        be_h = 12 + off
        pnl = None
        for j in range(len(after)):
            b = after.iloc[j]
            eff_sl = entry_px if b["bh"] >= be_h else sl_px
            if direction == "LONG":
                if b["low"] <= eff_sl:
                    pnl = (eff_sl - entry_px) / pip - cost; break
                if b["high"] >= tp_px:
                    pnl = rng_p - cost; break
            else:
                if b["high"] >= eff_sl:
                    pnl = (entry_px - eff_sl) / pip - cost; break
                if b["low"] <= tp_px:
                    pnl = rng_p - cost; break
        if pnl is None:
            last_c = float(after.iloc[-1]["close"]) if len(after) else entry_px
            raw = (last_c - entry_px) if direction == "LONG" else (entry_px - last_c)
            pnl = raw / pip - cost
        rows.append((D, pnl / (risk_p + cost)))
    verdict(rows, f"ASB/{sym}")

mt5.shutdown()
