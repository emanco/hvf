"""
Asian Gravity Strategy — Proper M15 Backtest Engine

Bar-by-bar simulation with session state machine, conservative fills,
walk-forward validation, and full performance reporting.

Usage:
    python scripts/asian_gravity_backtest.py
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# ---- Config ----

PAIRS = ["EURGBP", "EURUSD"]
TIMEFRAME = mt5.TIMEFRAME_M15
LOOKBACK_DAYS = 365

PIP_VALUES = {"EURUSD": 0.0001, "EURGBP": 0.0001}

# Session windows (UTC hours)
SESSION_START = 0
FORMATION_END = 2      # range forms 00:00-02:00
TRADING_END = 6        # last new entry at 06:00
FORCED_EXIT = 6        # force close at 06:00 (first bar of hour 6)

# Strategy parameters to sweep
PARAM_GRID = [
    # trigger, target, stop, max_trades_per_session
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
    (5, 3, 5, 6),
    (5, 5, 3, 4),
    (5, 5, 5, 4),
    (5, 5, 8, 4),
    (7, 5, 5, 4),
    (7, 5, 8, 4),
    (7, 7, 5, 3),
    (10, 5, 5, 3),
    (10, 7, 5, 3),
    (10, 7, 8, 3),
]


@dataclass
class Trade:
    entry_bar: int
    direction: str       # LONG or SHORT
    entry_price: float
    tp_price: float
    sl_price: float
    spread_pips: float
    session_date: object
    exit_bar: int = 0
    exit_price: float = 0.0
    pnl_pips: float = 0.0
    exit_reason: str = ""


@dataclass
class SessionState:
    date: object = None
    session_open: float = 0.0
    formation_high: float = 0.0
    formation_low: float = 0.0
    range_pips: float = 0.0
    in_formation: bool = True
    trades: list = field(default_factory=list)
    open_trade: object = None
    trade_count: int = 0


# ---- MT5 ----

def init_mt5():
    if not mt5.initialize():
        sys.exit(1)
    login = int(os.getenv("MT5_LOGIN", "0"))
    mt5.login(login, os.getenv("MT5_PASSWORD", ""), os.getenv("MT5_SERVER", ""))
    print(f"Connected: account {login}")


def fetch_data(symbol, days):
    now = datetime.now(timezone.utc)
    rates = mt5.copy_rates_range(symbol, TIMEFRAME, now - timedelta(days=days), now)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


# ---- Backtest Engine ----

def run_backtest(df: pd.DataFrame, symbol: str, trigger_pips: float,
                 target_pips: float, stop_pips: float,
                 max_trades: int = 4) -> list[Trade]:
    """Run bar-by-bar backtest of the gravity strategy."""

    pip_val = PIP_VALUES[symbol]
    all_trades = []
    state = SessionState()
    cooldown_until_bar = -1

    for bar_idx in range(len(df)):
        bar = df.iloc[bar_idx]
        ts = df.index[bar_idx]
        hour = ts.hour
        bar_date = ts.date()

        # ---- New session detection ----
        if state.date != bar_date and SESSION_START <= hour < FORCED_EXIT:
            # Force close any open trade from yesterday (shouldn't happen but safety)
            if state.open_trade:
                _close_trade(state, bar, pip_val, "TIME_NEW_SESSION")
                all_trades.append(state.open_trade)

            state = SessionState()
            state.date = bar_date
            state.session_open = bar["open"]
            state.formation_high = bar["high"]
            state.formation_low = bar["low"]
            state.in_formation = True
            cooldown_until_bar = -1
            continue

        # Skip bars outside Asian session
        if hour >= FORCED_EXIT or state.date != bar_date:
            # Force close at session end
            if state.open_trade and hour >= FORCED_EXIT:
                _close_trade(state, bar, pip_val, "TIME_EXIT")
                all_trades.append(state.open_trade)
                state.open_trade = None
            continue

        # ---- Formation phase (00:00-02:00) ----
        if state.in_formation and hour < FORMATION_END:
            state.formation_high = max(state.formation_high, bar["high"])
            state.formation_low = min(state.formation_low, bar["low"])
            continue

        # Transition to trading phase
        if state.in_formation and hour >= FORMATION_END:
            state.in_formation = False
            state.range_pips = (state.formation_high - state.formation_low) / pip_val
            # Skip if range is too small or too large
            if state.range_pips < 5 or state.range_pips > 50:
                state.date = None  # mark session as skipped
                continue

        # ---- Trading phase (02:00-06:00) ----

        # Get spread from bar data
        spread_pips = bar["spread"] / 10.0 if "spread" in df.columns else 0.8

        # Manage open trade
        if state.open_trade:
            trade = state.open_trade
            if trade.direction == "LONG":
                # Check SL (bar low breaches SL)
                if bar["low"] <= trade.sl_price:
                    trade.exit_price = trade.sl_price
                    trade.pnl_pips = (trade.sl_price - trade.entry_price) / pip_val - spread_pips
                    trade.exit_reason = "SL"
                    trade.exit_bar = bar_idx
                    all_trades.append(trade)
                    state.open_trade = None
                    cooldown_until_bar = bar_idx + 1
                    continue
                # Check TP (bar high reaches TP)
                elif bar["high"] >= trade.tp_price:
                    trade.exit_price = trade.tp_price
                    trade.pnl_pips = (trade.tp_price - trade.entry_price) / pip_val - spread_pips
                    trade.exit_reason = "TP"
                    trade.exit_bar = bar_idx
                    all_trades.append(trade)
                    state.open_trade = None
                    cooldown_until_bar = bar_idx + 1
                    continue
            else:  # SHORT
                if bar["high"] >= trade.sl_price:
                    trade.exit_price = trade.sl_price
                    trade.pnl_pips = (trade.entry_price - trade.sl_price) / pip_val - spread_pips
                    trade.exit_reason = "SL"
                    trade.exit_bar = bar_idx
                    all_trades.append(trade)
                    state.open_trade = None
                    cooldown_until_bar = bar_idx + 1
                    continue
                elif bar["low"] <= trade.tp_price:
                    trade.exit_price = trade.tp_price
                    trade.pnl_pips = (trade.entry_price - trade.tp_price) / pip_val - spread_pips
                    trade.exit_reason = "TP"
                    trade.exit_bar = bar_idx
                    all_trades.append(trade)
                    state.open_trade = None
                    cooldown_until_bar = bar_idx + 1
                    continue
            continue  # trade still open, don't look for new entries

        # No open trade - check for new entries
        if state.trade_count >= max_trades:
            continue
        if bar_idx <= cooldown_until_bar:
            continue

        session_open = state.session_open
        trigger_price_up = session_open + trigger_pips * pip_val
        trigger_price_down = session_open - trigger_pips * pip_val

        # SHORT entry: price drifted up past trigger
        if bar["high"] >= trigger_price_up:
            entry_price = trigger_price_up  # conservative: assume fill at trigger
            tp_price = session_open + target_pips * pip_val  # return toward open
            # Wait -- target should be CLOSER to open than entry
            # If trigger=3 and target=5, we enter at +3 and TP at... this needs rethinking
            # The "target" means: we want price to come back to within target_pips of open
            # So if we're SHORT from +3, TP is at +target (but target < trigger usually)
            # Actually: we SHORT at trigger_pips above open, target is closer to open
            # TP should be at: open + (trigger - target) * pip... no.
            # Simple: we SHORT at open + trigger. TP = open (return to open). Net = trigger pips.
            # Or: TP = open + residual. Let's keep it simple:
            # TP = session_open + (trigger_pips - target_pips) * pip_val... that's weird.
            # Let me reconsider: target_pips is how many pips of PROFIT we want.
            tp_price = entry_price - target_pips * pip_val
            sl_price = entry_price + stop_pips * pip_val

            state.open_trade = Trade(
                entry_bar=bar_idx, direction="SHORT",
                entry_price=entry_price, tp_price=tp_price, sl_price=sl_price,
                spread_pips=spread_pips, session_date=state.date,
            )
            state.trade_count += 1

        # LONG entry: price drifted down past trigger
        elif bar["low"] <= trigger_price_down:
            entry_price = trigger_price_down
            tp_price = entry_price + target_pips * pip_val
            sl_price = entry_price - stop_pips * pip_val

            state.open_trade = Trade(
                entry_bar=bar_idx, direction="LONG",
                entry_price=entry_price, tp_price=tp_price, sl_price=sl_price,
                spread_pips=spread_pips, session_date=state.date,
            )
            state.trade_count += 1

    # Close any remaining open trade
    if state.open_trade:
        _close_trade(state, df.iloc[-1], pip_val, "END")
        all_trades.append(state.open_trade)

    return all_trades


def _close_trade(state: SessionState, bar, pip_val: float, reason: str):
    trade = state.open_trade
    trade.exit_price = bar["close"]
    if trade.direction == "LONG":
        trade.pnl_pips = (bar["close"] - trade.entry_price) / pip_val - trade.spread_pips
    else:
        trade.pnl_pips = (trade.entry_price - bar["close"]) / pip_val - trade.spread_pips
    trade.exit_reason = reason


# ---- Performance Metrics ----

def compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}

    pnls = [t.pnl_pips for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001

    # Equity curve and drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Consecutive losses
    max_consec_loss = 0
    current_streak = 0
    for p in pnls:
        if p <= 0:
            current_streak += 1
            max_consec_loss = max(max_consec_loss, current_streak)
        else:
            current_streak = 0

    # Monthly breakdown
    monthly = {}
    for t in trades:
        month_key = t.session_date.strftime("%Y-%m") if hasattr(t.session_date, 'strftime') else str(t.session_date)[:7]
        if month_key not in monthly:
            monthly[month_key] = {"pnl": 0, "n": 0, "wins": 0}
        monthly[month_key]["pnl"] += t.pnl_pips
        monthly[month_key]["n"] += 1
        if t.pnl_pips > 0:
            monthly[month_key]["wins"] += 1

    positive_months = sum(1 for m in monthly.values() if m["pnl"] > 0)

    # Exit type breakdown
    tp_count = sum(1 for t in trades if t.exit_reason == "TP")
    sl_count = sum(1 for t in trades if t.exit_reason == "SL")
    time_count = sum(1 for t in trades if t.exit_reason in ("TIME_EXIT", "TIME_NEW_SESSION", "END"))

    return {
        "n": len(trades),
        "wr": len(wins) / len(trades) * 100,
        "pf": gross_profit / gross_loss,
        "exp": np.mean(pnls),
        "total": sum(pnls),
        "max_dd": max_dd,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "max_consec_loss": max_consec_loss,
        "monthly": monthly,
        "positive_months": positive_months,
        "total_months": len(monthly),
        "tp_pct": tp_count / len(trades) * 100,
        "sl_pct": sl_count / len(trades) * 100,
        "time_pct": time_count / len(trades) * 100,
    }


# ---- Walk-Forward ----

def walk_forward(df: pd.DataFrame, symbol: str, trigger: float, target: float,
                 stop: float, max_trades: int, train_months: int = 6,
                 test_months: int = 2) -> dict:
    """Simple walk-forward: split data into train/test windows."""
    dates = sorted(df.index.date)
    if not dates:
        return {}

    start = pd.Timestamp(dates[0], tz=timezone.utc)
    end = pd.Timestamp(dates[-1], tz=timezone.utc)
    total_months = (end.year - start.year) * 12 + (end.month - start.month)

    if total_months < train_months + test_months:
        # Not enough data for walk-forward, just run full backtest
        trades = run_backtest(df, symbol, trigger, target, stop, max_trades)
        return {"oos_trades": trades, "windows": 0}

    oos_trades = []
    window_results = []
    cursor = start

    while True:
        train_end = cursor + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)

        if test_end > end:
            break

        # Train period: just verify the strategy works (we don't optimize per-window)
        train_df = df[(df.index >= cursor) & (df.index < train_end)]
        train_trades = run_backtest(train_df, symbol, trigger, target, stop, max_trades)
        train_metrics = compute_metrics(train_trades)

        # Test period: collect OOS trades
        test_df = df[(df.index >= train_end) & (df.index < test_end)]
        test_trades = run_backtest(test_df, symbol, trigger, target, stop, max_trades)
        test_metrics = compute_metrics(test_trades)

        window_results.append({
            "train_start": cursor.date(),
            "test_start": train_end.date(),
            "test_end": test_end.date(),
            "train_pf": train_metrics.get("pf", 0),
            "test_pf": test_metrics.get("pf", 0),
            "test_trades": len(test_trades),
            "test_wr": test_metrics.get("wr", 0),
        })

        oos_trades.extend(test_trades)
        cursor += pd.DateOffset(months=test_months)  # step forward

    return {"oos_trades": oos_trades, "windows": window_results}


# ---- Main ----

def main():
    init_mt5()

    for symbol in PAIRS:
        print(f"\n{'='*80}")
        print(f"  {symbol} -- Asian Gravity Backtest (M15)")
        print(f"{'='*80}")

        df = fetch_data(symbol, LOOKBACK_DAYS)
        if df.empty:
            print("  No data")
            continue

        pip_val = PIP_VALUES[symbol]
        print(f"  {len(df)} bars, {df.index[0].date()} to {df.index[-1].date()}")

        # ---- Parameter Sweep ----
        print(f"\n  Parameter sweep ({len(PARAM_GRID)} combinations):")
        print(f"  {'Trig':>5} {'Tgt':>4} {'SL':>4} {'Max':>4} {'Trades':>7} "
              f"{'WR':>5} {'PF':>6} {'Exp':>7} {'Total':>7} {'MaxDD':>6} "
              f"{'ConsL':>6} {'TP%':>5} {'SL%':>5}")

        all_results = []
        for trigger, target, stop, max_t in PARAM_GRID:
            trades = run_backtest(df, symbol, trigger, target, stop, max_t)
            m = compute_metrics(trades)
            if m["n"] == 0:
                continue
            all_results.append((trigger, target, stop, max_t, m))

        # Sort by total pips (not expectancy - we want absolute profit)
        all_results.sort(key=lambda x: x[4]["total"], reverse=True)

        for trig, tgt, sl, max_t, m in all_results[:20]:
            marker = " *" if m["pf"] > 1.0 else ""
            print(f"  {trig:>4}p {tgt:>3}p {sl:>3}p {max_t:>4} {m['n']:>7} "
                  f"{m['wr']:>4.0f}% {m['pf']:>6.2f} {m['exp']:>+6.2f}p "
                  f"{m['total']:>+6.0f}p {m['max_dd']:>5.0f}p "
                  f"{m['max_consec_loss']:>5} {m['tp_pct']:>4.0f}% {m['sl_pct']:>4.0f}%{marker}")

        # ---- Best Combo Deep Dive ----
        profitable = [r for r in all_results if r[4]["pf"] > 1.0]
        if not profitable:
            print(f"\n  No profitable parameter combination found for {symbol}.")
            continue

        best = profitable[0]
        trig, tgt, sl, max_t, m = best
        print(f"\n  {'='*60}")
        print(f"  BEST: trigger={trig}p target={tgt}p stop={sl}p max={max_t}")
        print(f"  {'='*60}")
        print(f"  Trades: {m['n']}")
        print(f"  Win Rate: {m['wr']:.1f}%")
        print(f"  Profit Factor: {m['pf']:.2f}")
        print(f"  Expectancy: {m['exp']:+.2f} pips/trade")
        print(f"  Total P&L: {m['total']:+.0f} pips")
        print(f"  Max Drawdown: {m['max_dd']:.0f} pips")
        print(f"  Max Consec Losses: {m['max_consec_loss']}")
        print(f"  Avg Win: {m['avg_win']:.1f}p | Avg Loss: {m['avg_loss']:.1f}p")
        print(f"  Exit: TP={m['tp_pct']:.0f}% SL={m['sl_pct']:.0f}% Time={m['time_pct']:.0f}%")

        # Monthly breakdown
        print(f"\n  Monthly breakdown ({m['positive_months']}/{m['total_months']} positive):")
        for month, data in sorted(m["monthly"].items()):
            wr = data["wins"] / data["n"] * 100 if data["n"] > 0 else 0
            marker = "+" if data["pnl"] > 0 else "-"
            print(f"    {month}: {data['pnl']:>+7.1f}p  {data['n']:>3} trades  WR={wr:.0f}%  {marker}")

        # Position sizing
        print(f"\n  Position sizing ($10k account, {sl}p stop):")
        for risk_pct in [0.5, 1.0, 2.0, 3.0, 5.0]:
            risk_usd = 10000 * risk_pct / 100
            # For EURGBP: pip value ~ $12.7/lot (depends on GBP/USD rate)
            # For EURUSD: pip value = $10/lot
            pip_usd = 10.0 if symbol == "EURUSD" else 12.7
            lots = risk_usd / (sl * pip_usd)
            annual_pnl_usd = m["total"] * lots * pip_usd
            annual_ret = annual_pnl_usd / 10000 * 100
            max_dd_usd = m["max_dd"] * lots * pip_usd
            max_dd_pct = max_dd_usd / 10000 * 100
            print(f"    {risk_pct:>4.1f}% risk -> {lots:.2f} lots | "
                  f"P&L: ${annual_pnl_usd:>+8,.0f} ({annual_ret:>+5.0f}%) | "
                  f"MaxDD: ${max_dd_usd:>6,.0f} ({max_dd_pct:>4.1f}%)")

        # Walk-forward validation
        print(f"\n  Walk-forward validation (6m train / 2m test):")
        wf = walk_forward(df, symbol, trig, tgt, sl, max_t)
        if wf.get("windows"):
            for w in wf["windows"]:
                marker = "+" if w["test_pf"] > 1.0 else "-"
                print(f"    {w['test_start']} - {w['test_end']}: "
                      f"PF={w['test_pf']:.2f} WR={w['test_wr']:.0f}% "
                      f"({w['test_trades']} trades) {marker}")

            oos_metrics = compute_metrics(wf["oos_trades"])
            if oos_metrics["n"] > 0:
                pos_windows = sum(1 for w in wf["windows"] if w["test_pf"] > 1.0)
                print(f"\n  OOS Combined: {oos_metrics['n']} trades, "
                      f"PF={oos_metrics['pf']:.2f}, WR={oos_metrics['wr']:.0f}%, "
                      f"Exp={oos_metrics['exp']:+.2f}p")
                print(f"  Positive windows: {pos_windows}/{len(wf['windows'])}")
        else:
            print("    Not enough data for walk-forward (need 8+ months)")

    mt5.shutdown()
    print(f"\n{'='*80}")
    print("Done.")


if __name__ == "__main__":
    main()
