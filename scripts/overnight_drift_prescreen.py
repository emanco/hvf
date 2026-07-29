"""Overnight-vs-intraday PRE-SCREEN for IC index CFDs (VPS, read-only).

Documented fact in equities: index returns accrue disproportionately OVERNIGHT
(cash close -> next cash open), with the cash session contributing little or
nothing. The question for us is purely a cost question: a "buy at cash close,
sell at cash open" rule pays a spread round-trip and one financing charge EVERY
night, ~252 times a year. Does that eat the drift?

This is a PRE-SCREEN, not a backtest. It does not simulate a strategy, has no
parameters to fit, and cannot produce a PF. It answers exactly one question:
"is there gross drift left after per-night costs, i.e. is a backtest worth
writing?" A negative answer here kills the idea for ~zero effort.

Method
  - H1 bars -> true UTC (IC's broker clock is UTC+2/+3, DST-aware).
  - Log returns close[i]/close[i-1], labelled by the true-UTC hour of bar i, so
    they sum exactly to the total return and gaps are captured, not dropped.
  - Each bar is DAY if its hour falls in the instrument's cash session, else
    NIGHT. Sum by label => exact decomposition of total return.
  - Cost: spread round-trip per night, floored at the LIVE symbol_info spread.
    IC's recorded per-bar spread field medians to ~0 on raw feeds (known trap),
    so the recorded number alone would understate cost badly.
  - Financing: swap_long printed raw with its mode, converted where the mode
    makes conversion unambiguous.

Usage:
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/overnight_drift_prescreen.py
"""
import os
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

# cash session in true UTC, inclusive hour range (approximate; DST shifts these
# by an hour twice a year, which blurs the boundary bars but not the aggregate)
SYMS = {
    "US500": (14, 20), "USTEC": (14, 20), "US30": (14, 20),
    "DE40": (8, 16), "F40": (8, 16), "UK100": (8, 16),
    "JP225": (0, 5), "HK50": (1, 7),
}
SINCE_YEAR = 2019
TEST_FROM_YEAR = 2022
BARS = 99000

SWAP_MODES = {0: "DISABLED", 1: "POINTS", 2: "CCY_SYMBOL", 3: "CCY_MARGIN",
              4: "CCY_DEPOSIT", 5: "INTEREST_CURRENT", 6: "INTEREST_OPEN",
              7: "REOPEN_CURRENT", 8: "REOPEN_BID"}

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


def load(sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, BARS)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")
    off = df["tb"].apply(lambda t: eu_dst_offset(
        (t - pd.Timedelta(hours=3)).tz_localize("UTC")))
    df["tu"] = df["tb"] - pd.to_timedelta(off, unit="h")
    info = mt5.symbol_info(sym)
    df["spread_price"] = df["spread"] * info.point
    return df.iloc[:-1]


def decompose(df, h0, h1, since_year):
    d = df[df["tu"].dt.year >= since_year].copy()
    if len(d) < 500:
        return None
    d["lr"] = np.log(d["close"] / d["close"].shift(1))
    d = d.dropna(subset=["lr"])
    # a bar belongs to DAY if its hour is inside the cash session
    hr = d["tu"].dt.hour
    d["is_day"] = (hr >= h0) & (hr <= h1)
    # one "night" per calendar date on which any night bar exists
    d["date"] = d["tu"].dt.date
    nights = d.loc[~d["is_day"]].groupby("date")["lr"].sum()
    days = d.loc[d["is_day"]].groupby("date")["lr"].sum()
    yrs = (d["tu"].iloc[-1] - d["tu"].iloc[0]).days / 365.25
    return {
        "n_nights": len(nights), "n_days": len(days), "years": yrs,
        "night_total": nights.sum(), "day_total": days.sum(),
        "night_mean": nights.mean(), "day_mean": days.mean(),
        "night_sd": nights.std(), "px": d["close"].median(),
        "rec_spread": d["spread_price"].median(),
    }


def bp(x):
    return x * 1e4


print("=" * 78)
print("OVERNIGHT vs INTRADAY PRE-SCREEN  --  IC index CFDs")
print("night = outside cash session, day = inside. log returns, so they add up.")
print("=" * 78)

