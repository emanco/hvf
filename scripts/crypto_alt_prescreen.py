"""Crypto-alt PRE-SCREEN for BTC_DONCHIAN — cheap kills before any scoring.

Premise (2026-07-30): the one variable that separated every BTC_DONCHIAN
survivor from every failure is GROSS EDGE SIZE relative to friction + carry.
Crypto gross avgR is +4.6/+6.6R and survives; indices are +0.37..+0.49R and die
on financing. Crypto alts are the same instrument TYPE as the two best
performers, so they are the highest-prior place to look for capacity.

This script does NOT score anything. It answers the three questions that can
disqualify a candidate in minutes, so a full screen is only built for survivors:

  1. FRICTION — spread as % of ATR20. This already killed LTCUSD (64.1%),
     BCHUSD (10.4%) and XNGUSD (8.9%) on 2026-07-29.
     ⚠️ The bar's `spread` field FLOORS AT 0 on raw pricing (BTCUSD and LTCUSD
     both median 0), so the recorded column ALONE says "free" for the very
     illiquid symbols this check exists to catch — a first pass of this script
     promoted LTCUSD at 0.00% against its known 64.1%. Friction is therefore
     `max(recorded median, live tick median) / ATR20`: recorded understates and
     never overstates, so the max is the honest side. Live ticks are sampled
     LIVE_SAMPLES times (the FX breadth screen was left with a single-snapshot
     defect that moved 6 verdicts to 4 across two runs 20 min apart).
  2. HISTORY DEPTH — the screen's own bar needs N >= 40 fills. At the incumbents'
     ~5.5 fills/yr that is ~7.3 years. An instrument whose history starts after
     MIN_START_YEAR cannot reach N=40 and is NOT SCORABLE — which is a different
     verdict from FAILED (the old ASB screen "failed" AUDJPY on one year of
     data).
  3. CARRY — crypto longs pay ~20%/yr and shorts pay exactly 0 on IC. That
     asymmetry is worth ~1.1R per 40-night hold, so it must be read per symbol
     rather than assumed to match BTC/ETH.
  4. MIN-LOT — `vol_min x stop_dist x dpp <= equity x risk_pct`. An instrument
     whose minimum lot exceeds the risk budget is a SILENT NO-OP: correct
     sizing, correct detection, zero fills, and it looks deployed. This is what
     parked XAUUSD/USTEC on 2026-07-29.

PRE-COMMITTED BEFORE LOOKING AT ANY RESULT
  FRICTION_CEILING = 5.0% of median D1 ATR20. At a 1xATR stop that is 0.05R of
    friction per trade — negligible against crypto's gross avgR, and it is
    comfortably above whatever BTCUSD/ETHUSD measure (printed as reference).
  MIN_START_YEAR = 2019 (>= 7.5 years to today, so N=40 is reachable).
  A candidate is PROMOTED to the full screen only if it clears BOTH. No PF is
  computed here and none should be quoted from this file. The min-lot column is
  reported for survivors but is not a promotion gate — it is an account-size
  fact that can change with a deposit, not a property of the instrument.
"""
import os
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

FRICTION_CEILING = 5.0        # % of median D1 ATR20
MIN_START_YEAR = 2019
ATR_P = 20
INCUMBENTS = ("BTCUSD", "ETHUSD")
LIVE_SAMPLES = 5              # live tick spread samples per symbol
LIVE_SAMPLE_GAP_SEC = 3.0
RISK_PCT = 1.0                # the incumbents' crypto risk band

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()
ACCT_CCY = mt5.account_info().currency

