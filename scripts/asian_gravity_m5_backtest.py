"""
Asian Gravity Strategy — M5 Backtest via yfinance data

Downloads ~60 days of M5 data and runs a proper bar-by-bar backtest.
Runs locally on Mac (no MT5 needed).

Usage:
    python3 scripts/asian_gravity_m5_backtest.py
"""

import os
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

# ---- Config ----

PAIRS = {
    "EURGBP": {"ticker": "EURGBP=X", "pip": 0.0001},
    "EURUSD": {"ticker": "EURUSD=X", "pip": 0.0001},
}

SESSION_START = 0   # 00:00 UTC
FORMATION_END = 2   # 02:00 UTC
SESSION_END = 6     # 06:00 UTC

PARAM_GRID = [
    # (trigger, target, stop, max_trades_per_session)
    (3, 2, 3, 6),
    (3, 2, 4, 6),
    (3, 2, 5, 6),
    (3, 3, 3, 6),
    (3, 3, 4, 6),
    (3, 3, 5, 6),
    (3, 4, 3, 6),
    (3, 4, 4, 6),
    (3, 4, 5, 6),
    (3, 5, 3, 6),
    (3, 5, 4, 6),
    (3, 5, 5, 6),
    (3, 5, 6, 4),
    (3, 5, 8, 4),
    (4, 3, 3, 6),
    (4, 3, 4, 6),
    (4, 3, 5, 6),
    (4, 4, 3, 6),
    (4, 4, 4, 6),
    (4, 5, 3, 6),
    (4, 5, 4, 6),
    (4, 5, 5, 4),
    (5, 3, 3, 6),
    (5, 3, 4, 6),
    (5, 3, 5, 6),
    (5, 4, 3, 6),
    (5, 4, 4, 4),
    (5, 5, 3, 4),
    (5, 5, 5, 4),
    (5, 5, 8, 4),
    (7, 3, 3, 4),
    (7, 3, 5, 4),
    (7, 5, 3, 4),
    (7, 5, 5, 4),
    (7, 5, 8, 4),
    (7, 7, 5, 3),
    (10, 5, 5, 3),
    (10, 7, 5, 3),
    (10, 7, 8, 3),
    (10, 10, 5, 3),
    (10, 10, 8, 3),
]

# Spread assumptions (pips) - conservative for Asian session
SPREADS = {"EURGBP": 1.0, "EURUSD": 0.5}


@dataclass
class Trade:
    bar_idx: int
    direction: str
    entry_price: float
    tp_price: float
    sl_price: float
    session_date: object
    exit_bar: int = 0
    exit_price: float = 0.0
    pnl_pips: float = 0.0
    exit_reason: str = ""


# ---- Data ----

def download_m5(ticker: str) -> pd.DataFrame:
    """Download M5 data from yfinance."""
    t = yf.Ticker(ticker)
    df = t.history(period="60d", interval="5m")
    if df.empty:
        return df
    # Convert to UTC
    df.index = df.index.tz_convert("UTC")
    df.columns = [c.lower() for c in df.columns]
    return df


# ---- Backtest ----

