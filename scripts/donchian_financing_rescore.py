"""BTC_DONCHIAN financing re-score — does overnight swap change the verdict?

WHY (2026-07-29): every hvf backtest charges one round-trip cost at entry and
nothing per night. That is harmless for intraday strategies, but BTC_DONCHIAN
holds ~40 days across six live instruments, and IC's financing is both large and
direction-asymmetric (crypto longs 20%/yr, crypto shorts exactly 0; gold shorts
are PAID). Unmodelled cost lands preferentially on LONGS — i.e. on the winning
side of an up-trending sample — so it is the one omission that could flatter
this strategy specifically. The two live winners paid zero swap only because
both happened to be shorts.

METHOD
  - Everything above "END PORTED" is spliced VERBATIM from
    scripts/donchian_universe_screen.py, which is itself a verbatim port of
    scripts/btc_donchian_honest_bt.py. This script does not re-derive the fill
    model, the cost model or the sizing (see CLAUDE.md "Negative results" for
    what re-deriving one did to pair_extension_screen.py).
  - The ONLY behavioural change is a per-night financing charge, applied through
    an optional `fin` callable that defaults to None. Entry, exit, trailing and
    lot sizing are untouched, so trade COUNT must be identical with financing on
    and off — asserted at runtime.
  - Nights are counted as calendar-day deltas between bars, so the Fri->Mon gap
    costs 3 nights. That is how the weekend is actually financed; no
    triple-swap-Wednesday multiplier is layered on top of it.
  - Financing rates are read live from MT5 per instrument, dispatching on
    `swap_mode` (1=POINTS, 2/3/4=currency per lot, 5/6=annual %). The mode is
    NEVER assumed: reading a 20%/yr INTEREST rate as a currency amount produced
    a 15R fake cost on ETHUSD in an earlier pass. Currency modes are converted
    to the account currency via a live cross, and the script REFUSES (prints,
    skips) rather than guessing if it cannot prove the rate.
  - Cross-check printed for every instrument: financing re-expressed as %/yr of
    notional, flagged if outside -5%..+60%. A broken mode or a flipped FX
    conversion shows up there immediately rather than as a plausible-looking PF.

INCUMBENT SANITY GATE
  Runs first, with financing OFF, and must reproduce all 8 of the
  donchian_universe_screen pins on PF *and* N or the script exits non-zero.
  That is what proves the financing patch is behaviour-neutral when disabled.

PRE-COMMITTED BEFORE LOOKING AT ANY RESULT
  - Same bar as the screen that deployed these instruments: real-cost PF >= 1.30
    on the full window, N >= 40, avgR > 0, and avgR > 0 on the held-out 2022+
    test leg. No new bar invented after seeing the damage.
  - Judged on the "real" cost column, entry at close (the live rule since the
    2026-07-02 rollover-gate fix).
  - Today's swap rates are applied across the whole window. This is
    anachronistically harsh on 2017-2021 (policy rates ~0), so the 2022+ leg is
    the more decision-relevant row for a forward decision. Stated here, before
    the run, so it cannot become a post-hoc excuse for a bad result.

Usage (read-only, nothing is deployed by this script):
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -u -" < scripts/donchian_financing_rescore.py
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
             until_year=None, cutoff=None, fin=None):
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
                              "in": row["bdate"], "last": row["bdate"], "fin": 0.0}
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




# ======================================================== FINANCING RE-SCORE ==

DEPLOYED = [("BTCUSD", "crypto", 1.0), ("ETHUSD", "crypto", 1.0),
            ("XAUUSD", "metal", 0.5), ("USTEC", "index", 0.5),
            ("JP225", "index", 0.5), ("US500", "index", 0.5)]

SWAP_MODE_NAME = {0: "DISABLED", 1: "POINTS", 2: "CCY_SYMBOL",
                  3: "CCY_MARGIN", 4: "CCY_DEPOSIT", 5: "INTEREST_CURRENT",
                  6: "INTEREST_OPEN", 7: "REOPEN_CURRENT", 8: "REOPEN_BID"}

ACCT_CCY = mt5.account_info().currency


def to_acct(amount, ccy):
    """Convert `amount` in `ccy` to the account currency, or None if we cannot
    prove the rate. Returning None is deliberate — a silently wrong FX rate is
    exactly the value-per-point trap in CLAUDE.md, so we refuse rather than
    guess."""
    if ccy == ACCT_CCY:
        return amount
    for pair, invert in ((ccy + ACCT_CCY, False), (ACCT_CCY + ccy, True)):
        mt5.symbol_select(pair, True)
        t = mt5.symbol_info_tick(pair)
        if t and t.bid:
            return amount / t.bid if invert else amount * t.bid
    return None


def swap_fn(sym, dpp, px_now):
    """Per-night financing COST in price units (positive = you pay).

    `swap_mode` is read per instrument and never assumed — modes differ across
    instruments on the same account, and treating an INTEREST rate as a currency
    amount gave a 15R fake cost on ETHUSD once already.

    Every mode is normalised to an ANNUAL RATE ON NOTIONAL at today's price, and
    the charge is then applied as `px * rate/360` on each historical bar. This
    matters more than it looks. Modes 1/2/3/4 quote a FIXED amount per lot per
    night; holding that amount constant back through history charges the same
    dollars against a 5x smaller index, which inflates the cost in R by 5x for
    no economic reason. Broker financing is economically a rate on notional and
    the broker republishes the fixed amount as the index moves, so the rate is
    the invariant to carry backwards — not the currency amount.

    The residual assumption is that today's RATE held historically. It did not
    (policy rates were ~0 pre-2022), which is the pre-committed caveat that
    makes 2022+ the decision leg. That one is unavoidable without a rate
    history; the price-level one was pure model error.
    """
    info = mt5.symbol_info(sym)
    m, sl, ss, pt = info.swap_mode, info.swap_long, info.swap_short, info.point
    note = SWAP_MODE_NAME.get(m, "mode%d" % m)

    if m == 0:
        return (lambda d, px: 0.0), 0.0, 0.0, note + " (no financing)"
    if m in (5, 6):                       # already an annual interest %
        rL, rS = -sl, -ss
        detail = "long %+.3g%%/yr short %+.3g%%/yr (native)" % (sl, ss)
    elif m == 1:                          # points per lot per night
        rL = -sl * pt * 360.0 / px_now * 100.0
        rS = -ss * pt * 360.0 / px_now * 100.0
        detail = "long %+.4g pts short %+.4g pts /night" % (sl, ss)
    elif m in (2, 3, 4):                  # currency per lot per night
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


def rescore():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    yrs_full = (today - pd.Timestamp(f"{SCORE_FROM_YEAR}-01-01")).days / 365.25
    yrs_test = (today - pd.Timestamp(f"{TEST_FROM_YEAR}-01-01")).days / 365.25

    print("=" * 78)
    print("BTC_DONCHIAN FINANCING RE-SCORE   (%s)" % today.date())
    print("Same rule, same fills, same round-trip cost. The ONLY delta is a")
    print("per-night swap charge on every night the trade is held.")
    print("=" * 78)
    print("\nLIVE SWAP SPECS (read from MT5 now; %s account)" % ACCT_CCY)

    fns = {}
    for sym, cls, risk in DEPLOYED:
        spec = build_spec(sym, cls)
        if spec is None:
            print("  %-8s NO TICK SPECS" % sym)
            continue
        tick = mt5.symbol_info_tick(sym)
        px = tick.bid if tick and tick.bid else None
        if px is None:
            print("  %-8s NO TICK" % sym)
            continue
        f, annL, annS, note = swap_fn(sym, spec["dpp"], px)
        if f is None:
            print("  %-8s %s" % (sym, note))
            continue
        # cheap tripwire: an index/crypto CFD financed outside this band means
        # the mode or the FX conversion is wrong, not that the broker is exotic
        flag = "" if -5.0 <= annL <= 60.0 else "   <-- IMPLAUSIBLE, CHECK MODE"
        print("  %-8s %-52s" % (sym, note))
        print("           px=%.5g  cost/yr: long %+6.2f%%  short %+6.2f%%%s"
              % (px, annL, annS, flag))
        fns[sym] = (spec, f)

    print("\n" + "=" * 78)
    print("RE-SCORE  |  real-cost column, entry at close (the live rule)")
    print("=" * 78)

    pooled = {"off": [], "on": []}
    for sym, cls, risk in DEPLOYED:
        if sym not in fns:
            continue
        spec, f = fns[sym]
        d1 = load(sym)
        if d1 is None:
            print("  %-8s no history" % sym)
            continue
        spec["floor"] = spec["live_spread"]

        out = {}
        for per, sy, yrs in (("%d+" % SCORE_FROM_YEAR, SCORE_FROM_YEAR, yrs_full),
                             ("%d+" % TEST_FROM_YEAR, TEST_FROM_YEAR, yrs_test)):
            for lbl, fin in (("off", None), ("on", f)):
                tr, _eq, rc = simulate(spec, d1, "close", "real",
                                       since_year=sy, fin=fin)
                out[(per, lbl)] = (stats(tr, rc, yrs), rc)

        full = "%d+" % SCORE_FROM_YEAR
        test = "%d+" % TEST_FROM_YEAR
        s_off, rc_off = out[(full, "off")]
        s_on, rc_on = out[(full, "on")]
        if s_off is None or s_on is None:
            print("  %-8s no trades" % sym)
            continue
        assert s_off["n"] == s_on["n"], "financing changed trade count — bug"

        longs = [r for r in rc_on if r["dir"] == "L"]
        shorts = [r for r in rc_on if r["dir"] == "S"]
        nights = np.mean([r["nights"] for r in rc_on])
        nL = np.mean([r["nights"] for r in longs]) if longs else 0.0
        nS = np.mean([r["nights"] for r in shorts]) if shorts else 0.0
        finL = np.mean([r["finR"] for r in longs]) if longs else 0.0
        finS = np.mean([r["finR"] for r in shorts]) if shorts else 0.0

        st_off, _ = out[(test, "off")]
        st_on, _ = out[(test, "on")]

        def pf(s):
            return "  --  " if s is None else "%6.2f" % s["pf"]

        def ar(s):
            return 0.0 if s is None else s["avgR"]

        verdict = ("PASS" if (s_on["pf"] >= BAR_PF and s_on["n"] >= BAR_MIN_N
                              and s_on["avgR"] > 0 and st_on is not None
                              and st_on["avgR"] > 0) else "FAIL")
        print("\n  %-7s risk %.1f%%   N=%d   %d%% long   avg hold %.0f nights"
              % (sym, risk, s_on["n"], 100 * len(longs) / len(rc_on), nights))
        print("      financing per trade:  long %+.3fR over %.0f nights"
              "   short %+.3fR over %.0f nights" % (finL, nL, finS, nS))
        print("      %-6s PF %s -> %s    avgR %+.3f -> %+.3f"
              % (full, pf(s_off), pf(s_on), ar(s_off), ar(s_on)))
        print("      %-6s PF %s -> %s    avgR %+.3f -> %+.3f   [held-out test]"
              % (test, pf(st_off), pf(st_on), ar(st_off), ar(st_on)))
        print("      bar (PF>=%.2f full, N>=%d, avgR>0, test avgR>0):  %s"
              % (BAR_PF, BAR_MIN_N, verdict))

        pooled["off"] += [r["R"] for r in rc_off]
        pooled["on"] += [r["R"] for r in rc_on]

    print("\n" + "=" * 78)
    print("POOLED (equal-R, all six deployed instruments, %d+)" % SCORE_FROM_YEAR)
    for lbl in ("off", "on"):
        R = np.array(pooled[lbl])
        gp, gl = R[R > 0].sum(), abs(R[R <= 0].sum())
        print("  financing %-3s  N=%d  PF=%.2f  avgR=%+.3f  WR=%.0f%%"
              % (lbl, len(R), gp / gl if gl else float("inf"),
                 R.mean(), 100 * (R > 0).mean()))
    print("=" * 78)
    print("""
CAVEAT, stated before the numbers were read: today's swap rates are applied
across the whole window, including 2017-2021 when policy rates were ~0. That is
anachronistically harsh on the early years and is the same caveat that qualified
the index-reversal screen. For a FORWARD decision today's rate is the right one,
so the %d+ test leg is the more decision-relevant row.""" % TEST_FROM_YEAR)


sanity_gate()          # must reproduce all 8 pins with fin=None
rescore()
mt5.shutdown()
