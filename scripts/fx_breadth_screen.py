"""FX breadth screen — can one intraday rule run across the low-friction majors
at a frequency that is actually validatable?

THE PREMISE (2026-07-30)
Every edge in this portfolio is statistically unfalsifiable. ASB needs 923 fills
= 26 years at 2.6 fills/mo; BTC_DONCHIAN needs 21 years (BTCUSD) to 5,916
(USTEC). The binding constraint is not method, it is FILL RATE. So this screen
optimises for a property no existing strategy has: enough trades per year that
live data can settle the question inside 1-2 years.

  N for 80% power = 7.85 * sd(R)^2 / avgR^2.  At sd 0.60:
    avgR +0.05 -> 1130 fills    avgR +0.10 -> 283    avgR +0.15 -> 126
  At 300 fills/yr that is 3.8yr / 0.9yr / 0.4yr. At ASB's 30/yr: 38 / 9 / 4yr.

Frequency has to come from BREADTH, not from trading one pair harder. Measured
on EURUSD (8y H1, local cache) against ~1.0p round trip (raw spread ~0.1p +
$7/lot commission):

    horizon   stop (1xATR20)   friction/trade   share of a 0.15R gross edge
    H1              13p            0.077R                  51%
    H4              27p            0.037R                  25%
    D1              75p            0.013R                   9%

An H1 stop puts EURUSD at 0.077R of friction — the same wall that killed
LONDON_BO (0.11R on a 15p stop) and scalping. Trading one pair 200x/yr on a 13p
stop burns 15.4R/yr = $5,800 at 1% risk on $37.7k. The same 200 trades spread
over 8 pairs at H4 cost 7.4R. Identical trade count, half the friction, and the
bets are less correlated. Hence: H4-scale stops, many instruments, ONE rule.

THE PRIOR IS BAD AND THAT IS PRE-ACKNOWLEDGED
EURUSD specifically has already been killed six times: ASB 0.73-0.77, the whole
LBO family, NY-open breakout 1.02, Donchian D1 0.77-0.81, scalping (cost math),
KZ_HUNT 0.44. FX D1 trend-following is dead across all 12 pairs (best USDJPY
0.86). This screen is therefore SPEND-CAPPED: it runs once. If nothing clears
the pre-committed bar, intraday FX goes into CLAUDE.md negative results and is
not re-explored without a NEW hypothesis.

PRE-COMMITTED BEFORE LOOKING AT ANY RESULT
  Universe: FX only, selected by MEASURED friction, not by opinion. An
    instrument is in iff (a) H1 history begins <= 2017, and (b) round-trip real
    cost <= FRICTION_CEILING of its median H4 ATR20. The ceiling follows from
    the table above, not from the results. The measured table is printed so the
    selection is auditable.
  Families (2, deliberately small grids — LBO was overfit with 960 cells):
    F1 "H4 Donchian"  — the ONLY family that survived both 2026-07-28 fill
      audits structurally: close-based entry (immune to the blind-gap fill
      fiction) and no SL-modify overlay (immune to the stop-modify-through-
      market fiction). D1 FX is dead, but 4-hour continuation is a different
      phenomenon from multi-week trend. Grid: entry_lb in {20, 55} H4 bars,
      exit_lb = round(entry_lb / 2.75) (Turtle ratio held fixed), ATR20 x 1.0.
      2 cells. No direction fitting at all — the breakout picks the side.
    F2 "USD session drift" — hour-of-day flow, genuinely untested here. Enter at
      the close of true-UTC hour H, exit k hours later or on stop. Grid:
      H in {7, 11, 15, 19} (London open / London a.m. / NY open / NY close —
      flow-motivated, NOT the 24 hours swept), k in {4, 8}, stop 2.0 x ATR20(H1)
      ~= H4 scale. 8 cells. Direction is fitted, but ONE direction per cell
      POOLED across instruments in USD terms (pairs with USD as base are
      sign-flipped), so the whole family costs 8 degrees of freedom, not 8 per
      pair. Crosses have no USD leg and are excluded from F2.
  Cell selection: the winning cell is chosen on TRAIN ONLY, pooled across
    instruments — one cell for every instrument, NO per-pair tuning (that is
    where a crypto-fitted rule overfits 24 markets). Each family then gets
    exactly ONE evaluation on the held-out test leg. 2 test looks total.
  Split: train 2016-2021 inclusive, test 2022+. Fixed here, before results.
  Costs: the decision column is "real" = recorded spread FLOORED at a live
    snapshot, plus commission, WITH overnight financing charged. The recorded
    spread field is unusable alone — it is 0 on 96.6% of EURUSD H1 bars. A
    "stress" column doubles the spread. Verdicts are read off "real" only.
  Financing: charged. NO other hvf backtest does this and it cost the four
    2026-07-29 Donchian additions 20-48% of their PF, pushing three below their
    own bar. F1 holds multiple nights, so it is exposed. swap_mode is read per
    instrument and normalised to an annual RATE ON NOTIONAL before being carried
    backwards (see donchian_financing_rescore.py — holding a fixed per-lot
    amount constant through history inflated USTEC's carry ~5x).
  PASS requires ALL of:
    real-cost FULL PF >= 1.30, pooled N >= 200, avgR > 0 on FULL *and* on the
    held-out TEST leg, pooled test-leg PF >= 1.30, and >= 3.0 fills/week pooled.
    The N and fills/week legs are not decoration — a rule that passes on PF but
    fills 30x/yr fails the entire premise of the screen and is NOT deployed.

SANITY GATE
  This screen's simulate() is a parameterised port of
  donchian_universe_screen.simulate (itself a verbatim port of
  btc_donchian_honest_bt). Fed D1 bars at 55/20/20/1.0 it must reproduce all 8
  BTCUSD/ETHUSD incumbent pins on PF *and* N, in both cost modes and both
  periods, or this script exits non-zero. N is the sharper tripwire: a broken
  filter moves N long before it moves PF. Financing must also leave N EXACTLY
  unchanged (it only scales PnL) — asserted, not eyeballed.
  F2 uses a second engine that the incumbent pins cannot cover, so it carries
  its own identity check: with an unreachable stop, k=1 and zero cost, its PnL
  must equal the sum of close-to-close moves. Asserted at startup.

Run (read-only, safe while the bot is live):
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/fx_breadth_screen.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

# ------------------------------------------------------------- screen policy
SCORE_FROM_YEAR = 2016
TRAIN_YEARS = (2016, 2021)       # inclusive
TEST_FROM_YEAR = 2022
MIN_HISTORY_START_YEAR = 2017    # data must begin at/before this to be scorable

BAR_PF = 1.30
BAR_MIN_N = 200
BAR_FILLS_PER_WEEK = 3.0
FRICTION_CEILING = 0.06          # real round-trip cost / median H4 ATR20

# F1 grid: (entry_lb, exit_lb) in H4 bars. exit_lb = round(entry_lb / 2.75).
F1_GRID = [(20, 7), (55, 20)]
F1_ATR_P, F1_ATR_MULT = 20, 1.0
# F2 grid: entry hour (true UTC) x hold (hours). Stop = 2.0 x ATR20(H1).
F2_HOURS = [7, 11, 15, 19]
F2_HOLDS = [4, 8]
F2_ATR_P, F2_ATR_MULT = 20, 2.0

START_EQ, RISK_PCT = 10000.0, 1.0

UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD",
            "EURJPY", "GBPJPY", "EURGBP", "EURAUD"]
# USD-quoted (long = short USD) vs USD-base (long = long USD). Crosses -> None
# and are excluded from F2, which is a USD-flow family.
USD_SIDE = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1,
            "USDJPY": +1, "USDCHF": +1,
            "EURJPY": None, "GBPJPY": None, "EURGBP": None, "EURAUD": None}

COMMISSION_RT_USD_PER_LOT = 7.0   # IC raw account, FX: $3.50/side/100k

# ------------------------------------------------------------- incumbent pins
# Frozen window so the pins stay reproducible as history accrues. Copied from
# donchian_universe_screen.py, calibrated there 2026-07-29.
CALIBRATE = False
SANITY_CUTOFF = pd.Timestamp("2026-07-01")
SANITY_PF_TOL = 0.02
SANITY_SYMS = {"BTCUSD": 12.0, "ETHUSD": 5.0}    # -> FLAT_COST
DPP_INCUMBENT = 1.0
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

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()
ACCT_CCY = mt5.account_info().currency


# ================================================================== PORTED ===
# eu_dst_offset / load / atr / _cost / stats are behaviourally identical to
# scripts/donchian_universe_screen.py. simulate() is that function with the
# Donchian lookbacks and ATR params lifted into arguments so the same engine can
# be fed D1 bars (sanity gate) or H4 bars (F1). Do not "improve" in place.

def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load_h1(sym):
    """Raw H1 with both clocks. IC depth is ~11y at 99k bars."""
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000)
    if rates is None or len(rates) < 2000:
        return None
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")            # broker clock
    off = df["tb"].apply(lambda t: eu_dst_offset(
        (t - pd.Timedelta(hours=3)).tz_localize("UTC")))
    df["tu"] = df["tb"] - pd.to_timedelta(off, unit="h")        # true UTC
    df["spread_price"] = df["spread"] * mt5.symbol_info(sym).point
    df = df.iloc[:-1]                                          # drop forming bar
    df["bdate"] = df["tb"].dt.date
    return df


def build_d1(df):
    """Broker-day D1 exactly as the incumbent builds it (for the sanity gate)."""
    d1 = df.groupby("bdate").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last")).reset_index()
    utc0 = df[df["tu"].dt.hour == 0].groupby("bdate").agg(
        lag_open=("open", "first"), lag_spread=("spread_price", "first"))
    d1 = d1.merge(utc0, on="bdate", how="left")
    close_sp = df.groupby("bdate").agg(close_spread=("spread_price", "last"))
    d1 = d1.merge(close_sp, on="bdate", how="left")
    return d1


def build_h4(df):
    """H4 on the BROKER clock (MT5 H4 bars align to 00:00 broker)."""
    df = df.copy()
    df["blk"] = df["tb"].dt.floor("4h")
    h4 = df.groupby("blk").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        close_spread=("spread_price", "last"),
        bdate=("bdate", "last")).reset_index()
    return h4


def atr(bars, period):
    h, l, c = bars["high"], bars["low"], bars["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate(spec, bars, entry_mode, cost_mode, entry_lb, exit_lb,
             atr_p, atr_mult, since_year=None, until_year=None, cutoff=None,
             fin=None):
    df = bars.copy()
    if cutoff is not None:
        df = df[pd.to_datetime(df["bdate"]) < cutoff].reset_index(drop=True)
    df["entry_high"] = df["high"].rolling(entry_lb).max().shift(1)
    df["entry_low"] = df["low"].rolling(entry_lb).min().shift(1)
    df["exit_high"] = df["high"].rolling(exit_lb).max().shift(1)
    df["exit_low"] = df["low"].rolling(exit_lb).min().shift(1)
    df["atr"] = atr(df, atr_p).shift(1)
    rows = df.to_dict("records")
    trades, recs = [], []
    equity = START_EQ
    open_t = None
    pending_entry = None
    for i, row in enumerate(rows):
        yr = row["bdate"].year
        if since_year and yr < since_year:
            continue
        if until_year and yr > until_year:
            continue
        if pd.isna(row["entry_high"]) or pd.isna(row["atr"]):
            continue

        if pending_entry is not None and open_t is None:
            direction, sig_atr = pending_entry
            ep, sp = row.get("lag_open"), row.get("lag_spread")
            if ep is None or pd.isna(ep):
                pending_entry = None
            else:
                cost = _cost(spec, cost_mode, sp)
                stop = (ep - atr_mult * sig_atr if direction == "L"
                        else ep + atr_mult * sig_atr)
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
                    ep, sp = row["close"], row.get("close_spread")
                    cost = _cost(spec, cost_mode, sp)
                    stop = (ep - atr_mult * row["atr"] if direction == "L"
                            else ep + atr_mult * row["atr"])
                    open_t = {"dir": direction, "ep": ep, "stop": stop,
                              "isd": abs(ep - stop), "cost": cost,
                              "in": row["bdate"], "last": row["bdate"],
                              "fin": 0.0}
    return np.array(trades), equity, recs


def _cost(spec, cost_mode, sp):
    if cost_mode == "zero":
        return 0.0
    if cost_mode == "spread":
        return sp if not pd.isna(sp) else spec["flat"]
    if cost_mode == "flat":
        return spec["flat"]
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
    R = np.array([r["R"] for r in recs]) if recs else np.array([0.0])
    return {
        "n": len(trades), "wr": w / len(trades) * 100,
        "pf": (gp / gl) if gl > 0 else float("inf"),
        "avgR": float(R.mean()), "sdR": float(R.std(ddof=1)) if len(R) > 1 else 0.0,
        "dd": ddpct,
        "cagr": (((final / START_EQ) ** (1 / years) - 1) * 100
                 if years > 0 and final > 0 else float("nan")),
        "per_wk": len(trades) / (years * 52.0) if years > 0 else 0.0,
    }
# ============================================================== END PORTED ===


# ------------------------------------------------------------------- F2 engine
def simulate_drift(spec, h1, cost_mode, hour, hold, direction,
                   since_year=None, until_year=None, fin=None,
                   no_stop=False):
    """Enter at the close of true-UTC `hour`, exit `hold` hours later or on stop.

    Not covered by the incumbent pins, so it carries its own identity check
    (see _f2_identity_check). Mechanics — cost charged once in price points at
    entry, fixed-fractional sizing with lot rounding, financing per rollover —
    are the same as simulate().
    """
    df = h1.copy().reset_index(drop=True)
    df["atr"] = atr(df, F2_ATR_P).shift(1)
    rows = df.to_dict("records")
    trades, recs = [], []
    equity = START_EQ
    n = len(rows)
    i = 0
    while i < n:
        row = rows[i]
        yr = row["bdate"].year
        if (since_year and yr < since_year) or (until_year and yr > until_year) \
                or pd.isna(row["atr"]) or row["tu"].hour != hour:
            i += 1
            continue
        ep = row["close"]
        cost = 0.0 if no_stop else _cost(spec, cost_mode, row.get("spread_price"))
        isd = F2_ATR_MULT * row["atr"]
        stop = (ep - isd if direction == "L" else ep + isd)
        finR = 0.0
        last_date = row["bdate"]
        pnl_pts, out_date = None, row["bdate"]
        for j in range(i + 1, min(i + 1 + hold, n)):
            b = rows[j]
            if fin is not None:
                nights = (b["bdate"] - last_date).days
                if nights > 0:
                    finR += nights * fin(direction, b["close"])
                last_date = b["bdate"]
            out_date = b["bdate"]
            hit = (b["low"] <= stop) if direction == "L" else (b["high"] >= stop)
            if hit and not no_stop:
                xp = (min(b["open"], stop) if direction == "L"
                      else max(b["open"], stop))
                pnl_pts = ((xp - ep) if direction == "L" else (ep - xp))
                break
            if j == i + hold:
                pnl_pts = ((b["close"] - ep) if direction == "L"
                           else (ep - b["close"]))
                break
        if pnl_pts is not None:
            pnl_pts -= cost + finR
            risk_usd = equity * RISK_PCT / 100.0
            lots = risk_usd / max(isd * spec["dpp"], 0.01)
            lots = max(min(round(lots, 2), 100.0), 0.01)
            usd = pnl_pts * lots * spec["dpp"]
            equity += usd
            trades.append(usd)
            recs.append({"sym": spec["sym"], "dir": direction,
                         "in": row["bdate"], "out": out_date,
                         "R": pnl_pts / isd if isd else 0.0,
                         "nights": (out_date - row["bdate"]).days,
                         "finR": finR / isd if isd else 0.0, "usd": usd})
        i += 1
    return np.array(trades), equity, recs


# ------------------------------------------------------------------ financing
SWAP_MODE_NAME = {0: "DISABLED", 1: "POINTS", 2: "CCY_SYMBOL",
                  3: "CCY_MARGIN", 4: "CCY_DEPOSIT", 5: "INTEREST_CURRENT",
                  6: "INTEREST_OPEN", 7: "REOPEN_CURRENT", 8: "REOPEN_BID"}


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
    """Per-night financing COST in price units (positive = you pay).

    Ported from donchian_financing_rescore.swap_fn. Every mode is normalised to
    an ANNUAL RATE ON NOTIONAL at today's price before being carried backwards —
    holding a fixed per-lot amount constant through history charges today's
    dollars against a smaller notional and inflated USTEC's carry ~5x once.
    """
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


# ----------------------------------------------------------------------- spec
def build_spec(sym):
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
    return {"sym": sym, "dpp": dpp, "comm": COMMISSION_RT_USD_PER_LOT / dpp,
            "live_spread": info.spread * info.point, "point": info.point,
            "flat": SANITY_SYMS.get(sym, 0.0)}


# ----------------------------------------------------------------- gates
def sanity_gate():
    print("=" * 78)
    print("SANITY GATE 1/2 — incumbent Donchian pins (frozen bdate < %s)"
          % SANITY_CUTOFF.date())
    print("=" * 78)
    got_all, failures = {}, []
    for sym, flat in SANITY_SYMS.items():
        h1 = load_h1(sym)
        if h1 is None:
            failures.append("%s: no H1 data" % sym)
            continue
        d1 = build_d1(h1)
        spec = {"sym": sym, "dpp": DPP_INCUMBENT, "flat": flat,
                "comm": 0.0, "floor": 0.0}
        for label, em, cm in (("orig(close+flat)", "close", "flat"),
                              ("HONEST(lag+spread)", "lag", "spread")):
            for per, sy in (("FULL", None), ("2023+", 2023)):
                tr, _eq, rc = simulate(spec, d1, em, cm, 55, 20,
                                       F1_ATR_P, F1_ATR_MULT,
                                       since_year=sy, cutoff=SANITY_CUTOFF)
                st = stats(tr, rc, 1.0)
                key = (sym, label, per)
                got = (round(st["pf"], 2), st["n"])
                got_all[key] = got
                exp = SANITY.get(key)
                if exp is None:
                    failures.append("%s: no pin" % (key,))
                    continue
                ok = (abs(got[0] - exp[0]) <= SANITY_PF_TOL
                      and got[1] == exp[1])
                print("  %-7s %-19s %-6s PF %5.2f (exp %5.2f)  N %3d (exp %3d)"
                      "  %s" % (sym, label, per, got[0], exp[0], got[1],
                                exp[1], "OK" if ok else "** DRIFT **"))
                if not ok:
                    failures.append("%s got %s exp %s" % (key, got, exp))
    if CALIBRATE:
        print("\n  SANITY = {")
        for k, v in got_all.items():
            print("      %r: %r," % (k, v))
        print("  }")
        sys.exit(0)
    if failures:
        print("\n  SANITY GATE FAILED — the ported simulator has drifted from")
        print("  the incumbent. Every number below would be untrustworthy.")
        for f in failures:
            print("    " + f)
        sys.exit(1)
    print("  -> port is faithful (8/8 pins on PF and N)\n")


def _f2_identity_check():
    """F2's engine is not covered by the incumbent pins. With an unreachable
    stop, hold=1 and zero cost, its PnL must be the close-to-close move."""
    print("SANITY GATE 2/2 — F2 engine identity (no stop, k=1, no cost)")
    sym = "EURUSD"
    h1 = load_h1(sym)
    spec = build_spec(sym)
    spec["floor"] = 0.0
    tr, _eq, rc = simulate_drift(spec, h1, "real", 7, 1, "L",
                                 since_year=2024, no_stop=True)
    # independent recomputation straight off the bars
    df = h1.copy().reset_index(drop=True)
    df["atr"] = atr(df, F2_ATR_P).shift(1)
    exp = []
    for i in range(len(df) - 1):
        r = df.iloc[i]
        if r["bdate"].year >= 2024 and r["tu"].hour == 7 and not pd.isna(r["atr"]):
            exp.append((df.iloc[i + 1]["close"] - r["close"]) / (F2_ATR_MULT * r["atr"]))
    gotR = np.array([r["R"] for r in rc])
    expR = np.array(exp)
    ok = len(gotR) == len(expR) and np.allclose(gotR, expR, atol=1e-9)
    print("  N %d (exp %d)  maxdiff %.2e  %s"
          % (len(gotR), len(expR),
             np.abs(gotR - expR).max() if ok else float("nan"),
             "OK" if ok else "** MISMATCH **"))
    if not ok:
        print("  F2 ENGINE FAILED its identity check — aborting.")
        sys.exit(1)
    print("  -> F2 engine reproduces raw close-to-close moves exactly\n")


# ---------------------------------------------------------------------- screen
def friction_table(loaded):
    """Pre-committed universe selection, on MEASURED friction only."""
    print("=" * 78)
    print("UNIVERSE SELECTION — real round-trip cost vs median H4 ATR20")
    print("  ceiling = %.1f%% (pre-committed)" % (FRICTION_CEILING * 100))
    # The spread floor is a LIVE snapshot, so it depends on when this ran.
    # Off-session it is much wider than IC's raw pricing — record the time.
    print("  live spread snapshot taken %s UTC"
          % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    print("=" * 78)
    print("  %-8s %9s %9s %9s %9s %8s  %s"
          % ("sym", "live_sp", "comm", "cost", "H4 ATR", "cost/ATR", "verdict"))
    keep = {}
    for sym, (h1, h4, spec) in loaded.items():
        a = atr(h4, F1_ATR_P).median()
        cost = spec["live_spread"] + spec["comm"]
        ratio = cost / a if a else float("inf")
        ok = ratio <= FRICTION_CEILING
        pt = spec["point"]
        print("  %-8s %9.1f %9.1f %9.1f %9.1f %8.2f%%  %s"
              % (sym, spec["live_spread"] / pt, spec["comm"] / pt, cost / pt,
                 a / pt, ratio * 100, "IN" if ok else "OUT (too dear)"))
        if ok:
            keep[sym] = (h1, h4, spec)
    print("  -> %d of %d instruments in\n" % (len(keep), len(loaded)))
    return keep


def _pool(res):
    """Pool per-instrument (trades, recs) into one equal-risk portfolio."""
    tr = np.concatenate([r[0] for r in res]) if res else np.array([])
    rc = [x for r in res for x in r[2]]
    return tr, rc


def _yrs(a, b):
    return (b - a).days / 365.25


def run_family(name, cells, runner, keep, today):
    """Select the winning cell on TRAIN pooled, then ONE look at TEST."""
    yrs_tr = _yrs(pd.Timestamp(f"{TRAIN_YEARS[0]}-01-01"),
                  pd.Timestamp(f"{TEST_FROM_YEAR}-01-01"))
    yrs_te = _yrs(pd.Timestamp(f"{TEST_FROM_YEAR}-01-01"), today)
    yrs_fu = _yrs(pd.Timestamp(f"{SCORE_FROM_YEAR}-01-01"), today)

    print("=" * 78)
    print("%s — TRAIN %d-%d (cell selection; test leg untouched)"
          % (name, *TRAIN_YEARS))
    print("=" * 78)
    print("  %-22s %5s %6s %7s %8s %7s" % ("cell", "N", "PF", "avgR", "fills/wk", "DD%"))
    scored = []
    for cell in cells:
        res = [runner(cell, sym, keep[sym], TRAIN_YEARS[0], TRAIN_YEARS[1])
               for sym in keep]
        res = [r for r in res if r is not None]
        tr, rc = _pool(res)
        st = stats(tr, rc, yrs_tr)
        if st is None:
            print("  %-22s no trades" % str(cell))
            continue
        print("  %-22s %5d %6.2f %+7.3f %8.2f %7.1f"
              % (str(cell), st["n"], st["pf"], st["avgR"], st["per_wk"], st["dd"]))
        scored.append((st["avgR"], cell, st))
    if not scored:
        print("  -> no cell produced trades; %s is NOT SCORED\n" % name)
        return None
    scored.sort(reverse=True, key=lambda x: x[0])
    best_avgR, best, best_st = scored[0]
    print("  -> train winner: %s (avgR %+.3f). ONE test look now.\n"
          % (str(best), best_avgR))

    print("=" * 78)
    print("%s — HELD-OUT TEST %d+ and FULL %d+, winning cell %s"
          % (name, TEST_FROM_YEAR, SCORE_FROM_YEAR, str(best)))
    print("=" * 78)
    out = {}
    for leg, sy, uy, yy in (("TEST", TEST_FROM_YEAR, None, yrs_te),
                            ("FULL", SCORE_FROM_YEAR, None, yrs_fu)):
        print("  --- %s leg" % leg)
        print("    %-8s %5s %6s %6s %7s %7s %8s %8s"
              % ("sym", "N", "PF", "WR%", "avgR", "sd(R)", "finR", "fills/wk"))
        res = []
        for sym in keep:
            r = runner(best, sym, keep[sym], sy, uy)
            if r is None:
                continue
            res.append(r)
            st = stats(r[0], r[2], yy)
            if st is None:
                print("    %-8s no trades" % sym)
                continue
            fin = np.mean([x["finR"] for x in r[2]]) if r[2] else 0.0
            print("    %-8s %5d %6.2f %6.1f %+7.3f %7.3f %+8.4f %8.2f"
                  % (sym, st["n"], st["pf"], st["wr"], st["avgR"], st["sdR"],
                     fin, st["per_wk"]))
        tr, rc = _pool(res)
        st = stats(tr, rc, yy)
        if st is None:
            print("    POOLED   no trades")
            continue
        out[leg] = (st, rc)
        print("    %-8s %5d %6.2f %6.1f %+7.3f %7.3f %8s %8.2f   CAGR %.1f%% DD %.1f%%"
              % ("POOLED", st["n"], st["pf"], st["wr"], st["avgR"], st["sdR"],
                 "", st["per_wk"], st["cagr"], st["dd"]))
        # GROSS: zero cost, no financing. The decisive robustness check — if the
        # gross edge is negative the verdict cannot be blamed on a cost
        # assumption (spread snapshot time, raw-vs-standard commission, etc).
        gres = [r for r in (runner(best, sym, keep[sym], sy, uy,
                                   cost_mode="zero", use_fin=False)
                            for sym in keep) if r is not None]
        gtr, grc = _pool(gres)
        gst = stats(gtr, grc, yy)
        if gst is not None:
            out[leg + "_GROSS"] = (gst, grc)
            print("    %-8s %5d %6.2f %6.1f %+7.3f %7.3f   <- zero cost, no fin"
                  % ("(gross)", gst["n"], gst["pf"], gst["wr"], gst["avgR"],
                     gst["sdR"]))
    print()
    return {"cell": best, "legs": out}


def verdict(name, r):
    if r is None or "FULL" not in r["legs"] or "TEST" not in r["legs"]:
        print("  %-18s NOT SCORED" % name)
        return
    full, _ = r["legs"]["FULL"]
    test, _ = r["legs"]["TEST"]
    checks = [
        ("FULL PF >= %.2f" % BAR_PF, full["pf"] >= BAR_PF, "%.2f" % full["pf"]),
        ("N >= %d" % BAR_MIN_N, full["n"] >= BAR_MIN_N, "%d" % full["n"]),
        ("FULL avgR > 0", full["avgR"] > 0, "%+.3f" % full["avgR"]),
        ("TEST avgR > 0", test["avgR"] > 0, "%+.3f" % test["avgR"]),
        ("TEST PF >= %.2f" % BAR_PF, test["pf"] >= BAR_PF, "%.2f" % test["pf"]),
        ("fills/wk >= %.1f" % BAR_FILLS_PER_WEEK,
         full["per_wk"] >= BAR_FILLS_PER_WEEK, "%.2f" % full["per_wk"]),
    ]
    ok = all(c[1] for c in checks)
    print("  %-18s %s   cell=%s" % (name, "PASS" if ok else "FAIL", r["cell"]))
    for label, good, val in checks:
        print("      %-22s %-8s %s" % (label, val, "ok" if good else "MISS"))
    if ok:
        sd = full["sdR"]
        need = 7.85 * sd * sd / (full["avgR"] ** 2)
        print("      power: sd(R) %.3f, avgR %+.3f -> N=%.0f for 80%%, "
              "%.1f yr at %.2f fills/wk"
              % (sd, full["avgR"], need, need / (full["per_wk"] * 52.0),
                 full["per_wk"]))


def concurrency(recs, label):
    """Surface the PORTFOLIO_GATE trap: the screened portfolio is only real if
    the bot could actually hold its legs (max_per_currency is 4)."""
    if not recs:
        return
    ev = []
    for r in recs:
        ev.append((r["in"], +1, r["sym"]))
        ev.append((r["out"] + timedelta(days=1), -1, r["sym"]))
    ev.sort(key=lambda x: x[0])
    cur, peak = 0, 0
    ccy_cur, ccy_peak = {}, {}
    for _d, delta, sym in ev:
        cur += delta
        peak = max(peak, cur)
        for c in (sym[:3], sym[3:]):
            ccy_cur[c] = ccy_cur.get(c, 0) + delta
            ccy_peak[c] = max(ccy_peak.get(c, 0), ccy_cur[c])
    top = sorted(ccy_peak.items(), key=lambda x: -x[1])[:4]
    print("  %s peak concurrent legs %d | peak per-currency %s"
          % (label, peak, ", ".join("%s %d" % (c, n) for c, n in top)))


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    sanity_gate()
    _f2_identity_check()

    print("=" * 78)
    print("LOADING (H1 -> H4, broker clock) + live specs")
    print("=" * 78)
    loaded, fins = {}, {}
    for sym in UNIVERSE:
        spec = build_spec(sym)
        if spec is None:
            print("  %-8s NOT SCORED — no tick specs / not offered" % sym)
            continue
        h1 = load_h1(sym)
        if h1 is None:
            print("  %-8s NOT SCORED — insufficient H1 history" % sym)
            continue
        start = min(h1["bdate"])
        if start.year > MIN_HISTORY_START_YEAR:
            print("  %-8s NOT SCORED — history starts %s (need <= %d)"
                  % (sym, start, MIN_HISTORY_START_YEAR))
            continue
        spec["floor"] = spec["live_spread"]
        h4 = build_h4(h1)
        f, rL, rS, note = swap_fn(sym, spec["dpp"], h1["close"].iloc[-1])
        if f is None:
            print("  %-8s NOT SCORED — %s" % (sym, note))
            continue
        fins[sym] = f
        print("  %-8s %s -> %s  H1 %d  H4 %d  dpp %.0f  swap L%+.2f%%/yr "
              "S%+.2f%%/yr  [%s]"
              % (sym, start, max(h1["bdate"]), len(h1), len(h4), spec["dpp"],
                 rL, rS, note))
        loaded[sym] = (h1, h4, spec)
    print()
    if not loaded:
        print("nothing loaded — aborting")
        sys.exit(1)

    keep = friction_table(loaded)
    if not keep:
        print("no instrument cleared the friction ceiling — aborting")
        sys.exit(1)

    # ------------------------------------------------------------------- F1
    def f1_runner(cell, sym, bundle, sy, uy, cost_mode="real", use_fin=True):
        entry_lb, exit_lb = cell
        _h1, h4, spec = bundle
        return simulate(spec, h4, "close", cost_mode, entry_lb, exit_lb,
                        F1_ATR_P, F1_ATR_MULT, since_year=sy, until_year=uy,
                        fin=fins[sym] if use_fin else None)

    r1 = run_family("F1 H4 DONCHIAN", F1_GRID, f1_runner, keep, today)

    # ------------------------------------------------------------------- F2
    usd = {s: b for s, b in keep.items() if USD_SIDE.get(s) is not None}
    print("F2 universe (USD leg required): %s\n"
          % (", ".join(usd) if usd else "(none)"))

    def f2_runner(cell, sym, bundle, sy, uy, cost_mode="real", use_fin=True):
        hour, hold, usd_dir = cell
        h1, _h4, spec = bundle
        # usd_dir is the USD-side direction; flip for USD-quoted pairs
        want = usd_dir * USD_SIDE[sym]
        d = "L" if want > 0 else "S"
        return simulate_drift(spec, h1, cost_mode, hour, hold, d,
                              since_year=sy, until_year=uy,
                              fin=fins[sym] if use_fin else None)

    f2_cells = [(h, k, s) for h in F2_HOURS for k in F2_HOLDS for s in (+1, -1)]
    r2 = (run_family("F2 USD SESSION DRIFT", f2_cells, f2_runner, usd, today)
          if usd else None)

    # -------------------------------------------------------------- verdicts
    print("=" * 78)
    print("VERDICTS — decision column: real cost (floored spread + commission)")
    print("           WITH overnight financing.  Bar pre-committed above.")
    print("=" * 78)
    verdict("F1 H4 Donchian", r1)
    verdict("F2 USD drift", r2)
    print()
    for nm, r in (("F1", r1), ("F2", r2)):
        if r and "FULL" in r["legs"]:
            concurrency(r["legs"]["FULL"][1], nm)
    print("\nNOTE: financing rates are TODAY's, applied across history. Policy")
    print("rates were ~0 pre-2022, so the %d+ test leg is the honest read and"
          % TEST_FROM_YEAR)
    print("the FULL column is optimistic on carry for its first six years.")


if __name__ == "__main__":
    main()
