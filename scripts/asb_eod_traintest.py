"""ASB EOD-exit refinement, train/test split. GBPJPY, deployed live geometry.

Same simulation as scripts/asb_live_geometry_bt.py (fidelity-verified),
but each trade's exit is evaluated under 8 variants:
  EOD12 / EOD14 / EOD16 / EOD18 / EOD20(=deployed baseline)
  BE12 / BE14 / BE16 (move SL to entry at that true-UTC hour; TP kept;
                      final close 20:00)

Discipline: train = trades dated < 2025-01-01, test = >= 2025-01-01.
Winner selected on TRAIN avgR only; TEST is read once for the winner and
the baseline. Pre-committed adoption rule: winner must beat baseline on
BOTH train and test (avgR and PF) to be adopted.

Read-only. Run: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < asb_eod_traintest.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

SYM = "GBPJPY"
PIP, POINT = 0.01, 0.001
MIN_PCT, MAX_PCT = 0.4, 1.0
MIN_BUF, BUF_PCT = 2.0, 0.10
TREND_THR = 30.0
COMM = 1.0
SKIP_WD = (4, 5, 6)
SPLIT = datetime(2025, 1, 1).date()

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()

m15 = pd.DataFrame(mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, 99000))
h1 = pd.DataFrame(mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 99000))
for df in (m15, h1):
    df["bt"] = pd.to_datetime(df["time"], unit="s")
m15["bdate"] = m15["bt"].dt.date
m15["bh"] = m15["bt"].dt.hour
h1 = h1.sort_values("bt").reset_index(drop=True)


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
daily["rng"] = daily["hi"] - daily["lo"]
ddates = list(daily.index)
m15_by_date = {d: g.sort_values("bt").reset_index(drop=True)
               for d, g in m15.groupby("bdate")}

VARIANTS = ["EOD12", "EOD14", "EOD16", "EOD18", "EOD20", "BE12", "BE14", "BE16"]
rows = []  # one per trade: date + pnl/risk under each variant

for di, D in enumerate(ddates):
    g = m15_by_date[D]
    rep = datetime(D.year, D.month, D.day, 7, tzinfo=timezone.utc)
    off = eu_dst_offset(rep)
    if rep.weekday() in SKIP_WD:
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
    if not (MIN_PCT * adr_p <= rng_p <= MAX_PCT * adr_p):
        continue
    buf = max(MIN_BUF, BUF_PCT * rng_p)
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
    place_long = diff_p >= -TREND_THR
    place_short = diff_p <= TREND_THR

    win = g[(g["bh"] >= 7 + off) & (g["bh"] < 11 + off)].reset_index(drop=True)
    if win.empty:
        continue
    risk_p = rng_p + 2 * buf
    tp_long = long_stop + rng_p * PIP
    tp_short = short_stop - rng_p * PIP
    entry_i, direction = None, None
    for i in range(len(win)):
        b = win.iloc[i]
        lt = place_long and b["high"] >= long_stop
        st = place_short and b["low"] <= short_stop
        if lt and st:
            entry_i, direction = i, "BOTH"; break
        if lt:
            entry_i, direction = i, "LONG"; break
        if st:
            entry_i, direction = i, "SHORT"; break
    if entry_i is None:
        continue
    sp = float(win.iloc[entry_i]["spread"]) / 10.0
    cost = sp + COMM
    row = {"date": D}
    if direction == "BOTH":
        for v in VARIANTS:
            row[v] = (-risk_p - cost, risk_p + cost)
        rows.append(row)
        continue

    after = g[(g["bt"] >= win.iloc[entry_i]["bt"]) & (g["bh"] < 20 + off)]
    after = after.reset_index(drop=True)
    entry_px = long_stop if direction == "LONG" else short_stop
    sl_px = short_stop if direction == "LONG" else long_stop
    tp_px = tp_long if direction == "LONG" else tp_short

    for v in VARIANTS:
        if v.startswith("EOD"):
            cut_h = int(v[3:]) + off
            be_h = None
        else:
            cut_h = 20 + off
            be_h = int(v[2:]) + off
        pnl = None
        for j in range(len(after)):
            b = after.iloc[j]
            if b["bh"] >= cut_h:
                # exit at this bar's open (first cycle past the cutoff)
                raw = (b["open"] - entry_px) if direction == "LONG" else (entry_px - b["open"])
                pnl = raw / PIP - cost
                break
            eff_sl = sl_px
            if be_h is not None and b["bh"] >= be_h:
                eff_sl = entry_px
            if direction == "LONG":
                if b["low"] <= eff_sl:
                    raw = (eff_sl - entry_px)
                    pnl = raw / PIP - cost; break
                if b["high"] >= tp_px:
                    pnl = rng_p - cost; break
            else:
                if b["high"] >= eff_sl:
                    raw = (entry_px - eff_sl)
                    pnl = raw / PIP - cost; break
                if b["low"] <= tp_px:
                    pnl = rng_p - cost; break
        if pnl is None:
            last_c = float(after.iloc[-1]["close"]) if len(after) else entry_px
            raw = (last_c - entry_px) if direction == "LONG" else (entry_px - last_c)
            pnl = raw / PIP - cost
        row[v] = (pnl, risk_p + cost)
    rows.append(row)

print(f"trades: {len(rows)}  train(<{SPLIT}): "
      f"{sum(1 for r in rows if r['date'] < SPLIT)}  test: "
      f"{sum(1 for r in rows if r['date'] >= SPLIT)}")


def stats(vals):
    r = np.array([p / k for p, k in vals])
    if len(r) < 5:
        return None
    w = (r > 0).sum()
    gp = r[r > 0].sum() if w else 0.0
    gl = abs(r[r <= 0].sum()) or 0.001
    eq = np.cumsum(r)
    dd = (np.maximum.accumulate(eq) - eq).max()
    return dict(N=len(r), WR=w / len(r) * 100, PF=gp / gl, avgR=r.mean(),
                totR=r.sum(), ddR=dd)


print("\n===== TRAIN (2022-07 .. 2024-12) =====")
print(f"{'variant':<8}{'N':>5}{'WR':>6}{'PF':>7}{'avgR':>9}{'totR':>8}{'ddR':>7}")
train_res = {}
for v in VARIANTS:
    s = stats([r[v] for r in rows if r["date"] < SPLIT])
    train_res[v] = s
    print(f"{v:<8}{s['N']:>5}{s['WR']:>5.0f}%{s['PF']:>7.2f}{s['avgR']:>+9.3f}"
          f"{s['totR']:>+8.1f}{s['ddR']:>7.1f}")

winner = max(VARIANTS, key=lambda v: train_res[v]["avgR"])
print(f"\nTRAIN WINNER (by avgR): {winner}")

print("\n===== TEST (2025-01 .. now) — winner + baseline ONLY =====")
for v in (winner, "EOD20") if winner != "EOD20" else ("EOD20",):
    s = stats([r[v] for r in rows if r["date"] >= SPLIT])
    print(f"{v:<8}{s['N']:>5}{s['WR']:>5.0f}%{s['PF']:>7.2f}{s['avgR']:>+9.3f}"
          f"{s['totR']:>+8.1f}{s['ddR']:>7.1f}")
mt5.shutdown()
