"""NR7 tight-trail honest re-backtest on IC's own D1 history (VPS, read-only).

Replicates backtests/run_nr7_indices.py (NR7 signal, next-day-only bracket,
ATR(14)x1 initial stop, 10-day tight trail = highest low / lowest high,
1% compounding) and removes its remaining optimism:

  exits:    gap-aware (long stop exit at min(open, stop); orig used exact stop)
  whipsaw:  both-levels-hit days decided by open-proximity (first-touch
            heuristic, no lookahead; orig peeked at the day's close).
            Stress mode: worst-case (always the losing side).
  costs:    per-bar IC spread at the entry day (orig: flat 0.5/1.0 pts)
  trail:    TIGHT (the backtested variant that scored PF 5.46/5.74) and
            LOOSE (what the paused scanner shipped; sanity vs PF ~1.04)

Grid: {tight,loose} x {honest, worst-whipsaw} + orig-repro, full & 2023+.

Results 2026-07-02 (IC D1, 2012-08 -> 2026-07) — the RETIREMENT verdict:
                                    FULL              2023+
  US500 orig-repro (lookahead)   PF 1.77 +3.7%     PF 1.57
  US500 tight HONEST             PF 1.22 +1.5%     PF 0.83  <- negative
  US500 tight worst-whipsaw      PF 1.02           PF 0.67
  US500 loose (deployed)         PF 0.98           PF 0.91
  DE40  orig-repro (lookahead)   PF 1.74 +4.0%     PF 1.62
  DE40  tight HONEST             PF 1.12 +0.9%     PF 0.91  <- negative
  DE40  tight worst-whipsaw      PF 0.97           PF 0.75
  DE40  loose (deployed)         PF 0.84           PF 0.89

The claimed PF 5.46/5.74 was stacked optimism (exact fills through gaps on
both entry and exit, close-peeking whipsaw resolution, flat costs, cleaner
CSV data than IC's server history). No variant survives honest treatment;
both indices are sub-breakeven since 2023. NR7_BREAKOUT retired for good.

Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/nr7_honest_bt.py
"""
import os
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

START_EQ, RISK_PCT, DPP = 10000.0, 1.0, 1.0
NR_LB, ATR_P, TRAIL_LB = 7, 14, 10

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


def load_d1(sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 99000)
    df = pd.DataFrame(rates)
    df["t"] = pd.to_datetime(df["time"], unit="s")
    point = mt5.symbol_info(sym).point
    df["spread_pts"] = df["spread"] * point
    df = df.iloc[:-1]  # drop forming bar
    df = df[df["t"].dt.weekday < 5].reset_index(drop=True)
    return df


