"""BTC_DONCHIAN honest re-backtest on IC's own H1 history (VPS, read-only).

Replicates backtests/run_crypto_donchian.py (Donchian 55/20, ATR(20)x1.0
initial stop, trail to 20-day opposite extreme, 1% compounding from $10k,
entry on D1 close breakout, gap-aware stop exits) and adds two honesty axes:

  cost:  flat   = original assumption ($12 BTC / $5 ETH round trip)
         spread = IC's actual per-bar spread at the entry bar (price units)
  entry: close  = original (fill at signal-day D1 close = broker midnight)
         lag    = live reality (market order at ~00:01 real UTC, 2-3h after
                  the broker D1 close) -> fill at that H1 bar's open

Modes: orig(close+flat), spread(close+spread), lag(lag+flat),
       HONEST(lag+spread). Full history and 2023+.

Results 2026-07-02 (2023+ rows are the decision-grade ones — pre-2017 IC
history is MetaQuotes backfill and distorts full-period stats):
  BTCUSD 2023+: orig PF 2.59 CAGR +8.1% | HONEST PF 1.76 CAGR +5.1% dd 11%
  ETHUSD 2023+: orig PF 4.75 CAGR +9.8% | HONEST PF 3.92 CAGR +8.9% dd  7%
Findings: (1) the flat $12/$5 cost assumption was ~10x too pessimistic —
real IC spread at the 00:00-UTC entry hour is ~$0.7 BTC / $2.9 ETH; (2) the
dominant unmodeled cost is the ENTRY LAG — live decides at 00:01 UTC, 2-3h
after the broker D1 close, and that alone costs a third to half the edge.
Recovery option (not implemented): gate the scanners' daily processing at
the broker-day rollover (21:00/22:00 UTC) instead of 00:01 UTC, which would
move live toward the 'orig' rows. Re-run this script before changing.

Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/btc_donchian_honest_bt.py
"""
import os
import time as _time
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

ENTRY_LB, EXIT_LB, ATR_P, ATR_MULT = 55, 20, 20, 1.0
START_EQ, RISK_PCT = 10000.0, 1.0
FLAT_COST = {"BTCUSD": 12.0, "ETHUSD": 5.0}
DPP = 1.0  # $ per point per lot (both, IC contract size 1)

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
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000)
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")           # broker clock
    off = df["tb"].apply(lambda t: eu_dst_offset(
        (t - pd.Timedelta(hours=3)).tz_localize("UTC")))
    df["tu"] = df["tb"] - pd.to_timedelta(off, unit="h")       # true UTC
    point = mt5.symbol_info(sym).point
    df["spread_price"] = df["spread"] * point
    df = df.iloc[:-1]
    # broker-day D1 (matches live scanner + original CSV resample)
    df["bdate"] = df["tb"].dt.date
    d1 = df.groupby("bdate").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last")).reset_index()
    # per broker-day: the live entry bar = first bar of the NEXT broker day
    # with true-UTC hour == 0 (live scans at 00:01 UTC)
    utc0 = df[df["tu"].dt.hour == 0].groupby("bdate").agg(
        lag_open=("open", "first"), lag_spread=("spread_price", "first"))
    d1 = d1.merge(utc0, on="bdate", how="left")
    # signal-day close spread (for spread-cost at close-entry variants)
    close_sp = df.groupby("bdate").agg(close_spread=("spread_price", "last"))
    d1 = d1.merge(close_sp, on="bdate", how="left")
    return d1


