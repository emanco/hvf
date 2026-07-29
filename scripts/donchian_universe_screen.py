"""Donchian universe screen — can BTC_DONCHIAN's rule extend beyond crypto?

The premise (2026-07-29): BTC_DONCHIAN is the only live strategy whose sim
survived the 2026-07-28 fill audits untouched. It is close-based
(`if row["close"] > row["entry_high"]`), so it is structurally immune to the
blind-gap fill fiction that killed LONDON_BO, and it has no SL-modify overlay,
so the stop-modify-through-market fiction cannot reach it either. Its stops are
1x ATR on DAILY bars — hundreds of points against ~1-2p of friction — so unlike
every intraday strategy we have killed, its edge is not sitting on the cost wall.

What it lacks is breadth. Two crypto instruments that co-move ~0.8 are
effectively ONE bet. Trend-following does not earn its Sharpe from per-market
edge (which is thin and unstable); it earns it from running one rule across many
uncorrelated markets. This screens the same rule, unchanged, over every IC
instrument with usable daily history.

METHOD
  - `simulate()` and `load()` are ported VERBATIM from
    scripts/btc_donchian_honest_bt.py. This screen does not re-derive the fill
    model. (scripts/pair_extension_screen.py was contaminated precisely by
    re-deriving one — see CLAUDE.md "Negative results".)
  - The only edits are (a) per-symbol DPP/cost passed in via `spec` instead of
    the crypto-only globals, (b) a "real" cost mode, (c) trade metadata
    recorded for the portfolio pass. None of these touch entry/exit logic.
  - DPP (account-USD per price unit per lot) comes from MT5 tick specs
    (`trade_tick_value / trade_tick_size`), which is account-currency correct.
    NEVER a flat $10/pip — that is the quote currency (see CLAUDE.md DO NOT).
    Note PF is very nearly DPP-invariant here (DPP cancels in the
    fixed-fractional sizing); it is lot ROUNDING and the 0.01 floor that make
    it matter, plus CAGR/DD which are not scale-free.

PRE-COMMITTED BEFORE LOOKING AT ANY RESULT
  - Parameters are FIXED at the live values (55/20, ATR20 x1.0, 1% risk) for
    every instrument. No per-market tuning — that is where overfitting enters
    when you take a crypto-fitted rule to 24 markets.
  - Entry mode = "close". Live has entered at the broker rollover (~D1 close)
    since the 2026-07-02 gate fix, so "lag" is now a historical reference row,
    not the decision row.
  - Scored window = 2017-01-01+. Pre-2017 crypto history on IC is MetaQuotes
    backfill: it puts BTC's full-period maxDD at 72.9% and swings PF from 4.26
    to 5.66 on a cost change alone (one catastrophic early trade). Excluded.
  - Train = 2017..2021, Test = 2022+. Fixed here, before results.
  - Verdicts are judged on the "real" cost column ONLY. The "recorded" column
    is shown to expose how optimistic it is: IC's per-bar `spread` field
    medians to ~0 points on raw pricing (12 of 37 instruments scanned came back
    at exactly 0.00% of ATR), which is the trap that shipped a wrong LBO screen.
  - PASS requires ALL of: real-cost FULL PF >= 1.30, N >= 40, avgR > 0, AND
    test-leg avgR > 0. An instrument with < 40 trades or history starting after
    2018 is NOT SCORED, not FAILED (AUDJPY was being "failed" on one year in the
    old ASB screen).

INCUMBENT SANITY GATE
  BTCUSD/ETHUSD must reproduce btc_donchian_honest_bt.py on PF *and* N, in both
  cost modes and both periods, or this script exits non-zero. N is the sharper
  tripwire: a broken filter moves N long before it moves PF.
  The gate runs on a FROZEN data window (< SANITY_CUTOFF) so the pins stay
  reproducible as history accrues. This matters — re-running the incumbent on
  2026-07-29 already gave BTC 2023+ orig PF 2.67 vs the 2.59 recorded in its own
  docstring on 2026-07-02, purely from 27 extra days of data. A gate pinned to
  "latest" rots on its own.

RESULTS 2026-07-29 (sanity gate: all 8 pins reproduced exactly)
  PASS (6): XAUUSD 2.54, USTEC 1.59, JP225 1.51, US500 1.44, BTCUSD 5.18,
            ETHUSD 3.56   [real-cost PF, 2017+]
  FAIL — all 12 FX, uniformly and badly: EURGBP 0.16, AUDUSD 0.33, GBPUSD 0.39,
            NZDUSD 0.46, EURJPY 0.56, NZDCAD 0.66, EURAUD 0.67, EURCHF 0.69,
            USDCHF 0.71, GBPJPY 0.71, EURUSD 0.79, USDJPY 0.86.
            Not a cost artifact — recorded->stress cost moves these by ~2-5%
            (EURUSD 0.81/0.79/0.77). Daily-bar trend following on FX is simply
            dead over 2017+, consistent with the post-2010 carry/suppression
            regime. Do not re-screen FX for this family without a NEW hypothesis.
  FAIL — XTIUSD 1.63 and XBRUSD 1.53 clear the PF bar on the FULL window but
            are killed by the pre-committed TEST leg: train 2017-21 PF 2.76 /
            2.60, test 2022+ 0.77 / 0.85 (avgR -0.12 / -0.09). Entirely a
            pre-2022 phenomenon. This is the train/test rule doing its job and
            is the single most valuable line in this output.
  FAIL — XAGUSD 1.07, US30 0.89, HK50 0.85, F40 0.79, UK100 0.69, DE40 0.64.
  Portfolio of the 6 passers: N=325, avgR +2.37, PF 4.12, WR 28%.
  Peak concurrency 7 (gate cap 9); peak USD legs 4 (gate cap 4 — binds).
  Monthly-R correlation mean 0.07, max 0.61.

CAVEATS THAT MATTER MORE THAN THE HEADLINE
  1. avgR is mean-driven and NOT robust here. BTCUSD +4.63, ETHUSD +6.63,
     ETH train +12.48 — these are one or two monster trends, not a typical
     trade. Read PF and the R distribution, not avgR, for crypto/gold.
  2. 24 instruments screened at a fixed bar = a multiple-comparisons problem.
     6 passes is roughly what luck could produce. What makes it more than
     luck is that the passers cluster economically (equity indices, gold,
     crypto — assets with structural trend regimes) rather than scattering.
  3. US500 and USTEC are the max-0.61 correlation pair. Adding BOTH is close
     to double-counting one bet; prefer one unless sizing accounts for it.
  4. Concurrency is bucketed by day, so a same-day exit+entry double-counts.
     Peak=7 and USD=4 are therefore slight OVERstatements.
  5. XAUUSD/BTCUSD/ETHUSD are 6-letter alpha, so PORTFOLIO_GATE counts their
     currency legs; US500/USTEC/JP225 are not and are invisible to that cap.

Usage:
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/donchian_universe_screen.py
  Set CALIBRATE=True to re-emit the sanity pins after a deliberate change.
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
TRAIN_YEARS = (2017, 2021)      # inclusive
TEST_FROM_YEAR = 2022
BAR_PF = 1.30
BAR_MIN_N = 40
MIN_HISTORY_START_YEAR = 2018   # data must begin at/before this to be scorable

# Incumbent pins, frozen window. Regenerate with CALIBRATE=True after any
# deliberate change to the ported simulator, and say so in the commit.
CALIBRATE = False
SANITY_CUTOFF = pd.Timestamp("2026-07-01")
SANITY_PF_TOL = 0.02
# Calibrated 2026-07-29. The 2023+ rows reproduce btc_donchian_honest_bt.py's
# own docstring EXACTLY (BTC orig 2.59 / HONEST 1.76, ETH 4.75 / 3.92, recorded
# there on 2026-07-02) — independent evidence the port is faithful, and that
# re-running that script today gives 2.67/1.80/4.90/3.98 purely from 27 extra
# days of data rather than from any logic change.
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

# IC raw-spread account: commission is charged on FX and metals
# ($3.50/side/100k => $7.00 round trip per 1.0 lot); index, energy and crypto
# CFDs are spread-only. Verify against a statement before trusting a marginal
# verdict — a wrong commission is a silent, uniform edge tax.
COMMISSION_RT_USD_PER_LOT = {
    "fx": 7.0, "metal": 7.0, "index": 0.0, "energy": 0.0, "crypto": 0.0,
}

UNIVERSE = {
    "fx": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD",
           "EURJPY", "GBPJPY", "EURGBP", "EURAUD", "NZDCAD", "EURCHF"],
    "metal": ["XAUUSD", "XAGUSD"],
    "index": ["US500", "US30", "USTEC", "DE40", "UK100", "JP225", "HK50", "F40"],
    "energy": ["XTIUSD", "XBRUSD"],
    "crypto": ["BTCUSD", "ETHUSD"],
}
# Excluded on measured friction (median D1 spread as % of ATR20, 2026-07-29):
#   LTCUSD 64.1%, BCHUSD 10.4%, XNGUSD 8.9%. Unlike the low end of that scan,
#   large recorded spreads ARE trustworthy — the field floors at 0, it does not
#   inflate. Also excluded for history starting 2025-01-02 (408 D1 bars):
#   USDCAD, AUDJPY, AUDNZD, AUDCAD, AUS200, XRPUSD.

# Currency legs for the PORTFOLIO_GATE concurrency check. Mirrors
# portfolio_gate._currencies: 6-letter alpha symbols only, others have no
# currency-exposure semantics there.
NON_FX_CCY = {"US500": None, "US30": None, "USTEC": None, "DE40": None,
              "UK100": None, "JP225": None, "HK50": None, "F40": None,
              "XTIUSD": None, "XBRUSD": None, "BTCUSD": None, "ETHUSD": None,
              "XAUUSD": None, "XAGUSD": None}

FLAT_COST = {"BTCUSD": 12.0, "ETHUSD": 5.0}   # incumbent's original assumption
DPP_INCUMBENT = 1.0                            # incumbent's hardcoded DPP

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


# ================================================================== PORTED ===
# Everything from here to END PORTED is byte-equivalent in behaviour to
# scripts/btc_donchian_honest_bt.py. Do not "improve" it in place.

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
             until_year=None, cutoff=None):
    """Ported from btc_donchian_honest_bt.simulate.

    Deltas, all non-behavioural for the flat/spread modes the sanity gate uses:
      - FLAT_COST[sym] -> spec["flat"], DPP -> spec["dpp"] (per-instrument)
      - cost_mode "real" added (floored spread + commission)
      - until_year / cutoff added for train/test and the frozen sanity window
      - each trade records R, dates and direction for the portfolio pass
    """
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
                cost = _cost(spec, cost_mode, sp)
                stop = ep - ATR_MULT * sig_atr if direction == "L" else ep + ATR_MULT * sig_atr
                open_t = {"dir": direction, "ep": ep, "stop": stop,
                          "isd": abs(ep - stop), "cost": cost,
                          "in": row["bdate"]}
                pending_entry = None

        if open_t is not None:
            if open_t["dir"] == "L":
                if row["low"] <= open_t["stop"]:
                    xp = min(row["open"], open_t["stop"])
                    pnl_pts = (xp - open_t["ep"]) - open_t["cost"]
                else:
                    if not pd.isna(row["exit_low"]):
                        open_t["stop"] = max(open_t["stop"], row["exit_low"])
                    pnl_pts = None
            else:
                if row["high"] >= open_t["stop"]:
                    xp = max(row["open"], open_t["stop"])
                    pnl_pts = (open_t["ep"] - xp) - open_t["cost"]
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
                    cost = _cost(spec, cost_mode, sp)
                    stop = ep - ATR_MULT * row["atr"] if direction == "L" else ep + ATR_MULT * row["atr"]
                    open_t = {"dir": direction, "ep": ep, "stop": stop,
                              "isd": abs(ep - stop), "cost": cost,
                              "in": row["bdate"]}
    return np.array(trades), equity, recs


def _cost(spec, cost_mode, sp):
    """Round-trip cost in price points.

    "flat"/"spread" reproduce the incumbent exactly. "real" is the decision
    column: the recorded spread floored at a live snapshot (the field medians
    to ~0 on IC raw pricing) plus commission. "stress" doubles it.
    """
    if cost_mode == "spread":
        return sp if not pd.isna(sp) else spec["flat"]
    if cost_mode == "flat":
        return spec["flat"]
    base = max(0.0 if pd.isna(sp) else sp, spec["floor"]) + spec["comm"]
    return base * (2.0 if cost_mode == "stress" else 1.0)

# ============================================================== END PORTED ===


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
        "dd": ddpct,
        "cagr": (((final / START_EQ) ** (1 / years) - 1) * 100
                 if years > 0 and final > 0 else float("nan")),
    }


def build_spec(sym, cls):
    """Per-instrument sizing + cost spec from live MT5 tick specs."""
    info = mt5.symbol_info(sym)
    if info is None:
        return None
    if not info.visible:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
    if not info.trade_tick_size:
        return None
    dpp = info.trade_tick_value / info.trade_tick_size
    if dpp <= 0:
        return None
    comm_usd = COMMISSION_RT_USD_PER_LOT[cls]
    return {"sym": sym, "cls": cls, "dpp": dpp,
            "comm": comm_usd / dpp,
            "live_spread": info.spread * info.point,
            "flat": FLAT_COST.get(sym, 0.0)}


def sanity_gate():
    """Reproduce btc_donchian_honest_bt.py on a frozen window, or die."""
    print("=" * 78)
    print("INCUMBENT SANITY GATE  (frozen window: bdate < %s)"
          % SANITY_CUTOFF.date())
    print("=" * 78)
    emitted, failures = {}, []
    for sym in ("BTCUSD", "ETHUSD"):
        d1 = load(sym)
        if d1 is None:
            print("  %s: NO DATA — cannot verify" % sym)
            sys.exit(1)
        # the incumbent hardcodes DPP=1.0 for both crypto CFDs
        spec = {"sym": sym, "dpp": DPP_INCUMBENT, "flat": FLAT_COST[sym],
                "comm": 0.0, "floor": 0.0}
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
                if exp is None:
                    failures.append("%s %s %s: no pin recorded"
                                    % (sym, mode_label, per_label))
                    continue
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
        print("\n  CALIBRATE=True — pins emitted, screen not run.")
        mt5.shutdown()
        sys.exit(0)
    if failures:
        print("\n  SANITY GATE FAILED — the ported simulator has drifted from")
        print("  btc_donchian_honest_bt.py. Every number below would be void.")
        for f in failures:
            print("    - " + f)
        mt5.shutdown()
        sys.exit(1)
    print("\n  gate passed — simulator reproduces the incumbent.\n")


def screen():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    yrs_full = (today - pd.Timestamp(f"{SCORE_FROM_YEAR}-01-01")).days / 365.25
    yrs_23 = (today - pd.Timestamp("2023-01-01")).days / 365.25

    print("=" * 78)
    print("DONCHIAN UNIVERSE SCREEN  %d/%d ATR%dx%.1f  %.0f%% risk  (%s)"
          % (ENTRY_LB, EXIT_LB, ATR_P, ATR_MULT, RISK_PCT, today.date()))
    print("params identical on every instrument — no per-market tuning")
    print("verdicts judged on the 'real' cost column; scored from %d"
          % SCORE_FROM_YEAR)
    print("=" * 78)

    verdicts, all_recs = {}, {}
    for cls, syms in UNIVERSE.items():
        print("\n### %s" % cls.upper())
        for sym in syms:
            spec = build_spec(sym, cls)
            if spec is None:
                print("  %-8s NOT SCORED — no tick specs / not offered" % sym)
                verdicts[sym] = None
                continue
            d1 = load(sym)
            if d1 is None:
                print("  %-8s NOT SCORED — insufficient H1 history" % sym)
                verdicts[sym] = None
                continue
            start_year = d1["bdate"].iloc[0].year
            if start_year > MIN_HISTORY_START_YEAR:
                print("  %-8s NOT SCORED — history starts %d (need <= %d)"
                      % (sym, start_year, MIN_HISTORY_START_YEAR))
                verdicts[sym] = None
                continue

            # floor the recorded spread at the live snapshot before scoring
            spec["floor"] = spec["live_spread"]
            rec_med = d1["close_spread"].median()

            cols = {}
            for cm in ("spread", "real", "stress"):
                tr, _eq, rc = simulate(spec, d1, "close", cm,
                                       since_year=SCORE_FROM_YEAR)
                cols[cm] = (stats(tr, rc, yrs_full), rc)
            s_real, recs_real = cols["real"]
            if s_real is None or s_real["n"] < BAR_MIN_N:
                n = 0 if s_real is None else s_real["n"]
                print("  %-8s NOT SCORED — N=%d < %d in %d+"
                      % (sym, n, BAR_MIN_N, SCORE_FROM_YEAR))
                verdicts[sym] = None
                continue

            tr23, _e, rc23 = simulate(spec, d1, "close", "real", since_year=2023)
            s23 = stats(tr23, rc23, yrs_23)
            trtr, _e, rctr = simulate(spec, d1, "close", "real",
                                      since_year=TRAIN_YEARS[0],
                                      until_year=TRAIN_YEARS[1])
            s_tr = stats(trtr, rctr, TRAIN_YEARS[1] - TRAIN_YEARS[0] + 1)
            trte, _e, rcte = simulate(spec, d1, "close", "real",
                                      since_year=TEST_FROM_YEAR)
            s_te = stats(trte, rcte, yrs_full)

            ok = (s_real["pf"] >= BAR_PF and s_real["n"] >= BAR_MIN_N
                  and s_real["avgR"] > 0
                  and s_te is not None and s_te["avgR"] > 0)
            verdicts[sym] = ok
            all_recs[sym] = recs_real

            def pf(s):
                return "  --  " if s is None else "%6.2f" % s["pf"]

            print("  %-8s %s  spread=%.5f(rec %.5f) comm=%.5f  DPP=%.4g"
                  % (sym, "PASS" if ok else "fail", spec["floor"], rec_med,
                     spec["comm"], spec["dpp"]))
            print("      %d+  N=%3d WR=%2.0f%% PF rec%s real%s stress%s "
                  "avgR=%+.3f CAGR=%+5.1f%% DD=%4.1f%%"
                  % (SCORE_FROM_YEAR, s_real["n"], s_real["wr"],
                     pf(cols["spread"][0]), pf(s_real), pf(cols["stress"][0]),
                     s_real["avgR"], s_real["cagr"], s_real["dd"]))
            print("      train %d-%d PF%s avgR%+.3f (N=%s) | test %d+ PF%s "
                  "avgR%+.3f (N=%s) | 2023+ PF%s avgR%+.3f (N=%s)"
                  % (TRAIN_YEARS[0], TRAIN_YEARS[1], pf(s_tr),
                     0.0 if s_tr is None else s_tr["avgR"],
                     "0" if s_tr is None else s_tr["n"],
                     TEST_FROM_YEAR, pf(s_te),
                     0.0 if s_te is None else s_te["avgR"],
                     "0" if s_te is None else s_te["n"],
                     pf(s23), 0.0 if s23 is None else s23["avgR"],
                     "0" if s23 is None else s23["n"]))

    portfolio(verdicts, all_recs)
    return verdicts


def portfolio(verdicts, all_recs):
    """What the passers look like TOGETHER — the point of the exercise.

    Also measures the two PORTFOLIO_GATE limits the live bot would enforce, so
    a 'pass' that the gate would silently throttle is visible as such rather
    than discovered in production.
    """
    passers = [s for s, v in verdicts.items() if v]
    print("\n" + "=" * 78)
    print("PORTFOLIO — %d passing instrument(s): %s"
          % (len(passers), ", ".join(passers) if passers else "none"))
    print("=" * 78)
    if not passers:
        print("  nothing extends BTC_DONCHIAN on these rules.")
        return

    rows = [r for s in passers for r in all_recs[s]]
    rows.sort(key=lambda r: r["in"])
    R = np.array([r["R"] for r in rows])
    wins, losses = R[R > 0].sum(), abs(R[R <= 0].sum())
    print("  combined  N=%d  avgR=%+.3f  PF=%.2f  WR=%.0f%%"
          % (len(R), R.mean(), (wins / losses) if losses else float("inf"),
             (R > 0).mean() * 100))

    # concurrency: how many legs open on any given day, vs PORTFOLIO_GATE
    days, ccy_days = {}, {}
    for r in rows:
        for d in pd.date_range(r["in"], r["out"], freq="D"):
            days[d] = days.get(d, 0) + 1
            if len(r["sym"]) == 6 and r["sym"].isalpha():
                for c in (r["sym"][:3], r["sym"][3:]):
                    ccy_days[(d, c)] = ccy_days.get((d, c), 0) + 1
    peak = max(days.values()) if days else 0
    p95 = int(np.percentile(list(days.values()), 95)) if days else 0
    print("  concurrent positions: peak=%d  p95=%d   (PORTFOLIO_GATE "
          "max_positions=9)" % (peak, p95))
    if ccy_days:
        worst = max(ccy_days.items(), key=lambda kv: kv[1])
        by_ccy = {}
        for (d, c), n in ccy_days.items():
            by_ccy[c] = max(by_ccy.get(c, 0), n)
        print("  peak legs per currency: %s   (gate max_per_currency=4)"
              % ", ".join("%s=%d" % (c, n) for c, n in
                          sorted(by_ccy.items(), key=lambda kv: -kv[1])[:6]))
        over = [c for c, n in by_ccy.items() if n > 4]
        if over:
            print("    ^ %s would be THROTTLED by the live gate — the screened"
                  % ", ".join(over))
            print("      portfolio is not the one the bot would actually run.")
    if peak > 9:
        print("    ^ peak exceeds max_positions=9; entries would be dropped.")

    # correlation of monthly R between passers — the diversification claim
    if len(passers) > 1:
        ser = {}
        for s in passers:
            d = {}
            for r in all_recs[s]:
                k = (r["out"].year, r["out"].month)
                d[k] = d.get(k, 0.0) + r["R"]
            ser[s] = d
        keys = sorted(set().union(*[set(d) for d in ser.values()]))
        M = pd.DataFrame({s: [ser[s].get(k, 0.0) for k in keys]
                          for s in passers})
        c = M.corr().values
        iu = np.triu_indices_from(c, k=1)
        print("  monthly-R correlation across passers: mean=%.2f max=%.2f"
              % (np.nanmean(c[iu]), np.nanmax(c[iu])))
        print("    (low mean correlation is the entire reason to add markets;")
        print("     if this is high the extra instruments are one bet again.)")


if __name__ == "__main__":
    sanity_gate()
    screen()
    print("\nNOTE: pass/fail here is a SCREEN, not a deploy decision. Anything")
    print("passing still needs the portfolio-gate question settled and a")
    print("staged rollout at research risk, per CLAUDE.md.")
    mt5.shutdown()
