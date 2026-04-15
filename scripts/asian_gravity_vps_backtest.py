"""
Asian Gravity — VPS Backtest with Equity Chart

Runs on VPS using MT5 M15 data. Generates equity chart PNG.
Tests the Wednesday LONG-only gravity strategy on EURGBP.

Usage:
    C:\\hvf_trader\\venv\\Scripts\\python.exe scripts/asian_gravity_vps_backtest.py
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
import numpy as np
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# ---- Config ----
SYMBOL = "EURGBP"
PIP = 0.0001
SPREAD = 1.0  # conservative Asian spread
TRIGGER = 3
TARGET = 2
STOP = 4
MAX_RANGE = 10
DAYS = [2]  # Wednesday only
DIRECTION = "LONG"
LOOKBACK_YEARS = 10

CHART_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "backtests" / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)


def init_mt5():
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}")
        sys.exit(1)
    login = int(os.getenv("MT5_LOGIN", "0"))
    mt5.login(login, os.getenv("MT5_PASSWORD", ""), os.getenv("MT5_SERVER", ""))
    print(f"Connected: account {login}")


def fetch_data():
    # Use copy_rates_from_pos (works when copy_rates_range doesn't on IC Markets)
    # Try M5 first, then M15, then H1
    for tf_name, tf, count in [
        ("M5", mt5.TIMEFRAME_M5, 50000),
        ("M15", mt5.TIMEFRAME_M15, 50000),
        ("H1", mt5.TIMEFRAME_H1, 100000),
    ]:
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
        if rates is not None and len(rates) > 0:
            first = datetime.fromtimestamp(rates[0][0], tz=timezone.utc)
            last = datetime.fromtimestamp(rates[-1][0], tz=timezone.utc)
            print(f"  {tf_name}: {len(rates)} bars, {first.date()} to {last.date()}")
            return rates, tf_name
        print(f"  {tf_name}: not available, trying next...")
    print("No data available")
    return None, None


def run_backtest(rates, timeframe):
    """Bar-by-bar backtest."""
    trades = []  # list of dicts: date, pnl, exit_reason

    session_date = None
    session_open = 0.0
    form_high = form_low = 0.0
    in_formation = False
    open_trade = None  # (direction, entry_price, tp_price, sl_price)
    traded_today = False
    range_pips = 0

    for i in range(len(rates)):
        r = rates[i]
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        h = ts.hour
        bd = ts.date()
        o, hi, lo, cl = r[1], r[2], r[3], r[4]

        if ts.weekday() >= 5:
            continue

        # New session at 00:00
        if h == 0 and bd != session_date:
            # Force close open trade
            if open_trade:
                d, ep, tp, sl = open_trade
                pnl = (cl - ep) / PIP - SPREAD if d == "L" else (ep - cl) / PIP - SPREAD
                trades.append({"date": session_date, "pnl": pnl, "exit": "TIME"})
                open_trade = None

            session_date = bd
            session_open = o
            form_high = hi
            form_low = lo
            in_formation = True
            traded_today = False
            range_pips = 0
            continue

        # Outside session
        if h >= 6 or session_date != bd:
            if open_trade:
                d, ep, tp, sl = open_trade
                pnl = (cl - ep) / PIP - SPREAD if d == "L" else (ep - cl) / PIP - SPREAD
                trades.append({"date": session_date, "pnl": pnl, "exit": "TIME"})
                open_trade = None
            continue

        # Formation (00:00-02:00)
        if in_formation and h < 2:
            form_high = max(form_high, hi)
            form_low = min(form_low, lo)
            continue

        # Transition
        if in_formation and h >= 2:
            in_formation = False
            range_pips = (form_high - form_low) / PIP
            if range_pips > MAX_RANGE or range_pips < 1:
                session_date = None
                continue
            # Day filter
            if ts.weekday() not in DAYS:
                session_date = None
                continue

        if session_date is None:
            continue

        # Manage open trade
        if open_trade:
            d, ep, tp, sl = open_trade
            if d == "L":
                if lo <= sl:
                    trades.append({"date": session_date, "pnl": (sl - ep) / PIP - SPREAD, "exit": "SL"})
                    open_trade = None
                    continue
                if hi >= tp:
                    trades.append({"date": session_date, "pnl": (tp - ep) / PIP - SPREAD, "exit": "TP"})
                    open_trade = None
                    continue
            else:
                if hi >= sl:
                    trades.append({"date": session_date, "pnl": (ep - sl) / PIP - SPREAD, "exit": "SL"})
                    open_trade = None
                    continue
                if lo <= tp:
                    trades.append({"date": session_date, "pnl": (ep - tp) / PIP - SPREAD, "exit": "TP"})
                    open_trade = None
                    continue
            continue

        # Entry detection
        if traded_today:
            continue

        trigger_price = session_open - TRIGGER * PIP
        if DIRECTION == "LONG" and lo <= trigger_price:
            ep = trigger_price  # entry at trigger level
            tp_price = ep + TARGET * PIP
            sl_price = ep - STOP * PIP
            open_trade = ("L", ep, tp_price, sl_price)
            traded_today = True

    return trades


def generate_chart(trades, timeframe, data_start, data_end):
    """Generate equity curve chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import date

    pnls = [t["pnl"] for t in trades]
    dates = [t["date"] for t in trades]
    equity = np.cumsum(pnls)

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    wr = wins / len(pnls) * 100 if pnls else 0
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    pf = gp / gl
    total = sum(pnls)
    max_dd = max(np.maximum.accumulate(equity) - equity) if len(equity) > 0 else 0

    # Consecutive losses
    consec = 0
    max_consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    # Monthly breakdown
    monthly = {}
    for t in trades:
        key = t["date"].strftime("%Y-%m") if hasattr(t["date"], "strftime") else str(t["date"])[:7]
        monthly[key] = monthly.get(key, 0) + t["pnl"]
    pos_months = sum(1 for v in monthly.values() if v > 0)

    # Yearly breakdown
    yearly = {}
    for t in trades:
        yr = t["date"].year if hasattr(t["date"], "year") else int(str(t["date"])[:4])
        if yr not in yearly:
            yearly[yr] = {"pnl": 0, "n": 0, "wins": 0}
        yearly[yr]["pnl"] += t["pnl"]
        yearly[yr]["n"] += 1
        if t["pnl"] > 0:
            yearly[yr]["wins"] += 1

    # Print stats
    print(f"\n{'='*60}")
    print(f"  EURGBP Asian Gravity Backtest Results ({timeframe})")
    print(f"  Data: {data_start} to {data_end}")
    print(f"{'='*60}")
    print(f"  Trades: {len(trades)} (W:{wins} L:{losses})")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Expectancy: {np.mean(pnls):+.2f} pips/trade")
    print(f"  Total P&L: {total:+.1f} pips")
    print(f"  Max Drawdown: {max_dd:.1f} pips")
    print(f"  Max Consec Losses: {max_consec}")
    print(f"  Positive Months: {pos_months}/{len(monthly)}")

    tp_count = sum(1 for t in trades if t["exit"] == "TP")
    sl_count = sum(1 for t in trades if t["exit"] == "SL")
    time_count = sum(1 for t in trades if t["exit"] == "TIME")
    print(f"  Exits: TP={tp_count} SL={sl_count} TIME={time_count}")

    print(f"\n  Yearly Breakdown:")
    for yr in sorted(yearly):
        y = yearly[yr]
        ywr = y["wins"] / y["n"] * 100 if y["n"] > 0 else 0
        print(f"    {yr}: {y['n']:>3} trades, WR={ywr:>4.0f}%, PnL={y['pnl']:>+7.1f}p")

    # Position sizing at 2% risk
    print(f"\n  At 2% risk ($10k account, {STOP}p stop):")
    pip_usd = 12.7
    lots = (10000 * 0.02) / (STOP * pip_usd)
    pnl_usd = total * lots * pip_usd
    dd_usd = max_dd * lots * pip_usd
    years = max(1, (data_end - data_start).days / 365)
    annual_pnl = pnl_usd / years
    print(f"    Lots: {lots:.2f}")
    print(f"    Total P&L: ${pnl_usd:+,.0f}")
    print(f"    Annual avg: ${annual_pnl:+,.0f}/year")
    print(f"    Max DD: ${dd_usd:,.0f}")

    # Create chart
    fig, axes = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(
        f"EURGBP Asian Gravity - Wednesday LONG (T{TRIGGER}/T{TARGET}/S{STOP}, range<{MAX_RANGE}p)\n"
        f"{data_start} to {data_end} | {timeframe} bars",
        fontsize=13, fontweight="bold",
    )

    # Top: equity curve
    ax = axes[0]
    color = "#2196F3" if equity[-1] > 0 else "#F44336"
    ax.plot(dates, equity, color=color, linewidth=1.5)
    ax.fill_between(dates, 0, equity, alpha=0.1, color=color)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)

    for j, t in enumerate(trades):
        if t["exit"] == "TP":
            ax.scatter(dates[j], equity[j], color="#4CAF50", s=8, zorder=5)
        elif t["exit"] == "SL":
            ax.scatter(dates[j], equity[j], color="#F44336", s=12, zorder=5, marker="v")

    stats_text = (
        f"WR={wr:.0f}%  PF={pf:.2f}  Exp={np.mean(pnls):+.2f}p  "
        f"Total={total:+.0f}p  MaxDD={max_dd:.0f}p  Trades={len(trades)}"
    )
    ax.text(0.02, 0.95, stats_text, transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(labelsize=8)

    # Bottom: monthly P&L bars
    ax2 = axes[1]
    months = sorted(monthly.keys())
    month_pnls = [monthly[m] for m in months]
    colors = ["#4CAF50" if p > 0 else "#F44336" for p in month_pnls]
    ax2.bar(range(len(months)), month_pnls, color=colors, width=0.8)
    ax2.axhline(y=0, color="gray", linewidth=0.5)
    ax2.set_ylabel("Monthly P&L (pips)", fontsize=9)
    ax2.set_xlabel("Month", fontsize=9)
    # Show year labels
    year_ticks = []
    year_labels = []
    for i, m in enumerate(months):
        if m.endswith("-01") or i == 0:
            year_ticks.append(i)
            year_labels.append(m[:4])
    ax2.set_xticks(year_ticks)
    ax2.set_xticklabels(year_labels, fontsize=8)
    ax2.grid(True, alpha=0.2)

    plt.tight_layout()
    outpath = str(CHART_DIR / "asian_gravity_10yr_backtest.png")
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  Chart saved: {outpath}")


def main():
    init_mt5()
    print(f"Fetching {SYMBOL} data (up to {LOOKBACK_YEARS} years)...")
    rates, timeframe = fetch_data()
    if rates is None:
        mt5.shutdown()
        return

    first = datetime.fromtimestamp(rates[0][0], tz=timezone.utc)
    last = datetime.fromtimestamp(rates[-1][0], tz=timezone.utc)
    print(f"  {len(rates)} {timeframe} bars: {first.date()} to {last.date()}")

    print("Running backtest...")
    trades = run_backtest(rates, timeframe)

    if not trades:
        print("No trades generated")
        mt5.shutdown()
        return

    generate_chart(trades, timeframe, first.date(), last.date())
    mt5.shutdown()


if __name__ == "__main__":
    main()