rows = []
for sym, (h0, h1) in SYMS.items():
    info = mt5.symbol_info(sym)
    if info is None:
        print("\n%-7s not available on this account" % sym)
        continue
    df = load(sym)
    if df is None:
        print("\n%-7s no H1 history" % sym)
        continue

    live_spread = info.spread * info.point
    r = decompose(df, h0, h1, SINCE_YEAR)
    if r is None:
        print("\n%-7s insufficient history since %d" % (sym, SINCE_YEAR))
        continue

    # cost per night: one round trip, floored at the live spread snapshot
    sp = max(r["rec_spread"], live_spread)
    sp_bp = bp(sp / r["px"])
    swap_mode = SWAP_MODES.get(info.swap_mode, str(info.swap_mode))

    # financing per night as bp of notional.
    # For an index CFD the profit/margin currency IS the index quote currency,
    # so swap and notional are already in the same units -- no FX conversion.
    notional = info.trade_contract_size * r["px"]
    swap_bp = None
    if info.swap_mode == 1:                       # POINTS per lot per night
        swap_bp = bp(info.swap_long * info.point / r["px"])
    elif info.swap_mode in (2, 3):                # currency per lot per night
        swap_bp = bp(info.swap_long / notional)
    elif info.swap_mode in (5, 6):                # annual interest %
        swap_bp = bp(info.swap_long / 100.0 / 360.0)

    gross_bp = bp(r["night_mean"])
    net_bp = gross_bp - sp_bp + (swap_bp if swap_bp is not None else 0.0)
    # triple-swap Wednesday covers the weekend: a weeknight-only holder pays
    # 1+1+3+1 = 6 charges over 4 held nights => 1.5x the headline rate
    net_bp_wed = gross_bp - sp_bp + (swap_bp * 1.5 if swap_bp is not None else 0.0)

    print("\n### %s   (cash session %02d-%02d UTC, %d nights, %.1f yrs since %d)"
          % (sym, h0, h1, r["n_nights"], r["years"], SINCE_YEAR))
    print("    where the return accrues (total log return over the window)")
    print("      NIGHT %+8.2f%%   |   DAY %+8.2f%%"
          % (r["night_total"] * 100, r["day_total"] * 100))
    print("      per night: %+7.2f bp   (sd %6.1f bp)"
          % (gross_bp, bp(r["night_sd"])))
    print("    cost per night (one round trip)")
    print("      spread  recorded %.2f / live %.2f -> using %.2f  = %5.2f bp"
          % (r["rec_spread"], live_spread, sp, sp_bp))
    print("      contract %g x px %.1f = notional %.0f %s/lot"
          % (info.trade_contract_size, r["px"], notional, info.currency_profit))
    if swap_bp is not None:
        print("      swap_long %+.4f %s (%s) = %+5.2f bp/night  (%+.2f w/ triple-Wed)"
              % (info.swap_long, info.currency_profit, swap_mode, swap_bp, swap_bp * 1.5))
    else:
        print("      swap_long %+.4f swap_short %+.4f  mode=%s  (NOT convertible)"
              % (info.swap_long, info.swap_short, swap_mode))
    print("    NET per night: %+6.2f bp  (%+.2f w/ triple-Wed) ->  %+7.1f bp/yr"
          % (net_bp, net_bp_wed, net_bp_wed * (r["n_nights"] / r["years"])))
    verdict = "SURVIVES costs" if net_bp_wed > 0 else "DEAD on costs"
    print("    %s" % verdict)

    r2 = decompose(df, h0, h1, TEST_FROM_YEAR)
    if r2:
        g2 = bp(r2["night_mean"])
        print("    stability %d+: night %+.2f bp/night (vs %+.2f full), net %+.2f bp"
              % (TEST_FROM_YEAR, g2, gross_bp,
                 g2 - sp_bp + ((swap_bp * 1.5) if swap_bp is not None else 0.0)))

    rows.append((sym, gross_bp, sp_bp, swap_bp, net_bp, net_bp_wed))

print("\n" + "=" * 78)
print("SUMMARY  (bp per night, swap at the triple-Wednesday effective rate)")
print("  %-7s %9s %9s %9s %9s   %s"
      % ("sym", "gross", "spread", "swap", "net", ""))
for sym, g, s, w, n, nw in rows:
    print("  %-7s %+9.2f %9.2f %9s %+9.2f   %s"
          % (sym, g, s, ("%+.2f" % (w * 1.5)) if w is not None else "n/a", nw,
             "ok" if nw > 0 else "dead"))
print("=" * 78)
print("Reading this: 'gross' is the raw overnight drift. Costs are paid EVERY")
print("night, so the bar is high. A negative net kills the idea outright; a")
print("thin positive net is not a green light either, because this pre-screen")
print("assumes perfect fills at the session boundary and no slippage.")
mt5.shutdown()
