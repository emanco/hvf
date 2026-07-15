"""ASB honest backtest of the DEPLOYED live geometry — GBPJPY.

Replicates what the live code actually does (2026-07-02 audit finding:
bar labels are broker time, so the "00-07 UTC" Asian window is really
broker 00-07 = true UTC ~21:00-04:00 in summer, and the bracket is armed
at true UTC 07:00 — ~3h after the labeled range ends):

  - Range: M15 bars LABELED [D 00:00, D 07:00) broker time (>=16 bars).
  - ADR(14): Wilder EWM (alpha=1/14) over daily H-L of the last 30
    broker-label days before D (mirrors live's 720-bar H1 fetch).
  - Filters: 0.4*ADR <= range <= 1.0*ADR. Skip true-UTC Fri/Sat/Sun.
  - Buffer = max(2p, 0.10*range). BUY_STOP=high+buf, SELL_STOP=low-buf,
    SL=opposite stop, TP=1.0*range from stop. OCO — first fill wins.
  - Trend filter (deployed): H1 EMA200 (last 720 closes incl. forming-bar
    stub = open of capture-hour bar); price-EMA > +30p -> long only,
    < -30p -> short only.
  - Fill window: true UTC [07:00, 11:00) = broker [7+off, 11+off).
  - EOD force-close true 20:00. Same-bar SL/TP ambiguity -> SL (against us).
  - Costs: entry-bar recorded spread + 1.0p commission (JPY pip ~ $6.8/lot,
    $7 round trip). All results also in R units (risk = range + 2*buf + costs).

Fidelity targets from live logs (must reproduce):
  2026-07-07 range=52.9p ADR=108.0p BUY_STOP=217.267
  2026-07-08 range=61.6p ADR=110.9p BUY_STOP=216.933 (LONG filled @216.933)
  2026-07-13 BUY_STOP=216.904 (price already through -> instant/rejected)
  2026-07-14, 2026-07-15 range filter rejected

Read-only. Run: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < asb_live_geometry_bt.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

SYM = "GBPJPY"
PIP = 0.01
POINT = 0.001
MIN_PCT, MAX_PCT = 0.4, 1.0
MIN_BUF, BUF_PCT = 2.0, 0.10
TREND_THR = 30.0
COMM = 1.0  # pips
SKIP_WD = (4, 5, 6)  # true-UTC Fri/Sat/Sun

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()

m15 = pd.DataFrame(mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, 99000))
h1 = pd.DataFrame(mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 99000))
for df in (m15, h1):
    df["bt"] = pd.to_datetime(df["time"], unit="s")  # broker-labeled
m15["bdate"] = m15["bt"].dt.date
m15["bh"] = m15["bt"].dt.hour
print(f"M15 {len(m15)} bars from {m15['bt'].iloc[0]}  H1 {len(h1)} bars from {h1['bt'].iloc[0]}")


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


# Daily H-L per broker-label date (for ADR)
daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
daily["rng"] = daily["hi"] - daily["lo"]
ddates = list(daily.index)

# H1 closes indexed for trend filter
h1 = h1.sort_values("bt").reset_index(drop=True)

m15_by_date = {d: g.sort_values("bt").reset_index(drop=True)
               for d, g in m15.groupby("bdate")}

trades = []   # dicts
skips = {"weekday": 0, "bars": 0, "adr": 0, "filter": 0, "nofill": 0}
FID_DATES = {datetime(2026, 7, 7).date(), datetime(2026, 7, 8).date(),
             datetime(2026, 7, 13).date(), datetime(2026, 7, 14).date(),
             datetime(2026, 7, 15).date(), datetime(2026, 6, 16).date(),
             datetime(2026, 6, 18).date()}

for di, D in enumerate(ddates):
    g = m15_by_date[D]
    # capture moment: true UTC 07:00 on date D -> offset from a rep. time
    rep = datetime(D.year, D.month, D.day, 7, tzinfo=timezone.utc)
    off = eu_dst_offset(rep)
    if rep.weekday() in SKIP_WD:
        skips["weekday"] += 1
        continue
    asian = g[(g["bh"] >= 0) & (g["bh"] < 7)]
    if len(asian) < 16:
        skips["bars"] += 1
        continue
    hi, lo = float(asian["high"].max()), float(asian["low"].min())
    rng_p = (hi - lo) / PIP
    # ADR over last 30 broker days before D (mirror live 720-bar fetch)
    prior = [d for d in ddates[max(0, di - 45):di]][-30:]
    rngs = daily.loc[prior, "rng"].dropna()
    if len(rngs) < 14:
        skips["adr"] += 1
        continue
    adr_p = float(rngs.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]) / PIP
    fid = D in FID_DATES
    ok = (MIN_PCT * adr_p <= rng_p <= MAX_PCT * adr_p)
    buf = max(MIN_BUF, BUF_PCT * rng_p)
    long_stop = hi + buf * PIP
    short_stop = lo - buf * PIP
    if fid:
        print(f"[FID] {D} range={rng_p:.1f}p ADR={adr_p:.1f}p "
              f"BUY_STOP={long_stop:.3f} SELL_STOP={short_stop:.3f} "
              f"filter={'PASS' if ok else 'REJECT'}")
    if not ok:
        skips["filter"] += 1
        continue

    # Trend filter: EMA200 over last 720 H1 closes ending before capture,
    # with forming-bar stub (open of capture-hour bar) appended.
    cap_bt = pd.Timestamp(datetime(D.year, D.month, D.day, 7 + off))
    hh = h1[h1["bt"] < cap_bt]
    if len(hh) < 200:
        skips["adr"] += 1
        continue
    closes = hh["close"].tail(719).tolist()
    form = h1[h1["bt"] == cap_bt]
    stub = float(form["open"].iloc[0]) if len(form) else closes[-1]
    closes.append(stub)
    ema = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1]
    diff_p = (closes[-1] - ema) / PIP
    place_long, place_short = True, True
    if diff_p > TREND_THR:
        place_short = False
    elif diff_p < -TREND_THR:
        place_long = False

    # Fill window: broker labels [7+off, 11+off)
    win = g[(g["bh"] >= 7 + off) & (g["bh"] < 11 + off)]
    if win.empty:
        skips["nofill"] += 1
        continue
    win = win.reset_index(drop=True)
    risk_p = rng_p + 2 * buf
    tp_long = long_stop + rng_p * PIP
    tp_short = short_stop - rng_p * PIP
    entry_i, direction = None, None
    for i in range(len(win)):
        b = win.iloc[i]
        lt = place_long and b["high"] >= long_stop
        st = place_short and b["low"] <= short_stop
        if lt and st:
            entry_i, direction = i, "BOTH"
            break
        if lt:
            entry_i, direction = i, "LONG"
            break
        if st:
            entry_i, direction = i, "SHORT"
            break
    if entry_i is None:
        skips["nofill"] += 1
        continue
    sp = float(win.iloc[entry_i]["spread"]) / 10.0  # points -> pips
    cost = sp + COMM
    if direction == "BOTH":
        pnl = -risk_p - cost
        reason = "SPAN_SL"
    else:
        # walk M15 to EOD (true 20:00 = broker 20+off)
        after = g[(g["bt"] >= win.iloc[entry_i]["bt"]) & (g["bh"] < 20 + off)]
        after = after.reset_index(drop=True)
        pnl, reason = None, None
        for j in range(len(after)):
            b = after.iloc[j]
            if direction == "LONG":
                if b["low"] <= short_stop:      # SL first (against us)
                    pnl, reason = -risk_p - cost, "SL"; break
                if b["high"] >= tp_long:
                    pnl, reason = rng_p - cost, "TP"; break
            else:
                if b["high"] >= long_stop:
                    pnl, reason = -risk_p - cost, "SL"; break
                if b["low"] <= tp_short:
                    pnl, reason = rng_p - cost, "TP"; break
        if pnl is None:
            last_c = float(after.iloc[-1]["close"]) if len(after) else (
                long_stop if direction == "LONG" else short_stop)
            raw = (last_c - long_stop) if direction == "LONG" else (short_stop - last_c)
            pnl, reason = raw / PIP - cost, "EOD"
    if fid:
        print(f"[FID] {D} -> {direction} {reason} pnl={pnl:+.1f}p")
    trades.append({"date": D, "year": D.year, "dir": direction, "pnl": pnl,
                   "risk": risk_p + cost, "reason": reason,
                   "trend": diff_p, "rng": rng_p})

print(f"\nskips: {skips}")
tr = pd.DataFrame(trades)
tr["R"] = tr["pnl"] / tr["risk"]


def stats(df, label):
    if len(df) < 5:
        print(f"{label:<28} N={len(df)} (too few)")
        return
    r = df["R"].values
    w = (r > 0).sum()
    gp = r[r > 0].sum() if w else 0.0
    gl = abs(r[r <= 0].sum()) or 0.001
    eq = np.cumsum(r)
    dd = (np.maximum.accumulate(eq) - eq).max()
    print(f"{label:<28} N={len(df):>4} WR={w/len(r)*100:>3.0f}% PF={gp/gl:>5.2f} "
          f"avgR={r.mean():>+6.3f} totR={r.sum():>+7.1f} ddR={dd:>5.1f} "
          f"| pips tot={df['pnl'].sum():>+7.0f}")


print("\n===== DEPLOYED (trend filter ON) =====")
stats(tr, "ALL")
stats(tr[tr["year"] >= 2023], "2023+")
print("\n-- per year --")
for y in sorted(tr["year"].unique()):
    stats(tr[tr["year"] == y], f"  {y}")
print("\n-- by exit --")
for rs in tr["reason"].unique():
    stats(tr[tr["reason"] == rs], f"  {rs}")
mt5.shutdown()
