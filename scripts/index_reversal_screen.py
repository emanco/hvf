"""Short-term reversal on index CFDs -- pre-committed screen (VPS, read-only).

HYPOTHESIS (documented, not invented here): equity indices mean-revert at a
2-5 day horizon. Buying short-term oversold conditions *within an uptrend* has
positive expectancy. This is the natural complement to BTC_DONCHIAN: trend
earns in trending regimes, short-term reversal earns in the chop that stops
trend out. It is also the daily-horizon cousin of NIGHT_TIDE, our second-best
validated edge.

WHY THIS FAMILY IS WORTH A LOOK AT ALL (vs the ones we killed)
  Every intraday breakout we retired died on the friction wall: ~1.7p round
  trip against a ~15p stop = ~0.11R/trade. Here the stop is 3xATR20 daily
  (US500: ~3.7% of price) and the spread is ~1bp, so friction is ~0.003R.
  The edge does not have to clear a cost wall -- it only has to exist.

COSTS -- first hvf backtest to model FINANCING
  Discovered 2026-07-29: no existing hvf sim charges swap, and index longs pay
  8-16%/yr of notional. This strategy is LONG ONLY, i.e. always on the paying
  side, and holds several days. Swap is charged per CALENDAR night held (which
  naturally prices the weekend, the thing triple-swap Wednesday exists to
  cover). Ignoring it would be the same class of error as the blind-gap fill.
  Spread is floored at the live snapshot -- IC's recorded per-bar spread
  medians to ~0 on raw feeds and would understate cost badly.

PRE-COMMITTED before any result was seen
  Primary cell:  RSI(2) < 10, close > SMA200, long only
                 exit when RSI(2) > 70, or after 10 days, or 3xATR20 stop
  Universe:      the 8 IC indices, all of them, no post-hoc dropping
  Periods:       scored 2017+, train 2017-2021, held-out test 2022+
  Entry timing:  reported at signal close AND next open. Verdict on next-OPEN
                 (the pessimistic one) -- we have been burned by entry timing
                 before (BTC_DONCHIAN's 00:01 lag cost a third of its edge).
  PASS requires ALL of:
     full  PF >= 1.30, N >= 40, avgR > 0
     test  PF >= 1.15, avgR > 0
     sign  >= 5 of 8 instruments with positive avgR
  Neighbourhood is reported for ROBUSTNESS ONLY, never for selection. If only
  the primary cell works it is noise; if EVERY cell works suspect a mechanical
  artifact (the BE12 lesson) -- we want "most of the neighbourhood, degrading
  smoothly away from centre".

SANITY GATE
  No incumbent exists for this family, so instead the gate pins buy-and-hold:
  the simulator's own bars must reproduce each index's actual total return over
  the window. That catches data/plumbing/clock bugs, which is what the
  incumbent pins catch elsewhere.

Usage:
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -u -" < scripts/index_reversal_screen.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

SYMS = ["US500", "USTEC", "US30", "DE40", "F40", "UK100", "JP225", "HK50"]

# ---- primary cell (pre-committed) ----
RSI_P, RSI_ENTRY, RSI_EXIT = 2, 10, 70
SMA_P = 200
ATR_P, STOP_MULT = 20, 3.0
MAX_HOLD = 10

# ---- neighbourhood, for robustness reporting only ----
NEIGHBOURHOOD = [(2, 5, 70), (2, 10, 70), (2, 15, 70), (2, 20, 70),
                 (3, 10, 70), (4, 10, 70), (2, 10, 60), (2, 10, 80)]

SCORE_FROM_YEAR = 2017
TRAIN_YEARS = (2017, 2021)
TEST_FROM_YEAR = 2022

BAR_FULL_PF, BAR_FULL_N = 1.30, 40
BAR_TEST_PF = 1.15
SIGN_BAR = 5

RISK_PCT = 1.0
BARS = 99000

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


def load_d1(sym):
    """H1 -> broker-day D1, matching the convention in the Donchian scripts."""
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, BARS)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")
    info = mt5.symbol_info(sym)
    df["spread_price"] = df["spread"] * info.point
    df = df.iloc[:-1]
    df["bdate"] = df["tb"].dt.date
    d1 = df.groupby("bdate").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        close_spread=("spread_price", "last")).reset_index()
    d1["next_open"] = d1["open"].shift(-1)
    return d1


def spec_for(sym, d1):
    """Cost + financing spec from live MT5 tick specs."""
    i = mt5.symbol_info(sym)
    px = float(d1["close"].median())
    live_sp = i.spread * i.point
    m = i.swap_mode
    if m == 1:
        swap_px = abs(i.swap_long) * i.point
    elif m in (2, 3, 4):
        swap_px = abs(i.swap_long) / i.trade_contract_size
    elif m in (5, 6):
        swap_px = px * abs(i.swap_long) / 100.0 / 360.0
    else:
        swap_px = 0.0
    return {"sym": sym, "live_spread": live_sp, "swap_px": swap_px,
            "swap_mode": m, "px": px}


def rsi(close, p):
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1.0 / p, adjust=False).mean()
    ad = dn.ewm(alpha=1.0 / p, adjust=False).mean()
    rs = au / ad.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.fillna(100.0)


def atr(d1, p):
    h, l, c = d1["high"], d1["low"], d1["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / p, adjust=False).mean()


def simulate(spec, d1, rsi_p, rsi_entry, rsi_exit, entry_mode,
             cost_mode="real", charge_swap=True, since_year=None, until_year=None):
    """Long-only short-term reversal. Returns list of trade records (R units)."""
    df = d1.copy()
    df["rsi"] = rsi(df["close"], rsi_p)
    df["sma"] = df["close"].rolling(SMA_P).mean()
    df["atr"] = atr(df, ATR_P)
    rows = df.to_dict("records")
    recs = []
    n = len(rows)
    i = 0
    while i < n - 1:
        row = rows[i]
        yr = row["bdate"].year
        if (since_year and yr < since_year) or (until_year and yr > until_year):
            i += 1
            continue
        if pd.isna(row["sma"]) or pd.isna(row["atr"]) or row["atr"] <= 0:
            i += 1
            continue
        # --- entry condition, evaluated on this bar's close ---
        if not (row["rsi"] < rsi_entry and row["close"] > row["sma"]):
            i += 1
            continue

        if entry_mode == "close":
            ep = row["close"]
            start = i + 1
        else:
            ep = rows[i + 1]["open"]
            if pd.isna(ep):
                i += 1
                continue
            start = i + 1
        sig_atr = row["atr"]
        stop = ep - STOP_MULT * sig_atr
        isd = ep - stop
        if isd <= 0:
            i += 1
            continue

        sp = max(row["close_spread"] if not pd.isna(row["close_spread"]) else 0.0,
                 spec["live_spread"])
        if cost_mode == "stress":
            sp *= 2.0
        elif cost_mode == "nospread":
            sp = 0.0

        xp, xi, reason = None, None, None
        for j in range(start, n):
            b = rows[j]
            if b["low"] <= stop:
                xp, xi, reason = min(b["open"], stop), j, "stop"
                break
            if b["rsi"] > rsi_exit:
                xp, xi, reason = b["close"], j, "rsi"
                break
            if (j - start + 1) >= MAX_HOLD:
                xp, xi, reason = b["close"], j, "time"
                break
        if xp is None:
            break  # ran out of history with the position open

        nights = (rows[xi]["bdate"] - row["bdate"]).days
        swap_cost = spec["swap_px"] * nights if charge_swap else 0.0
        pnl_px = (xp - ep) - sp - swap_cost
        recs.append({"sym": spec["sym"], "date": row["bdate"], "R": pnl_px / isd,
                     "nights": nights, "reason": reason,
                     "swap_R": swap_cost / isd, "sp_R": sp / isd})
        i = xi + 1
    return recs


def pooled(recs):
    if not recs:
        return None
    r = np.array([x["R"] for x in recs])
    gp = r[r > 0].sum()
    gl = abs(r[r <= 0].sum()) or 1e-9
    return {"n": len(r), "pf": gp / gl, "avgR": r.mean(), "medR": float(np.median(r)),
            "wr": (r > 0).mean() * 100, "totR": r.sum(),
            "nights": np.mean([x["nights"] for x in recs]),
            "swapR": np.mean([x["swap_R"] for x in recs])}


def fmt(s):
    if not s:
        return "no trades"
    return ("N=%3d WR=%3.0f%% PF=%5.2f avgR=%+.3f medR=%+.3f totR=%+7.1f"
            % (s["n"], s["wr"], s["pf"], s["avgR"], s["medR"], s["totR"]))


# ----------------------------------------------------------------- sanity gate
print("=" * 78)
print("SANITY GATE -- buy & hold reproduced from the simulator's own bars")
print("(no incumbent exists for this family; this pins the data plumbing)")
print("=" * 78)
DATA = {}
for s in SYMS:
    d1 = load_d1(s)
    if d1 is None or len(d1) < 400:
        print("  %-7s NO DATA -- excluded" % s)
        continue
    sub = d1[d1["bdate"].apply(lambda x: x.year >= SCORE_FROM_YEAR)]
    bh = (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100
    print("  %-7s %s -> %s  %5d bars  buy&hold %+8.1f%%  px %.1f -> %.1f"
          % (s, sub["bdate"].iloc[0], sub["bdate"].iloc[-1], len(sub), bh,
             sub["close"].iloc[0], sub["close"].iloc[-1]))
    DATA[s] = (spec_for(s, d1), d1)
if not DATA:
    print("no data at all -- aborting")
    mt5.shutdown()
    sys.exit(1)
print("\n  financing charged per calendar night held (long side):")
for s, (sp, _d) in DATA.items():
    print("     %-7s swap %.5f price units/night (mode %d) = %.2f bp/night"
          % (s, sp["swap_px"], sp["swap_mode"], sp["swap_px"] / sp["px"] * 1e4))

# ------------------------------------------------------------------- main runs
def run(entry_mode, charge_swap=True, cost_mode="real", label=""):
    print("\n" + "=" * 78)
    print("PRIMARY CELL  RSI(%d)<%d & close>SMA%d | exit RSI>%d / %dd / %.0fxATR%d"
          % (RSI_P, RSI_ENTRY, SMA_P, RSI_EXIT, MAX_HOLD, STOP_MULT, ATR_P))
    print("entry=%s  cost=%s  swap=%s   %s"
          % (entry_mode, cost_mode, "ON" if charge_swap else "OFF", label))
    print("=" * 78)
    allr, per = [], {}
    for s, (sp, d1) in DATA.items():
        full = simulate(sp, d1, RSI_P, RSI_ENTRY, RSI_EXIT, entry_mode,
                        cost_mode, charge_swap, since_year=SCORE_FROM_YEAR)
        tr = simulate(sp, d1, RSI_P, RSI_ENTRY, RSI_EXIT, entry_mode,
                      cost_mode, charge_swap,
                      since_year=TRAIN_YEARS[0], until_year=TRAIN_YEARS[1])
        te = simulate(sp, d1, RSI_P, RSI_ENTRY, RSI_EXIT, entry_mode,
                      cost_mode, charge_swap, since_year=TEST_FROM_YEAR)
        per[s] = {"full": pooled(full), "train": pooled(tr), "test": pooled(te)}
        allr.append((s, full, tr, te))
        print("  %-7s full  %s" % (s, fmt(per[s]["full"])))
        print("  %-7s test  %s" % ("", fmt(per[s]["test"])))
    pf_all = pooled([r for _s, f, _t, _e in allr for r in f])
    pt_all = pooled([r for _s, _f, t, _e in allr for r in t])
    pe_all = pooled([r for _s, _f, _t, e in allr for r in e])
    print("\n  POOLED full   %s" % fmt(pf_all))
    print("  POOLED train  %s" % fmt(pt_all))
    print("  POOLED test   %s" % fmt(pe_all))
    if pf_all:
        print("  avg hold %.1f nights | avg swap %.3fR | avg spread %.4fR"
              % (pf_all["nights"], pf_all["swapR"],
                 np.mean([r["sp_R"] for _s, f, _t, _e in allr for r in f])))
    signs = [s for s in per if per[s]["full"] and per[s]["full"]["avgR"] > 0]
    print("  sign test: %d/%d instruments with positive avgR -> %s"
          % (len(signs), len(per), ", ".join(sorted(signs))))
    ok = (pf_all and pf_all["pf"] >= BAR_FULL_PF and pf_all["n"] >= BAR_FULL_N
          and pf_all["avgR"] > 0 and pe_all and pe_all["pf"] >= BAR_TEST_PF
          and pe_all["avgR"] > 0 and len(signs) >= SIGN_BAR)
    print("  VERDICT: %s" % ("PASS" if ok else "FAIL"))
    if not ok and pf_all and pe_all:
        why = []
        if pf_all["pf"] < BAR_FULL_PF: why.append("full PF %.2f<%.2f" % (pf_all["pf"], BAR_FULL_PF))
        if pf_all["n"] < BAR_FULL_N: why.append("N %d<%d" % (pf_all["n"], BAR_FULL_N))
        if pe_all["pf"] < BAR_TEST_PF: why.append("test PF %.2f<%.2f" % (pe_all["pf"], BAR_TEST_PF))
        if pe_all["avgR"] <= 0: why.append("test avgR %+.3f" % pe_all["avgR"])
        if len(signs) < SIGN_BAR: why.append("sign %d/%d" % (len(signs), len(per)))
        print("           (%s)" % "; ".join(why))
    return ok, pf_all, pe_all


ok_open, _, _ = run("open", True, "real", "<-- THE VERDICT (pessimistic entry)")
run("close", True, "real", "context: entry at signal close")
run("open", False, "real", "context: swap OFF, to size the financing drag")

# ------------------------------------------------------- neighbourhood (robust)
print("\n" + "=" * 78)
print("NEIGHBOURHOOD (robustness only -- NOT for selection)")
print("entry=open, real cost, swap ON. Want most cells positive and degrading")
print("smoothly. All cells winning => suspect artifact; only centre => noise.")
print("=" * 78)
print("  %-18s %20s %20s" % ("cell", "full", "test 2022+"))
for (p, ent, ex) in NEIGHBOURHOOD:
    f, e = [], []
    for s, (sp, d1) in DATA.items():
        f += simulate(sp, d1, p, ent, ex, "open", "real", True,
                      since_year=SCORE_FROM_YEAR)
        e += simulate(sp, d1, p, ent, ex, "open", "real", True,
                      since_year=TEST_FROM_YEAR)
    pf, pe = pooled(f), pooled(e)
    mark = " <-- PRIMARY" if (p, ent, ex) == (RSI_P, RSI_ENTRY, RSI_EXIT) else ""
    print("  RSI(%d)<%-2d exit>%-2d  %s  %s%s"
          % (p, ent, ex,
             ("N=%3d PF=%5.2f avgR=%+.3f" % (pf["n"], pf["pf"], pf["avgR"])) if pf else "  -- none --",
             ("N=%3d PF=%5.2f avgR=%+.3f" % (pe["n"], pe["pf"], pe["avgR"])) if pe else "  -- none --",
             mark))

print("\n" + "=" * 78)
print("Reminder: this is a SCREEN. A PASS opens a deploy discussion, it does")
print("not settle one. Nothing is deployed by this script.")
print("=" * 78)
mt5.shutdown()