def simulate(df, trail_mode, whipsaw, cost_mode, flat_cost, since_year=None):
    d = df.copy()
    d["rng"] = d["high"] - d["low"]
    h, l, c = d["high"], d["low"], d["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / ATR_P, adjust=False).mean().shift(1)
    d["nr7"] = d["rng"] == d["rng"].rolling(NR_LB).min()
    rows = d.to_dict("records")
    trades = []
    equity = START_EQ
    ot = None  # open trade dict
    for i in range(NR_LB, len(rows) - 1):
        row, nxt = rows[i], rows[i + 1]
        if since_year and row["t"].year < since_year:
            continue

        if ot is not None:
            if ot["dir"] == "L":
                if row["low"] <= ot["stop"]:
                    xp = min(row["open"], ot["stop"])  # gap-aware exit
                    pnl_pts = (xp - ot["ep"]) - ot["cost"]
                else:
                    trail = max(r["low"] for r in rows[max(0, i - TRAIL_LB):i]) \
                        if trail_mode == "tight" else \
                        min(r["low"] for r in rows[max(0, i - TRAIL_LB):i])
                    ot["stop"] = max(ot["stop"], trail)
                    pnl_pts = None
            else:
                if row["high"] >= ot["stop"]:
                    xp = max(row["open"], ot["stop"])
                    pnl_pts = (ot["ep"] - xp) - ot["cost"]
                else:
                    trail = min(r["high"] for r in rows[max(0, i - TRAIL_LB):i]) \
                        if trail_mode == "tight" else \
                        max(r["high"] for r in rows[max(0, i - TRAIL_LB):i])
                    ot["stop"] = min(ot["stop"], trail)
                    pnl_pts = None
            if pnl_pts is not None:
                risk = equity * RISK_PCT / 100.0
                lots = max(min(round(risk / max(ot["isd"] * DPP, 0.01), 2), 100.0), 0.01)
                usd = pnl_pts * lots * DPP
                equity += usd
                trades.append(usd)
                ot = None

        if ot is None and row["nr7"] and not pd.isna(row["atr"]):
            buy_lvl, sell_lvl, atr = row["high"], row["low"], row["atr"]
            n_open = nxt["open"]
            cost = nxt["spread_pts"] if cost_mode == "spread" else flat_cost
            long_fill = max(buy_lvl, n_open)
            short_fill = min(sell_lvl, n_open)
            hit_l = nxt["high"] >= buy_lvl
            hit_s = nxt["low"] <= sell_lvl
            direction = None
            if hit_l and hit_s:
                if whipsaw == "orig":       # lookahead: day's winner
                    direction = "L" if nxt["close"] > nxt["open"] else "S"
                elif whipsaw == "open":     # first-touch heuristic
                    direction = "L" if abs(n_open - buy_lvl) <= abs(n_open - sell_lvl) else "S"
                else:                        # worst-case: the losing side
                    direction = "S" if nxt["close"] > nxt["open"] else "L"
            elif hit_l:
                direction = "L"
            elif hit_s:
                direction = "S"
            if direction == "L":
                ot = {"dir": "L", "ep": long_fill, "stop": buy_lvl - atr,
                      "isd": abs(long_fill - (buy_lvl - atr)), "cost": cost}
            elif direction == "S":
                ot = {"dir": "S", "ep": short_fill, "stop": sell_lvl + atr,
                      "isd": abs((sell_lvl + atr) - short_fill), "cost": cost}
    return np.array(trades), equity


def report(label, trades, final_eq, years):
    if len(trades) == 0:
        print(f"  {label}: no trades")
        return
    w = (trades > 0).sum()
    gp = trades[trades > 0].sum()
    gl = abs(trades[trades <= 0].sum()) or 0.001
    eq = np.concatenate([[START_EQ], START_EQ + np.cumsum(trades)])
    dd = np.maximum.accumulate(eq) - eq
    ddpct = dd.max() / np.maximum.accumulate(eq)[dd.argmax()] * 100 if dd.max() > 0 else 0
    cagr = ((final_eq / START_EQ) ** (1 / years) - 1) * 100 if years > 0 else 0
    print(f"  {label:<34} N={len(trades):>3} WR={w/len(trades)*100:>3.0f}% "
          f"PF={gp/gl:>5.2f} CAGR={cagr:>+6.1f}% maxDD={ddpct:>4.1f}%")


FLAT = {"US500": 0.5, "DE40": 1.0}
GRID = [
    ("orig-repro (tight, lookahead, flat)", "tight", "orig", "flat"),
    ("tight HONEST (open-touch, IC sprd)",  "tight", "open", "spread"),
    ("tight worst-whipsaw (IC sprd)",       "tight", "worst", "spread"),
    ("loose (deployed) honest",             "loose", "open", "spread"),
]

for sym in ("US500", "DE40"):
    df = load_d1(sym)
    med_sp = df["spread_pts"].median()
    yrs = (df["t"].iloc[-1] - df["t"].iloc[0]).days / 365.25
    print(f"\n# {sym}: {len(df)} D1 bars ({df['t'].iloc[0].date()} -> "
          f"{df['t'].iloc[-1].date()}), median spread {med_sp:.2f} pts")
    for label, tm, ws, cm in GRID:
        tr, eq = simulate(df, tm, ws, cm, FLAT[sym])
        report(label, tr, eq, yrs)
    print("  --- 2023+ ---")
    yrs23 = (df["t"].iloc[-1] - pd.Timestamp("2023-01-01")).days / 365.25
    for label, tm, ws, cm in GRID:
        tr, eq = simulate(df, tm, ws, cm, FLAT[sym], since_year=2023)
        report(label, tr, eq, yrs23)
mt5.shutdown()