SWAP_MODE_NAME = {0: "DISABLED", 1: "POINTS", 2: "CCY_SYMBOL", 3: "CCY_MARGIN",
                  4: "CCY_DEPOSIT", 5: "INTEREST_CURRENT", 6: "INTEREST_OPEN",
                  7: "REOPEN_CURRENT", 8: "REOPEN_BID"}


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load_d1(sym):
    """Broker-day D1 from H1, exactly as the incumbent screen builds it."""
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000)
    if rates is None or len(rates) < 500:
        return None
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")
    point = mt5.symbol_info(sym).point
    df["spread_price"] = df["spread"] * point
    df = df.iloc[:-1]
    df["bdate"] = df["tb"].dt.date
    d1 = df.groupby("bdate").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), spread=("spread_price", "last")).reset_index()
    return d1


def atr(d1, period=ATR_P):
    h, l, c = d1["high"], d1["low"], d1["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def swap_pct_yr(sym, px):
    """Annual carry as a RATE ON NOTIONAL, per direction. Positive = you pay.
    Ported from donchian_financing_rescore.swap_fn — never assume the mode."""
    info = mt5.symbol_info(sym)
    m, sl, ss, pt = info.swap_mode, info.swap_long, info.swap_short, info.point
    note = SWAP_MODE_NAME.get(m, "mode%d" % m)
    if m == 0:
        return 0.0, 0.0, note
    if m in (5, 6):
        return -sl, -ss, note
    dpp = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size else 0
    if not dpp:
        return None, None, note + " (no dpp)"
    if m == 1:
        return (-sl * pt * 360.0 / px * 100.0,
                -ss * pt * 360.0 / px * 100.0, note)
    if m in (2, 3, 4):
        ccy = (info.currency_base if m == 2 else
               info.currency_margin if m == 3 else ACCT_CCY)
        def conv(a):
            if ccy == ACCT_CCY:
                return a
            for pair, inv in ((ccy + ACCT_CCY, False), (ACCT_CCY + ccy, True)):
                mt5.symbol_select(pair, True)
                t = mt5.symbol_info_tick(pair)
                if t and t.bid:
                    return a / t.bid if inv else a * t.bid
            return None
        aL, aS = conv(sl), conv(ss)
        if aL is None or aS is None:
            return None, None, note + " (no fx rate)"
        return (-aL / dpp * 360.0 / px * 100.0,
                -aS / dpp * 360.0 / px * 100.0, note)
    return None, None, note + " UNHANDLED"


def sample_live_spreads(syms):
    """Round-robin so every symbol is sampled at the same wall-clock instants,
    and the whole sweep costs LIVE_SAMPLES x gap rather than N x that."""
    acc = {s: [] for s in syms}
    for i in range(LIVE_SAMPLES):
        for s in syms:
            t = mt5.symbol_info_tick(s)
            if t and t.ask and t.bid and t.ask > t.bid:
                acc[s].append(t.ask - t.bid)
        if i < LIVE_SAMPLES - 1:
            time.sleep(LIVE_SAMPLE_GAP_SEC)
    return {s: (float(np.median(v)) if v else float("nan")) for s, v in acc.items()}


def min_lot_risk_pct(sym, stop_dist, equity):
    """Risk of ONE minimum lot as % of equity. Never assume a value-per-point."""
    info = mt5.symbol_info(sym)
    if not info.trade_tick_size:
        return None
    dpp = info.trade_tick_value / info.trade_tick_size
    return info.volume_min * stop_dist * dpp / equity * 100.0


def discover():
    """Every crypto symbol the broker offers, not a hand-maintained list."""
    out = []
    for s in mt5.symbols_get():
        path = (s.path or "").lower()
        if "crypto" in path:
            out.append(s.name)
    return sorted(set(out))


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    print("=" * 96)
    print("CRYPTO-ALT PRE-SCREEN  %s   (no PF computed here by design)"
          % today.date())
    print("  friction ceiling %.1f%% of D1 ATR20 | history must start <= %d"
          % (FRICTION_CEILING, MIN_START_YEAR))
    print("=" * 96)

    syms = discover()
    print("broker offers %d crypto symbols: %s\n" % (len(syms), ", ".join(syms)))
    for s in syms:
        mt5.symbol_select(s, True)

    equity = mt5.account_info().equity
    live = sample_live_spreads(syms)
    print("live spread: median of %d ticks %ds apart | equity $%.0f, risk %.1f%%\n"
          % (LIVE_SAMPLES, LIVE_SAMPLE_GAP_SEC, equity, RISK_PCT))

    print("  %-9s %-11s %6s %9s %9s %9s %8s  %7s %7s %8s  %s"
          % ("sym", "start", "D1", "rec_sp", "live_sp", "ATR20", "sp/ATR",
             "swapL%", "swapS%", "minlot%", "verdict"))
    promote, rejected = [], []
    for sym in syms:
        d1 = load_d1(sym)
        if d1 is None or len(d1) < 100:
            print("  %-9s %-11s %6s  -- no usable H1 history" % (sym, "?", "-"))
            rejected.append((sym, "no history"))
            continue
        a = atr(d1)
        med_atr = float(a.median())
        rec_sp = float(d1["spread"].median())
        live_sp = live.get(sym, float("nan"))
        # recorded floors at 0 and never overstates -> the max is the honest side
        eff_sp = max(rec_sp, 0.0 if pd.isna(live_sp) else live_sp)
        ratio = eff_sp / med_atr * 100 if med_atr else float("inf")
        start = min(d1["bdate"])
        px = float(d1["close"].iloc[-1])
        rL, rS, note = swap_pct_yr(sym, px)
        # stop is 1x current ATR20, matching the live rule
        cur_atr = float(a.iloc[-1])
        ml = min_lot_risk_pct(sym, cur_atr, equity)

        reasons = []
        if start.year > MIN_START_YEAR:
            reasons.append("history %d" % start.year)
        if ratio > FRICTION_CEILING:
            reasons.append("friction %.1f%%" % ratio)
        if rL is None:
            reasons.append("carry unreadable")
        if pd.isna(live_sp):
            reasons.append("no live tick")
        tag = ("PROMOTE" if not reasons and sym not in INCUMBENTS
               else "incumbent (reference)" if sym in INCUMBENTS
               else "reject: " + ", ".join(reasons))
        print("  %-9s %-11s %6d %9.4f %9.4f %9.4f %7.2f%%  %+7.1f %+7.1f %7s  %s"
              % (sym, start, len(d1), rec_sp, live_sp, med_atr, ratio,
                 rL if rL is not None else float("nan"),
                 rS if rS is not None else float("nan"),
                 "n/a" if ml is None else "%.2f" % ml, tag))
        if not reasons and sym not in INCUMBENTS:
            promote.append(sym)
        elif sym not in INCUMBENTS:
            rejected.append((sym, ", ".join(reasons)))

    print("\n" + "=" * 96)
    print("OUTCOME")
    print("=" * 96)
    yrs_needed = 40 / 5.5
    print("  N>=40 at the incumbents' ~5.5 fills/yr needs ~%.1f years of history."
          % yrs_needed)
    if promote:
        print("  PROMOTE to full screen (%d): %s" % (len(promote), ", ".join(promote)))
        print("  -> next step is a pre-committed screen on the UNCHANGED rule")
        print("     (55/20, ATR20x1.0, close entry) with financing charged and")
        print("     the 8 incumbent pins gating it.")
    else:
        print("  NOTHING to promote. No full screen is warranted.")
    if rejected:
        print("\n  rejected / not scorable:")
        for s, why in rejected:
            print("    %-9s %s" % (s, why))
    print("\n  NOTE: rejection here is on FRICTION, HISTORY and CARRY only — the")
    print("  cheap, decisive checks. Nothing above is a statement about edge.")
    print("  minlot%% is risk of ONE minimum lot at a 1xATR stop; > %.1f%% means the"
          % RISK_PCT)
    print("  sizer refuses every signal and the instrument is a silent no-op.")


if __name__ == "__main__":
    main()
