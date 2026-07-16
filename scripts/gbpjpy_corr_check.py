"""Correlation check: LBO/GBPJPY (candidate) vs ASB/GBPJPY (incumbent).

Both are breakout strategies on the same pair with overlapping morning
windows — before adopting LBO/GBPJPY, measure how correlated their trade
outcomes are. Simulates both (harnesses as validated: LBO LIVE geometry,
band 19-42p vol-scaled, 1.9p spread, 1.0p comm; ASB live geometry + BE12,
recorded spread) over the shared M15/H1 history, joins by date.

Outputs: overlap counts, direction agreement, Pearson corr of daily R on
both-traded days, and combined-vs-separate drawdown.

Read-only. Run: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < gbpjpy_corr_check.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

SYM = "GBPJPY"
PIP = 0.01

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


# ── LBO/GBPJPY sim (LIVE geometry, vol-scaled band 19-42p, 1.9p spread, 1p comm)
rates = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 50000)
bars = []
for r in rates:
    t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)
    off = eu_dst_offset(t_broker - timedelta(hours=3))
    t_utc = t_broker - timedelta(hours=off)
    bars.append({"bh": t_broker.hour, "uh": t_utc.hour, "udate": t_utc.date(),
                 "uwd": t_utc.weekday(), "hi": r[2], "lo": r[3], "cl": r[4]})
LO_B, HI_B, SPREAD_P, COMM_LBO = 19.0, 42.0, 1.9, 1.0
sess = {}
for b in bars:
    if b["uwd"] >= 5:
        continue
    sess.setdefault(b["udate"], {"bars": [], "wd": b["uwd"]})["bars"].append(b)
lbo = {}   # date -> (R, direction)
for d in sorted(sess):
    s = sess[d]
    if s["wd"] not in (0, 1):
        continue
    asian = [b for b in s["bars"] if b["uh"] < 7 and b["bh"] < 7]
    if len(asian) < 3:
        continue
    a_high = max(b["hi"] for b in asian)
    a_low = min(b["lo"] for b in asian)
    a_range = (a_high - a_low) / PIP
    if not (LO_B <= a_range <= HI_B):
        continue
    london = [b for b in s["bars"] if 8 <= b["uh"] < 13]
    if not london:
        continue
    tp_dist = a_range * PIP
    sp = SPREAD_P * PIP
    for i, b in enumerate(london):
        pnl, direc = None, None
        if b["hi"] > a_high + sp:
            direc = "LONG"
            entry, sl, tp = a_high + sp, a_low - sp, a_high + sp + tp_dist
            risk = (entry - sl) / PIP
            for rb in london[i:]:
                if rb["lo"] <= sl: pnl = -risk - SPREAD_P; break
                if rb["hi"] >= tp: pnl = (tp - entry) / PIP - SPREAD_P; break
            if pnl is None: pnl = (london[-1]["cl"] - entry) / PIP - SPREAD_P
        elif b["lo"] < a_low - sp:
            direc = "SHORT"
            entry, sl, tp = a_low - sp, a_high + sp, a_low - sp - tp_dist
            risk = (sl - entry) / PIP
            for rb in london[i:]:
                if rb["hi"] >= sl: pnl = -risk - SPREAD_P; break
                if rb["lo"] <= tp: pnl = (entry - tp) / PIP - SPREAD_P; break
            if pnl is None: pnl = (entry - london[-1]["cl"]) / PIP - SPREAD_P
        if pnl is not None:
            lbo[d] = ((pnl - COMM_LBO) / (a_range + 2 * SPREAD_P + COMM_LBO), direc)
            break

# ── ASB/GBPJPY sim (live geometry + BE12, recorded spread, 1p comm)
m15 = pd.DataFrame(mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, 99000))
h1 = pd.DataFrame(mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 99000))
for df in (m15, h1):
    df["bt"] = pd.to_datetime(df["time"], unit="s")
m15["bdate"] = m15["bt"].dt.date
m15["bh"] = m15["bt"].dt.hour
h1 = h1.sort_values("bt").reset_index(drop=True)
daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
daily["rng"] = daily["hi"] - daily["lo"]
ddates = list(daily.index)
by_date = {d: g.sort_values("bt").reset_index(drop=True) for d, g in m15.groupby("bdate")}
asb = {}   # date -> (R, direction)
for di, D in enumerate(ddates):
    g = by_date[D]
    rep = datetime(D.year, D.month, D.day, 7, tzinfo=timezone.utc)
    off = eu_dst_offset(rep)
    if rep.weekday() in (4, 5, 6):
        continue
    asian = g[(g["bh"] >= 0) & (g["bh"] < 7)]
    if len(asian) < 16:
        continue
    hi, lo = float(asian["high"].max()), float(asian["low"].min())
    rng_p = (hi - lo) / PIP
    prior = [d for d in ddates[max(0, di - 45):di]][-30:]
    rngs = daily.loc[prior, "rng"].dropna()
    if len(rngs) < 14:
        continue
    adr_p = float(rngs.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]) / PIP
    if not (0.4 * adr_p <= rng_p <= 1.0 * adr_p):
        continue
    buf = max(2.0, 0.10 * rng_p)
    long_stop, short_stop = hi + buf * PIP, lo - buf * PIP
    cap_bt = pd.Timestamp(datetime(D.year, D.month, D.day, 7 + off))
    hh = h1[h1["bt"] < cap_bt]
    if len(hh) < 200:
        continue
    closes = hh["close"].tail(719).tolist()
    form = h1[h1["bt"] == cap_bt]
    closes.append(float(form["open"].iloc[0]) if len(form) else closes[-1])
    ema = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1]
    diff_p = (closes[-1] - ema) / PIP
    place_long, place_short = diff_p >= -30.0, diff_p <= 30.0
    win = g[(g["bh"] >= 7 + off) & (g["bh"] < 11 + off)].reset_index(drop=True)
    if win.empty:
        continue
    risk_p = rng_p + 2 * buf
    tp_long, tp_short = long_stop + rng_p * PIP, short_stop - rng_p * PIP
    entry_i, direction = None, None
    for i in range(len(win)):
        b = win.iloc[i]
        lt = place_long and b["high"] >= long_stop
        st = place_short and b["low"] <= short_stop
        if lt and st: entry_i, direction = i, "BOTH"; break
        if lt: entry_i, direction = i, "LONG"; break
        if st: entry_i, direction = i, "SHORT"; break
    if entry_i is None:
        continue
    sp = float(win.iloc[entry_i]["spread"]) / 10.0
    cost = sp + 1.0
    if direction == "BOTH":
        asb[D] = (-1.0, "BOTH")
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
            if b["low"] <= eff_sl: pnl = (eff_sl - entry_px) / PIP - cost; break
            if b["high"] >= tp_px: pnl = rng_p - cost; break
        else:
            if b["high"] >= eff_sl: pnl = (entry_px - eff_sl) / PIP - cost; break
            if b["low"] <= tp_px: pnl = rng_p - cost; break
    if pnl is None:
        last_c = float(after.iloc[-1]["close"]) if len(after) else entry_px
        raw = (last_c - entry_px) if direction == "LONG" else (entry_px - last_c)
        pnl = raw / PIP - cost
    asb[D] = (pnl / (risk_p + cost), direction)

# ── Join & report (restrict LBO to ASB's data span for fairness)
span_lo = min(asb.keys())
lbo = {d: v for d, v in lbo.items() if d >= span_lo}
both = sorted(set(lbo) & set(asb))
print(f"span: {span_lo} .. now")
print(f"LBO/GBPJPY trades: {len(lbo)}   ASB/GBPJPY trades: {len(asb)}   "
      f"same-day overlap: {len(both)}")
lbo_mt = {d for d in lbo}
asb_mt = {d for d in asb if datetime(d.year, d.month, d.day).weekday() in (0, 1)}
print(f"(ASB Mon/Tue trades: {len(asb_mt)} — LBO can only overlap these)")
if both:
    a = np.array([lbo[d][0] for d in both])
    b = np.array([asb[d][0] for d in both])
    corr = np.corrcoef(a, b)[0, 1] if len(both) > 2 else float("nan")
    same_dir = sum(1 for d in both if lbo[d][1] == asb[d][1])
    both_loss = sum(1 for d in both if lbo[d][0] < 0 and asb[d][0] < 0)
    both_win = sum(1 for d in both if lbo[d][0] > 0 and asb[d][0] > 0)
    print(f"on overlap days: corr(R)={corr:+.2f}  same-direction {same_dir}/{len(both)}"
          f"  both-win {both_win}  both-lose {both_loss}")
    comb = a + b
    print(f"overlap-day combined R: mean {comb.mean():+.3f}  worst {comb.min():+.2f}")

# Portfolio effect: daily R series (0 when no trade), separate vs combined
alldays = sorted(set(lbo) | set(asb))
ra = np.array([lbo.get(d, (0, None))[0] for d in alldays])
rb = np.array([asb.get(d, (0, None))[0] for d in alldays])


def ddof(x):
    eq = np.cumsum(x)
    return (np.maximum.accumulate(eq) - eq).max()


print(f"\nASB alone:      totR {rb.sum():+7.1f}  ddR {ddof(rb):5.1f}")
print(f"LBO alone:      totR {ra.sum():+7.1f}  ddR {ddof(ra):5.1f}")
print(f"combined 1x+1x: totR {(ra+rb).sum():+7.1f}  ddR {ddof(ra+rb):5.1f}")
mt5.shutdown()