def run_backtest(df: pd.DataFrame, pair: str, trigger: float, target: float,
                 stop: float, max_trades: int) -> list[Trade]:
    """Bar-by-bar M5 backtest."""
    pip = PAIRS[pair]["pip"]
    spread = SPREADS[pair]
    spread_price = spread * pip

    trades = []
    session_date = None
    session_open = 0.0
    form_high = 0.0
    form_low = 0.0
    in_formation = False
    open_trade = None
    session_trades = 0
    cooldown_until = -1

    for i in range(len(df)):
        bar = df.iloc[i]
        ts = df.index[i]
        hour = ts.hour
        minute = ts.minute
        bar_date = ts.date()

        # Skip weekends
        if ts.weekday() >= 5:
            continue

        # New session start
        if hour == SESSION_START and minute == 0 and bar_date != session_date:
            # Force close open trade from previous session
            if open_trade:
                _close(open_trade, bar, pip, spread, "TIME_EXIT")
                trades.append(open_trade)
                open_trade = None

            session_date = bar_date
            session_open = bar["open"]
            form_high = bar["high"]
            form_low = bar["low"]
            in_formation = True
            session_trades = 0
            cooldown_until = -1
            continue

        # Outside session
        if hour >= SESSION_END or session_date != bar_date:
            if open_trade:
                _close(open_trade, bar, pip, spread, "TIME_EXIT")
                trades.append(open_trade)
                open_trade = None
            continue

        # Formation phase
        if in_formation and hour < FORMATION_END:
            form_high = max(form_high, bar["high"])
            form_low = min(form_low, bar["low"])
            continue

        # Transition
        if in_formation and hour >= FORMATION_END:
            in_formation = False
            range_pips = (form_high - form_low) / pip
            if range_pips < 3 or range_pips > 60:
                session_date = None  # skip
                continue

        if session_date is None:
            continue

        # ---- Manage open trade ----
        if open_trade:
            if open_trade.direction == "LONG":
                # SL check: use bar low (conservative: assume SL hit before TP if both in range)
                if bar["low"] <= open_trade.sl_price:
                    open_trade.exit_price = open_trade.sl_price
                    open_trade.pnl_pips = (open_trade.sl_price - open_trade.entry_price) / pip - spread
                    open_trade.exit_reason = "SL"
                    open_trade.exit_bar = i
                    trades.append(open_trade)
                    open_trade = None
                    cooldown_until = i + 1  # skip 1 bar
                    continue
                elif bar["high"] >= open_trade.tp_price:
                    open_trade.exit_price = open_trade.tp_price
                    open_trade.pnl_pips = (open_trade.tp_price - open_trade.entry_price) / pip - spread
                    open_trade.exit_reason = "TP"
                    open_trade.exit_bar = i
                    trades.append(open_trade)
                    open_trade = None
                    cooldown_until = i + 1
                    continue
            else:  # SHORT
                if bar["high"] >= open_trade.sl_price:
                    open_trade.exit_price = open_trade.sl_price
                    open_trade.pnl_pips = (open_trade.entry_price - open_trade.sl_price) / pip - spread
                    open_trade.exit_reason = "SL"
                    open_trade.exit_bar = i
                    trades.append(open_trade)
                    open_trade = None
                    cooldown_until = i + 1
                    continue
                elif bar["low"] <= open_trade.tp_price:
                    open_trade.exit_price = open_trade.tp_price
                    open_trade.pnl_pips = (open_trade.entry_price - open_trade.tp_price) / pip - spread
                    open_trade.exit_reason = "TP"
                    open_trade.exit_bar = i
                    trades.append(open_trade)
                    open_trade = None
                    cooldown_until = i + 1
                    continue
            continue  # trade still open

        # ---- New entry logic ----
        if session_trades >= max_trades:
            continue
        if i <= cooldown_until:
            continue

        trigger_up = session_open + trigger * pip
        trigger_down = session_open - trigger * pip

        # SHORT: price drifted up
        if bar["high"] >= trigger_up:
            entry = trigger_up + spread_price  # worse fill (ask)
            tp = entry - target * pip
            sl = entry + stop * pip
            open_trade = Trade(i, "SHORT", entry, tp, sl, session_date)
            session_trades += 1

        # LONG: price drifted down
        elif bar["low"] <= trigger_down:
            entry = trigger_down - spread_price  # worse fill (bid)
            tp = entry + target * pip
            sl = entry - stop * pip
            open_trade = Trade(i, "LONG", entry, tp, sl, session_date)
            session_trades += 1

    if open_trade:
        _close(open_trade, df.iloc[-1], pip, spread, "END")
        trades.append(open_trade)

    return trades


def _close(trade: Trade, bar, pip: float, spread: float, reason: str):
    trade.exit_price = bar["close"]
    if trade.direction == "LONG":
        trade.pnl_pips = (bar["close"] - trade.entry_price) / pip - spread
    else:
        trade.pnl_pips = (trade.entry_price - bar["close"]) / pip - spread
    trade.exit_reason = reason


def metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    pnls = [t.pnl_pips for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 0.001

    eq = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    consec = 0
    max_consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    tp_n = sum(1 for t in trades if t.exit_reason == "TP")
    sl_n = sum(1 for t in trades if t.exit_reason == "SL")

    # Per-week breakdown
    weekly = {}
    for t in trades:
        wk = t.session_date.isocalendar()[1] if hasattr(t.session_date, 'isocalendar') else 0
        yr = t.session_date.year if hasattr(t.session_date, 'year') else 0
        key = f"{yr}-W{wk:02d}"
        if key not in weekly:
            weekly[key] = 0
        weekly[key] += t.pnl_pips
    pos_weeks = sum(1 for v in weekly.values() if v > 0)

    return {
        "n": len(trades), "wr": len(wins)/len(trades)*100, "pf": gp/gl,
        "exp": np.mean(pnls), "total": sum(pnls), "max_dd": max_dd,
        "aw": np.mean(wins) if wins else 0, "al": np.mean(losses) if losses else 0,
        "consec": max_consec, "tp": tp_n/len(trades)*100, "sl": sl_n/len(trades)*100,
        "pos_weeks": pos_weeks, "total_weeks": len(weekly),
    }


# ---- Main ----

def main():
    for pair, cfg in PAIRS.items():
        print(f"\n{'='*80}")
        print(f"  {pair} -- Asian Gravity M5 Backtest")
        print(f"  Spread assumption: {SPREADS[pair]} pips")
        print(f"{'='*80}")

        print(f"  Downloading M5 data...")
        df = download_m5(cfg["ticker"])
        if df.empty:
            print("  No data")
            continue

        sessions = df[(df.index.hour >= SESSION_START) & (df.index.hour < SESSION_END)]
        n_sessions = sessions.index.date
        n_unique = len(set(n_sessions))
        print(f"  {len(df)} bars, {df.index[0].date()} to {df.index[-1].date()}")
        print(f"  ~{n_unique} Asian sessions")

        # Parameter sweep
        print(f"\n  {'Trig':>5} {'Tgt':>4} {'SL':>4} {'Max':>4} {'Trades':>7} "
              f"{'WR':>5} {'PF':>6} {'Exp':>7} {'Total':>7} {'MaxDD':>6} "
              f"{'ConsL':>6} {'TP%':>5} {'SL%':>5} {'Wk+':>4}")

        results = []
        for trigger, target, stop, max_t in PARAM_GRID:
            trades = run_backtest(df, pair, trigger, target, stop, max_t)
            m = metrics(trades)
            if m["n"] == 0:
                continue
            results.append((trigger, target, stop, max_t, m))

        results.sort(key=lambda x: x[4]["total"], reverse=True)

        for trig, tgt, sl, max_t, m in results[:25]:
            flag = " *" if m["pf"] > 1.0 else ""
            print(f"  {trig:>4}p {tgt:>3}p {sl:>3}p {max_t:>4} {m['n']:>7} "
                  f"{m['wr']:>4.0f}% {m['pf']:>6.2f} {m['exp']:>+6.2f}p "
                  f"{m['total']:>+6.0f}p {m['max_dd']:>5.0f}p "
                  f"{m['consec']:>5} {m['tp']:>4.0f}% {m['sl']:>4.0f}% "
                  f"{m['pos_weeks']:>2}/{m['total_weeks']}{flag}")

        # Deep dive on profitable combos
        profitable = [(t, tg, s, mx, m) for t, tg, s, mx, m in results if m["pf"] > 1.0]
        if profitable:
            print(f"\n  === {len(profitable)} PROFITABLE COMBINATIONS ===")
            for trig, tgt, sl, max_t, m in profitable[:5]:
                print(f"\n  trigger={trig}p target={tgt}p stop={sl}p max={max_t}")
                print(f"    Trades: {m['n']} | WR: {m['wr']:.0f}% | PF: {m['pf']:.2f} | "
                      f"Exp: {m['exp']:+.2f}p")
                print(f"    Total: {m['total']:+.0f}p | MaxDD: {m['max_dd']:.0f}p | "
                      f"ConsecL: {m['consec']}")
                print(f"    AvgWin: {m['aw']:.1f}p | AvgLoss: {m['al']:.1f}p")
                print(f"    Positive weeks: {m['pos_weeks']}/{m['total_weeks']}")

                # Sizing
                print(f"    Sizing ($10k, {sl}p stop):")
                pip_usd = 10.0 if pair == "EURUSD" else 12.7
                for risk in [1.0, 2.0, 3.0, 5.0]:
                    lots = (10000 * risk / 100) / (sl * pip_usd)
                    pnl = m["total"] * lots * pip_usd
                    dd = m["max_dd"] * lots * pip_usd
                    # Annualize: data is ~60 days, so multiply by 365/60
                    ann_factor = 365 / 60
                    print(f"      {risk}% -> {lots:.2f} lots | "
                          f"60d P&L: ${pnl:+,.0f} | "
                          f"Ann. ~${pnl*ann_factor:+,.0f} ({pnl*ann_factor/10000*100:+.0f}%) | "
                          f"MaxDD: ${dd:,.0f} ({dd/10000*100:.1f}%)")
        else:
            print(f"\n  No profitable combinations found.")

    print(f"\n{'='*80}")
    print("Done.")


if __name__ == "__main__":
    main()