def atr(d1):
    h, l, c = d1["high"], d1["low"], d1["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_P, adjust=False).mean()


def simulate(sym, d1, entry_mode, cost_mode, since_year=None):
    df = d1.copy()
    df["entry_high"] = df["high"].rolling(ENTRY_LB).max().shift(1)
    df["entry_low"] = df["low"].rolling(ENTRY_LB).min().shift(1)
    df["exit_high"] = df["high"].rolling(EXIT_LB).max().shift(1)
    df["exit_low"] = df["low"].rolling(EXIT_LB).min().shift(1)
    df["atr"] = atr(df).shift(1)
    rows = df.to_dict("records")
    trades = []
    equity = START_EQ
    open_t = None
    pending_entry = None  # (direction, atr) queued for next row's lag fill
    for i, row in enumerate(rows):
        if since_year and row["bdate"].year < since_year:
            continue
        if pd.isna(row["entry_high"]) or pd.isna(row["atr"]):
            continue

        # Fill a lag entry at this row's 00:00-UTC bar open
        if pending_entry is not None and open_t is None:
            direction, sig_atr = pending_entry
            ep = row.get("lag_open")
            sp = row.get("lag_spread")
            if ep is None or pd.isna(ep):
                pending_entry = None  # no 00:00 bar (rare) — skip signal
            else:
                cost = (sp if cost_mode == "spread" and not pd.isna(sp)
                        else FLAT_COST[sym])
                stop = ep - ATR_MULT * sig_atr if direction == "L" else ep + ATR_MULT * sig_atr
                open_t = {"dir": direction, "ep": ep, "stop": stop,
                          "isd": abs(ep - stop), "cost": cost}
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
                lots = risk_usd / max(open_t["isd"] * DPP, 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                usd = pnl_pts * lots * DPP
                equity += usd
                trades.append(usd)
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
                    cost = (sp if cost_mode == "spread" and not pd.isna(sp)
                            else FLAT_COST[sym])
                    stop = ep - ATR_MULT * row["atr"] if direction == "L" else ep + ATR_MULT * row["atr"]
                    open_t = {"dir": direction, "ep": ep, "stop": stop,
                              "isd": abs(ep - stop), "cost": cost}
    return np.array(trades), equity


def report(sym, trades, final_eq, years, label):
    if len(trades) == 0:
        print(f"{sym} {label}: no trades")
        return
    w = (trades > 0).sum()
    gp = trades[trades > 0].sum()
    gl = abs(trades[trades <= 0].sum()) or 0.001
    eq = np.concatenate([[START_EQ], START_EQ + np.cumsum(trades)])
    dd = (np.maximum.accumulate(eq) - eq)
    ddpct = dd.max() / np.maximum.accumulate(eq)[dd.argmax()] * 100 if dd.max() > 0 else 0
    cagr = ((final_eq / START_EQ) ** (1 / years) - 1) * 100 if years > 0 else 0
    print(f"{sym} {label:<22} N={len(trades):>3} WR={w/len(trades)*100:>3.0f}% "
          f"PF={gp/gl:>5.2f} CAGR={cagr:>+6.1f}% maxDD={ddpct:>4.1f}%")


MODES = [("orig (close+flat)", "close", "flat"),
         ("close+IC spread", "close", "spread"),
         ("lag entry+flat", "lag", "flat"),
         ("HONEST (lag+spread)", "lag", "spread")]

for sym in ("BTCUSD", "ETHUSD"):
    d1 = load(sym)
    yrs_full = (pd.Timestamp(d1["bdate"].iloc[-1]) - pd.Timestamp(d1["bdate"].iloc[0])).days / 365.25
    med_sp = d1["lag_spread"].median()
    print(f"\n# {sym}: {len(d1)} D1 bars ({d1['bdate'].iloc[0]} -> {d1['bdate'].iloc[-1]}), "
          f"median entry-bar spread ${med_sp:.1f}")
    for label, em, cm in MODES:
        tr, eq = simulate(sym, d1, em, cm)
        report(sym, tr, eq, yrs_full, label)
    print(f"  --- 2023+ ---")
    yrs_23 = (pd.Timestamp(d1["bdate"].iloc[-1]) - pd.Timestamp("2023-01-01")).days / 365.25
    for label, em, cm in MODES:
        tr, eq = simulate(sym, d1, em, cm, since_year=2023)
        report(sym, tr, eq, yrs_23, label)
mt5.shutdown()
