"""Crypto-alt screen for BTC_DONCHIAN — can the rule buy CAPACITY on alts?

WHY (2026-07-30). BTC_DONCHIAN's discriminator is gross edge size, not carry
rate: crypto gross avgR is +4.6/+6.6R and survives 20%/yr financing, gold +1.15R
survives, indices +0.37..+0.49R die. Crypto alts are the same instrument type as
the two survivors, so they are the highest-prior extension. The honest goal is
CAPACITY, not diversification — alts correlate 0.7-0.9 with BTC, so this buys
more fills on an edge already owned, which is the actual bottleneck (~17
fills/yr across the whole book).

  ⚠️ CORRECTED AFTER THE RUN: the premise above asserted alts correlate 0.7-0.9
  with BTC and therefore buy capacity rather than diversification. That is true
  of PRICE and false of what matters — measured monthly-R correlation is
  BCHUSD/BTCUSD -0.01 and LTCUSD/BTCUSD +0.08. Strategy returns decorrelate
  because R depends on when each instrument triggers and how far its own trend
  runs relative to its own ATR, not on price co-movement (the same thing showed
  up as mean 0.07 on the index/gold additions). So "correlated, therefore only
  capacity" is not a valid reason to pre-reject an extension in this family —
  measure monthly R. It made no difference to this verdict, which is a
  no-edge verdict, but it would have been the wrong reason to skip the work.

WHAT THE PRE-SCREEN ALREADY SETTLED (scripts/crypto_alt_prescreen.py)
  The broker lists 18 crypto symbols. Only FOUR have enough history for the
  screen's own N>=40 bar (~7.3 years at the incumbents' ~5.5 fills/yr):
  BTCUSD (2011), LTCUSD (2011), ETHUSD (2016), BCHUSD (2017-08). Two are already
  deployed. **The entire candidate set is BCHUSD and LTCUSD.** Everything else
  begins 2021-06 or later (ADAUSD, BNBUSD, DOGUSD, DOTUSD, LNKUSD, UNIUSD,
  XLMUSD, XTZUSD, AVXUSD, KSMUSD, POLUSD) or 2025-01 (SOLUSD, XRPUSD), and is
  NOT SCORABLE — a different verdict from FAILED, and it will stay NOT SCORABLE
  until ~2028 at the earliest.

DELIBERATE OVERRIDE OF A PRE-COMMITTED GATE — stated up front
  The pre-screen's FRICTION_CEILING of 5.0% of ATR20 rejected BCHUSD (5.18%) and
  LTCUSD (31.6%). I am scoring both anyway. The ceiling was mis-calibrated for
  THIS family: at a 1xATR stop, friction as a fraction of ATR IS the friction in
  R, so 5.2% is 0.052R and 31.6% is 0.32R — against a gross avgR of +4.6R that
  is 1% and 7% of the edge. A 5% ceiling is roughly 6x tighter than anything
  that binds here. Three things make the override legitimate rather than
  goalpost-moving: (1) it runs in the PERMISSIVE direction, so it can only add
  candidates, never remove a failure; (2) the bar that DECIDES is untouched and
  still pre-committed; (3) the friction is not waved away, it is charged — and
  charged harder than the incumbents get charged (see the cost model). The
  multiple-comparisons cost is exactly 2 extra instruments.

COST MODEL — the one genuine methodological addition
  LTCUSD's recorded per-bar spread medians to 0.00 (IC raw pricing floors the
  field) while its live spread is 1.09 on an ATR of 3.45. So there is no usable
  recorded spread history, and the incumbents' "floor the recorded spread at a
  live snapshot" trick degenerates to "charge today's dollar spread on every bar
  since 2011". That is precisely the fixed-amount-vs-rate error that inflated
  USTEC's financing ~5x: LTC traded near $2 in 2013 and near $300 in 2021, so a
  constant $1.09 is meaningless at both ends. This script therefore adds
  cost_mode "atrfrac", which holds the spread/ATR RATIO constant and charges
  `ratio * ATR_t` per bar — the rate is the invariant, not the amount, same
  lesson as the swap normalisation. It is the decision column.

  ⚠️ CORRECTED AFTER THE RUN: I expected atrfrac to be strictly harsher than
  "real". It is not, and the direction is instructive. Charging a fixed $1.09 on
  a bar whose ATR is 2.0 costs 0.55R; charging the same $1.09 when ATR is 12
  costs 0.09R. So the fixed-amount model OVER-charges low-volatility (i.e.
  low-price) eras and UNDER-charges high-volatility ones. Correcting it moved
  LTCUSD 0.89 -> 0.94 and BTCUSD 4.48 -> 4.55. The honest description is
  "removes an anachronism", not "adds conservatism" — and it matters that both
  candidates still FAIL on the more lenient column, which is what makes the
  verdict robust rather than a cost-assumption artifact.

PRE-COMMITTED BEFORE LOOKING AT ANY RESULT
  Rule: UNCHANGED. 55/20 Donchian, ATR20 x 1.0 stop, 20-day trail, entry at the
    D1 close, 1% risk. No parameter is fitted here; if an alt needs different
    parameters it is a different strategy and out of scope.
  Bar, identical to the screen that deployed the current six: decision column
    (atrfrac cost + commission + financing ON), 2017+ PF >= 1.30, N >= 40,
    avgR > 0 on 2017+, AND avgR > 0 on the held-out 2022+ test leg. One look at
    the test leg.
  Financing charged on every night (crypto: longs pay, shorts pay 0).
  GROSS column (zero cost, no financing) printed alongside, per the standing
    rule that it separates "no edge" from "edge eaten by costs".
  Correlation of monthly R against BTCUSD/ETHUSD reported for any PASS, so the
    "capacity, not diversification" caveat is quantified rather than asserted.
  A PASS is a recommendation to screen further, NOT a deploy. Nothing here
    changes config.py.

INCUMBENT SANITY GATE
  All 8 donchian_universe_screen pins must reproduce on PF *and* N with
  financing off and the atrfrac mode unused, or the script exits non-zero. That
  is what proves adding cost_mode "atrfrac" is behaviour-neutral for the
  existing modes.

Usage (read-only; deploys nothing, writes nothing):
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -u -" < scripts/crypto_alt_screen.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

# ---------------------------------------------------------------- live params
ENTRY_LB, EXIT_LB, ATR_P, ATR_MULT = 55, 20, 20, 1.0
START_EQ, RISK_PCT = 10000.0, 1.0

# ------------------------------------------------------------- screen policy
SCORE_FROM_YEAR = 2017
TEST_FROM_YEAR = 2022
BAR_PF = 1.30
BAR_MIN_N = 40
MIN_HISTORY_START_YEAR = 2018

CANDIDATES = ["BCHUSD", "LTCUSD"]
INCUMBENTS = ["BTCUSD", "ETHUSD"]
# Reported as NOT SCORABLE with an indicative row, so the constraint is visible
# rather than a bare absence. These cannot be scored before ~2028.
NOT_SCORABLE = ["SOLUSD", "XRPUSD", "ADAUSD", "BNBUSD", "DOGUSD", "DOTUSD",
                "LNKUSD", "UNIUSD", "XLMUSD", "XTZUSD", "AVXUSD", "KSMUSD",
                "POLUSD"]

LIVE_SAMPLES, LIVE_GAP_SEC = 5, 2.0

CALIBRATE = False
SANITY_CUTOFF = pd.Timestamp("2026-07-01")
SANITY_PF_TOL = 0.02
SANITY = {
    ('BTCUSD', 'orig(close+flat)', 'FULL'):    (4.21, 73),
    ('BTCUSD', 'orig(close+flat)', '2023+'):   (2.59, 26),
    ('BTCUSD', 'HONEST(lag+spread)', 'FULL'):  (3.60, 58),
    ('BTCUSD', 'HONEST(lag+spread)', '2023+'): (1.76, 29),
    ('ETHUSD', 'orig(close+flat)', 'FULL'):    (3.22, 61),
    ('ETHUSD', 'orig(close+flat)', '2023+'):   (4.75, 20),
    ('ETHUSD', 'HONEST(lag+spread)', 'FULL'):  (2.72, 41),
    ('ETHUSD', 'HONEST(lag+spread)', '2023+'): (3.92, 21),
}

COMMISSION_RT_USD_PER_LOT = 0.0   # crypto CFDs are spread-only on IC raw
FLAT_COST = {"BTCUSD": 12.0, "ETHUSD": 5.0}
DPP_INCUMBENT = 1.0

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()
ACCT_CCY = mt5.account_info().currency


# ================================================================== PORTED ===
# Spliced from scripts/donchian_financing_rescore.py, itself a verbatim port of
# btc_donchian_honest_bt.py. The ONLY delta is cost_mode "atrfrac", which needs
# the bar ATR, so _cost takes an `atr_now` kwarg that defaults to None and is
# ignored by every pre-existing mode. The sanity gate proves that neutrality.

def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load(sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000)
    if rates is None or len(rates) < 2000:
        return None
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")           # broker clock
    off = df["tb"].apply(lambda t: eu_dst_offset(
        (t - pd.Timedelta(hours=3)).tz_localize("UTC")))
    df["tu"] = df["tb"] - pd.to_timedelta(off, unit="h")       # true UTC
    point = mt5.symbol_info(sym).point
    df["spread_price"] = df["spread"] * point
    df = df.iloc[:-1]
    df["bdate"] = df["tb"].dt.date
    d1 = df.groupby("bdate").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last")).reset_index()
    utc0 = df[df["tu"].dt.hour == 0].groupby("bdate").agg(
        lag_open=("open", "first"), lag_spread=("spread_price", "first"))
    d1 = d1.merge(utc0, on="bdate", how="left")
    close_sp = df.groupby("bdate").agg(close_spread=("spread_price", "last"))
    d1 = d1.merge(close_sp, on="bdate", how="left")
    return d1


def atr(d1):
    h, l, c = d1["high"], d1["low"], d1["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_P, adjust=False).mean()


def simulate(spec, d1, entry_mode, cost_mode, since_year=None,
             until_year=None, cutoff=None, fin=None):
    df = d1.copy()
    if cutoff is not None:
        df = df[pd.to_datetime(df["bdate"]) < cutoff].reset_index(drop=True)
    df["entry_high"] = df["high"].rolling(ENTRY_LB).max().shift(1)
    df["entry_low"] = df["low"].rolling(ENTRY_LB).min().shift(1)
    df["exit_high"] = df["high"].rolling(EXIT_LB).max().shift(1)
    df["exit_low"] = df["low"].rolling(EXIT_LB).min().shift(1)
    df["atr"] = atr(df).shift(1)
    rows = df.to_dict("records")
    trades = []
    recs = []
    equity = START_EQ
    open_t = None
    pending_entry = None
    for i, row in enumerate(rows):
        if since_year and row["bdate"].year < since_year:
            continue
        if until_year and row["bdate"].year > until_year:
            continue
        if pd.isna(row["entry_high"]) or pd.isna(row["atr"]):
            continue

        if pending_entry is not None and open_t is None:
            direction, sig_atr = pending_entry
            ep = row.get("lag_open")
            sp = row.get("lag_spread")
            if ep is None or pd.isna(ep):
                pending_entry = None
            else:
                cost = _cost(spec, cost_mode, sp, atr_now=row["atr"])
                stop = ep - ATR_MULT * sig_atr if direction == "L" else ep + ATR_MULT * sig_atr
                open_t = {"dir": direction, "ep": ep, "stop": stop,
                          "isd": abs(ep - stop), "cost": cost,
                          "in": row["bdate"], "last": row["bdate"], "fin": 0.0}
                pending_entry = None

        if open_t is not None:
            if fin is not None:
                nights = (row["bdate"] - open_t["last"]).days
                if nights > 0:
                    open_t["fin"] += nights * fin(open_t["dir"], row["close"])
                open_t["last"] = row["bdate"]
            if open_t["dir"] == "L":
                if row["low"] <= open_t["stop"]:
                    xp = min(row["open"], open_t["stop"])
                    pnl_pts = (xp - open_t["ep"]) - open_t["cost"] - open_t["fin"]
                else:
                    if not pd.isna(row["exit_low"]):
                        open_t["stop"] = max(open_t["stop"], row["exit_low"])
                    pnl_pts = None
            else:
                if row["high"] >= open_t["stop"]:
                    xp = max(row["open"], open_t["stop"])
                    pnl_pts = (open_t["ep"] - xp) - open_t["cost"] - open_t["fin"]
                else:
                    if not pd.isna(row["exit_high"]):
                        open_t["stop"] = min(open_t["stop"], row["exit_high"])
                    pnl_pts = None
            if pnl_pts is not None:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_t["isd"] * spec["dpp"], 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                usd = pnl_pts * lots * spec["dpp"]
                equity += usd
                trades.append(usd)
                recs.append({"sym": spec["sym"], "dir": open_t["dir"],
                             "in": open_t["in"], "out": row["bdate"],
                             "R": pnl_pts / open_t["isd"] if open_t["isd"] else 0.0,
                             "nights": (row["bdate"] - open_t["in"]).days,
                             "finR": (open_t["fin"] / open_t["isd"]
                                      if open_t["isd"] else 0.0),
                             "costR": (open_t["cost"] / open_t["isd"]
                                       if open_t["isd"] else 0.0),
                             "usd": usd})
                open_t = None

        if open_t is None and pending_entry is None:
            direction = None
            if row["close"] > row["entry_high"]:
                direction = "L"
            elif row["close"] < row["entry_low"]:
                direction = "S"
            if direction:
                if entry_mode == "lag":
                    pending_entry = (direction, row["atr"])
                else:
                    ep = row["close"]
                    sp = row.get("close_spread")
                    cost = _cost(spec, cost_mode, sp, atr_now=row["atr"])
                    stop = ep - ATR_MULT * row["atr"] if direction == "L" else ep + ATR_MULT * row["atr"]
                    open_t = {"dir": direction, "ep": ep, "stop": stop,
                              "isd": abs(ep - stop), "cost": cost,
                              "in": row["bdate"], "last": row["bdate"], "fin": 0.0}
    return np.array(trades), equity, recs


def _cost(spec, cost_mode, sp, atr_now=None):
    """Round-trip cost in price points.

    "flat"/"spread"/"real"/"stress" are the incumbent's, unchanged.

    "atrfrac" is new and is this screen's decision column: charge
    `spread_over_atr * ATR_t + commission`, i.e. hold the spread as a RATIO of
    volatility rather than as a fixed dollar amount. Required because the
    recorded spread field is 0 for LTCUSD across its whole 15-year history, so
    the only measurable spread is today's — and carrying today's DOLLARS back to
    a $2 coin is the same fixed-amount-vs-rate error that inflated USTEC's
    financing 5x.
    """
    if cost_mode == "zero":
        return 0.0
    if cost_mode == "spread":
        return sp if not pd.isna(sp) else spec["flat"]
    if cost_mode == "flat":
        return spec["flat"]
    if cost_mode == "atrfrac":
        if atr_now is None or pd.isna(atr_now):
            return spec["floor"] + spec["comm"]
        return spec["sp_over_atr"] * atr_now + spec["comm"]
    base = max(0.0 if pd.isna(sp) else sp, spec["floor"]) + spec["comm"]
    return base * (2.0 if cost_mode == "stress" else 1.0)


def stats(trades, recs, years):
    if len(trades) == 0:
        return None
    w = (trades > 0).sum()
    gp = trades[trades > 0].sum()
    gl = abs(trades[trades <= 0].sum())
    eq = np.concatenate([[START_EQ], START_EQ + np.cumsum(trades)])
    dd = np.maximum.accumulate(eq) - eq
    ddpct = (dd.max() / np.maximum.accumulate(eq)[dd.argmax()] * 100
             if dd.max() > 0 else 0.0)
    final = START_EQ + trades.sum()
    return {
        "n": len(trades),
        "wr": w / len(trades) * 100,
        "pf": (gp / gl) if gl > 0 else float("inf"),
        "avgR": float(np.mean([r["R"] for r in recs])) if recs else 0.0,
        "sdR": float(np.std([r["R"] for r in recs], ddof=1)) if len(recs) > 1 else 0.0,
        "dd": ddpct,
        "cagr": (((final / START_EQ) ** (1 / years) - 1) * 100
                 if years > 0 and final > 0 else float("nan")),
    }


SWAP_MODE_NAME = {0: "DISABLED", 1: "POINTS", 2: "CCY_SYMBOL", 3: "CCY_MARGIN",
                  4: "CCY_DEPOSIT", 5: "INTEREST_CURRENT", 6: "INTEREST_OPEN",
                  7: "REOPEN_CURRENT", 8: "REOPEN_BID"}


def to_acct(amount, ccy):
    if ccy == ACCT_CCY:
        return amount
    for pair, invert in ((ccy + ACCT_CCY, False), (ACCT_CCY + ccy, True)):
        mt5.symbol_select(pair, True)
        t = mt5.symbol_info_tick(pair)
        if t and t.bid:
            return amount / t.bid if invert else amount * t.bid
    return None


def swap_fn(sym, dpp, px_now):
    """Per-night financing cost in price units, normalised to an annual rate on
    notional first. Ported verbatim from donchian_financing_rescore.swap_fn."""
    info = mt5.symbol_info(sym)
    m, sl, ss, pt = info.swap_mode, info.swap_long, info.swap_short, info.point
    note = SWAP_MODE_NAME.get(m, "mode%d" % m)
    if m == 0:
        return (lambda d, px: 0.0), 0.0, 0.0, note + " (no financing)"
    if m in (5, 6):
        rL, rS = -sl, -ss
        detail = "long %+.3g%%/yr short %+.3g%%/yr (native)" % (sl, ss)
    elif m == 1:
        rL = -sl * pt * 360.0 / px_now * 100.0
        rS = -ss * pt * 360.0 / px_now * 100.0
        detail = "long %+.4g pts short %+.4g pts /night" % (sl, ss)
    elif m in (2, 3, 4):
        ccy = (info.currency_base if m == 2 else
               info.currency_margin if m == 3 else ACCT_CCY)
        aL, aS = to_acct(sl, ccy), to_acct(ss, ccy)
        if aL is None or aS is None:
            return None, 0.0, 0.0, ("%s in %s — NO CONVERSION RATE, refusing "
                                    "to guess" % (note, ccy))
        rL = -aL / dpp * 360.0 / px_now * 100.0
        rS = -aS / dpp * 360.0 / px_now * 100.0
        detail = "long %+.4g %s short %+.4g %s /night" % (sl, ccy, ss, ccy)
    else:
        return None, 0.0, 0.0, "%s UNHANDLED" % note

    def f(d, px, rL=rL, rS=rS):
        return px * (rL if d == "L" else rS) / 100.0 / 360.0

    return f, rL, rS, "%s %s" % (note, detail)

# ============================================================== END PORTED ===


def sample_live_spread(syms):
    """Median of several ticks — a single snapshot moved 2 verdicts on the FX
    breadth screen 20 minutes apart."""
    acc = {s: [] for s in syms}
    import time
    for i in range(LIVE_SAMPLES):
        for s in syms:
            t = mt5.symbol_info_tick(s)
            if t and t.ask and t.bid and t.ask > t.bid:
                acc[s].append(t.ask - t.bid)
        if i < LIVE_SAMPLES - 1:
            time.sleep(LIVE_GAP_SEC)
    return {s: (float(np.median(v)) if v else None) for s, v in acc.items()}


def build_spec(sym, live_sp, d1):
    info = mt5.symbol_info(sym)
    if info is None or not info.trade_tick_size:
        return None
    dpp = info.trade_tick_value / info.trade_tick_size
    if dpp <= 0:
        return None
    a = atr(d1)
    # ratio measured on the RECENT regime (last 2y of bars), where the live tick
    # we floor on was actually observed
    recent_atr = float(a.iloc[-500:].median())
    rec_sp = float(d1["close_spread"].median()) if "close_spread" in d1 else 0.0
    eff_sp = max(rec_sp if not pd.isna(rec_sp) else 0.0, live_sp or 0.0)
    return {"sym": sym, "dpp": dpp,
            "comm": COMMISSION_RT_USD_PER_LOT / dpp,
            "live_spread": live_sp or 0.0,
            "floor": eff_sp,
            "rec_sp": rec_sp,
            "recent_atr": recent_atr,
            "sp_over_atr": eff_sp / recent_atr if recent_atr else 0.0,
            "vol_min": info.volume_min,
            "flat": FLAT_COST.get(sym, 0.0)}


def sanity_gate():
    print("=" * 84)
    print("INCUMBENT SANITY GATE  (frozen window: bdate < %s)"
          % SANITY_CUTOFF.date())
    print("  proves cost_mode 'atrfrac' + the atr_now kwarg are behaviour-neutral")
    print("=" * 84)
    emitted, failures = {}, []
    for sym in INCUMBENTS:
        d1 = load(sym)
        if d1 is None:
            print("  %s: NO DATA — cannot verify" % sym)
            sys.exit(1)
        spec = {"sym": sym, "dpp": DPP_INCUMBENT, "flat": FLAT_COST[sym],
                "comm": 0.0, "floor": 0.0, "sp_over_atr": 0.0}
        for mode_label, em, cm in (("orig(close+flat)", "close", "flat"),
                                   ("HONEST(lag+spread)", "lag", "spread")):
            for per_label, sy in (("FULL", None), ("2023+", 2023)):
                tr, _eq, rc = simulate(spec, d1, em, cm, since_year=sy,
                                       cutoff=SANITY_CUTOFF)
                s = stats(tr, rc, 1.0)
                key = (sym, mode_label, per_label)
                got = (round(s["pf"], 2), s["n"])
                emitted[key] = got
                if CALIBRATE:
                    print("    %-7s %-19s %-6s PF=%5.2f N=%3d"
                          % (sym, mode_label, per_label, got[0], got[1]))
                    continue
                exp = SANITY.get(key)
                ok_pf = abs(got[0] - exp[0]) <= SANITY_PF_TOL
                ok_n = got[1] == exp[1]
                print("  %-7s %-19s %-6s PF %5.2f (exp %5.2f) N %3d (exp %3d)  %s"
                      % (sym, mode_label, per_label, got[0], exp[0],
                         got[1], exp[1], "ok" if (ok_pf and ok_n) else "DRIFT"))
                if not (ok_pf and ok_n):
                    failures.append("%s %s %s: PF %.2f vs %.2f, N %d vs %d"
                                    % (sym, mode_label, per_label,
                                       got[0], exp[0], got[1], exp[1]))
    if CALIBRATE:
        print("\n  SANITY = {")
        for k, v in emitted.items():
            print("      %-42s (%.2f, %d)," % (str(k) + ":", v[0], v[1]))
        print("  }")
        mt5.shutdown()
        sys.exit(0)
    if failures:
        print("\n  SANITY GATE FAILED — every number below would be void.")
        for f in failures:
            print("    - " + f)
        mt5.shutdown()
        sys.exit(1)
    print("\n  gate passed — simulator reproduces the incumbent.\n")


def monthly_R(recs):
    if not recs:
        return pd.Series(dtype=float)
    df = pd.DataFrame(recs)
    df["m"] = pd.to_datetime(df["out"]).dt.to_period("M")
    return df.groupby("m")["R"].sum()


def score(sym, spec, d1, f, yrs_full, yrs_test):
    """Every column for one instrument. Returns (rows, recs_decision)."""
    out = {}
    for per, sy, yrs in (("full", SCORE_FROM_YEAR, yrs_full),
                         ("test", TEST_FROM_YEAR, yrs_test)):
        for lbl, cm, use_fin in (("gross", "zero", False),
                                 ("real", "real", True),
                                 ("atrfrac", "atrfrac", True),
                                 ("stress", "stress", True)):
            tr, _eq, rc = simulate(spec, d1, "close", cm, since_year=sy,
                                   fin=f if use_fin else None)
            out[(per, lbl)] = (stats(tr, rc, yrs), rc)
    return out


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    yrs_full = (today - pd.Timestamp("%d-01-01" % SCORE_FROM_YEAR)).days / 365.25
    yrs_test = (today - pd.Timestamp("%d-01-01" % TEST_FROM_YEAR)).days / 365.25
    equity = mt5.account_info().equity

    sanity_gate()

    print("=" * 84)
    print("CRYPTO-ALT SCREEN   %s" % today.date())
    print("  rule UNCHANGED (55/20, ATR20x1.0, close entry, %.1f%% risk)" % RISK_PCT)
    print("  bar: atrfrac+financing PF>=%.2f on %d+, N>=%d, avgR>0 on %d+ AND on"
          " %d+ test" % (BAR_PF, SCORE_FROM_YEAR, BAR_MIN_N, SCORE_FROM_YEAR,
                         TEST_FROM_YEAR))
    print("=" * 84)

    allsyms = CANDIDATES + INCUMBENTS + NOT_SCORABLE
    for s in allsyms:
        mt5.symbol_select(s, True)
    live = sample_live_spread(allsyms)

    print("\nCOST + CARRY SPECS (live)")
    print("  %-8s %8s %8s %9s %8s  %8s %8s  %s"
          % ("sym", "live_sp", "ATR20", "sp/ATR", "minlot%", "swapL%", "swapS%",
             "mode"))
    specs, fns = {}, {}
    for sym in CANDIDATES + INCUMBENTS:
        d1 = load(sym)
        if d1 is None:
            print("  %-8s no history" % sym)
            continue
        spec = build_spec(sym, live.get(sym), d1)
        if spec is None:
            print("  %-8s no tick specs" % sym)
            continue
        tick = mt5.symbol_info_tick(sym)
        px = tick.bid if tick and tick.bid else float(d1["close"].iloc[-1])
        f, annL, annS, note = swap_fn(sym, spec["dpp"], px)
        if f is None:
            print("  %-8s %s" % (sym, note))
            continue
        cur_atr = float(atr(d1).iloc[-1])
        ml = spec["vol_min"] * cur_atr * spec["dpp"] / equity * 100.0
        flag = "" if -5.0 <= annL <= 60.0 else "  <-- CHECK MODE"
        print("  %-8s %8.4f %8.3f %8.2f%% %7.2f%%  %+8.2f %+8.2f  %s%s"
              % (sym, spec["live_spread"], spec["recent_atr"],
                 spec["sp_over_atr"] * 100, ml, annL, annS, note, flag))
        specs[sym] = (spec, d1)
        fns[sym] = f

    print("\n" + "=" * 84)
    print("RESULTS   (gross = zero cost + no financing; atrfrac = DECISION)")
    print("=" * 84)

    verdicts, dec_recs = {}, {}
    for sym in CANDIDATES + INCUMBENTS:
        if sym not in specs:
            continue
        spec, d1 = specs[sym]
        out = score(sym, spec, d1, fns[sym], yrs_full, yrs_test)
        s_dec, rc_dec = out[("full", "atrfrac")]
        st_dec, _ = out[("test", "atrfrac")]
        if s_dec is None:
            print("\n  %-8s no trades" % sym)
            continue
        dec_recs[sym] = rc_dec
        start = min(d1["bdate"])
        tag = "INCUMBENT" if sym in INCUMBENTS else "CANDIDATE"
        print("\n  %-8s [%s]  history from %s   N=%d over %.1fy (%.1f fills/yr)"
              % (sym, tag, start, s_dec["n"], yrs_full, s_dec["n"] / yrs_full))
        print("      %-9s %6s %6s %7s %7s %7s"
              % ("column", "PF", "N", "avgR", "WR%", "maxDD%"))
        for lbl in ("gross", "real", "atrfrac", "stress"):
            for per in ("full", "test"):
                s, _ = out[(per, lbl)]
                if s is None:
                    continue
                mark = "  <- decision" if (lbl == "atrfrac" and per == "full") else ""
                print("      %-9s %6.2f %6d %+7.3f %7.0f %7.1f   [%s]%s"
                      % (lbl if per == "full" else "", s["pf"], s["n"],
                         s["avgR"], s["wr"], s["dd"],
                         "%d+" % SCORE_FROM_YEAR if per == "full"
                         else "%d+ test" % TEST_FROM_YEAR, mark))
        fin_mean = np.mean([r["finR"] for r in rc_dec])
        cost_mean = np.mean([r["costR"] for r in rc_dec])
        longs = [r for r in rc_dec if r["dir"] == "L"]
        print("      friction %+.3fR/trade   financing %+.3fR/trade   %d%% long"
              "   avg hold %.0f nights"
              % (cost_mean, fin_mean, 100 * len(longs) / len(rc_dec),
                 np.mean([r["nights"] for r in rc_dec])))
        ok = (s_dec["pf"] >= BAR_PF and s_dec["n"] >= BAR_MIN_N
              and s_dec["avgR"] > 0 and st_dec is not None and st_dec["avgR"] > 0)
        why = []
        if s_dec["pf"] < BAR_PF:
            why.append("PF %.2f < %.2f" % (s_dec["pf"], BAR_PF))
        if s_dec["n"] < BAR_MIN_N:
            why.append("N %d < %d" % (s_dec["n"], BAR_MIN_N))
        if s_dec["avgR"] <= 0:
            why.append("avgR %+.3f <= 0" % s_dec["avgR"])
        if st_dec is None or st_dec["avgR"] <= 0:
            why.append("test avgR %+.3f <= 0"
                       % (st_dec["avgR"] if st_dec else 0.0))
        print("      BAR: %s%s" % ("PASS" if ok else "FAIL",
                                   "" if ok else "  (" + "; ".join(why) + ")"))
        if sym in CANDIDATES:
            verdicts[sym] = ok
        # power: can this instrument ever be validated live?
        if s_dec["avgR"] > 0 and s_dec["sdR"] > 0:
            n80 = 7.85 * s_dec["sdR"] ** 2 / s_dec["avgR"] ** 2
            rate = s_dec["n"] / yrs_full
            print("      power: N80=%.0f at %.1f fills/yr = %.0f years to validate"
                  % (n80, rate, n80 / rate if rate else float("nan")))

    # ------------------------------------------------ correlation to incumbents
    print("\n" + "=" * 84)
    print("MONTHLY-R CORRELATION vs INCUMBENTS  (capacity vs diversification)")
    print("=" * 84)
    mr = {s: monthly_R(r) for s, r in dec_recs.items()}
    keys = [k for k in CANDIDATES + INCUMBENTS if k in mr]
    print("  %-8s %s" % ("", " ".join("%8s" % k for k in keys)))
    for a in keys:
        cells = []
        for b in keys:
            j = pd.concat([mr[a], mr[b]], axis=1).fillna(0.0)
            c = j.corr().iloc[0, 1] if len(j) > 2 else float("nan")
            cells.append("%8.2f" % c)
        print("  %-8s %s" % (a, " ".join(cells)))
    print("\n  Read this as the reason a PASS buys CAPACITY, not diversification:")
    print("  a high correlation means more fills on the SAME bet, which still")
    print("  helps (compounding is fill-starved) but does not reduce portfolio")
    print("  variance the way an uncorrelated instrument would.")

    # ---------------------------------------------------------- not scorable
    print("\n" + "=" * 84)
    print("NOT SCORABLE — history too short for the N>=%d bar" % BAR_MIN_N)
    print("=" * 84)
    print("  %-8s %-11s %6s %8s  %s" % ("sym", "start", "fills", "yrs", "note"))
    for sym in NOT_SCORABLE:
        d1 = load(sym)
        if d1 is None:
            print("  %-8s %-11s %6s %8s  no usable H1 history" % (sym, "?", "-", "-"))
            continue
        spec = build_spec(sym, live.get(sym), d1)
        if spec is None:
            print("  %-8s no tick specs" % sym)
            continue
        start = min(d1["bdate"])
        yrs = (today - pd.Timestamp(start)).days / 365.25
        tr, _eq, rc = simulate(spec, d1, "close", "atrfrac")
        n = len(tr)
        print("  %-8s %-11s %6d %8.1f  needs ~%.0f more years at this rate"
              % (sym, start, n, yrs,
                 max(0.0, (BAR_MIN_N - n) / (n / yrs)) if n else float("nan")))
    print("\n  No PF is printed for these ON PURPOSE. A PF on 1-4 years and")
    print("  N<40 is noise, and printing it invites exactly the 'but SOLUSD")
    print("  looks great' reasoning that the ASB/AUDJPY screen fell for.")

    # ------------------------------------------------------------- conclusion
    print("\n" + "=" * 84)
    print("VERDICT")
    print("=" * 84)
    passed = [s for s, ok in verdicts.items() if ok]
    failed = [s for s, ok in verdicts.items() if not ok]
    if passed:
        print("  PASS: %s" % ", ".join(passed))
        print("  This is a recommendation to consider, NOT a deploy. Before any")
        print("  config change: (a) check PORTFOLIO_GATE headroom — 6 Donchian")
        print("  instruments already run against max_positions 12; (b) confirm")
        print("  the min-lot column above leaves the sizer able to fill; (c) note")
        print("  the correlation matrix — this adds capacity, not independence.")
    else:
        print("  NOTHING PASSES. The crypto-alt extension is dead on this rule.")
    if failed:
        print("  FAIL: %s" % ", ".join(failed))
    print("\n  Scope note: the broker's crypto list is 18 symbols and 13 of them")
    print("  cannot be scored before ~2028. Whatever this screen concludes, the")
    print("  crypto-alt avenue is CLOSED for the next ~2 years by data, not by")
    print("  edge — so this is not a question to revisit in a few months.")


main()
mt5.shutdown()
