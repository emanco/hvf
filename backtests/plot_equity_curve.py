"""
Plot equity curve + drawdown from 1-year backtest.

Shows:
  1. Cumulative equity curve (backtest ideal)
  2. Slippage-adjusted equity curve (1 pip/trade deducted)
  3. Underwater (drawdown) chart
  4. Monthly returns heatmap
  5. Per-pair contribution breakdown

Runs on VPS where MT5 data is available.
Charts saved to backtests/charts/.
"""

import sys
import os
import logging

sys.path.insert(0, "C:/")
from dotenv import load_dotenv
load_dotenv("C:/hvf_trader/.env")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.backtest_engine import BacktestEngine

logging.basicConfig(level=logging.WARNING)

SYMBOLS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
EQUITY = 10000.0
SLIPPAGE_PIPS = 1.0  # realistic slippage per trade

CHART_DIR = os.path.join(os.path.dirname(__file__), "charts")
os.makedirs(CHART_DIR, exist_ok=True)


def fetch_history(symbol, timeframe_mt5, bars=20000):
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, bars)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def main():
    path = os.getenv("MT5_PATH")
    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not mt5.initialize(path=path):
        print(f"MT5 init failed: {mt5.last_error()}")
        return
    if not mt5.login(login, password=password, server=server):
        print(f"MT5 login failed: {mt5.last_error()}")
        return
    print("MT5 connected")

    # Fetch data
    all_data = {}
    for symbol in SYMBOLS:
        print(f"  Fetching {symbol}...", end=" ", flush=True)
        df = fetch_history(symbol, mt5.TIMEFRAME_H1, bars=20000)
        if df is None:
            print("FAILED")
            continue
        df = add_indicators(df)
        df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        all_data[symbol] = df
        print(f"{len(df)} bars")
    mt5.shutdown()

    # Run 1-year backtest per pair
    one_year_ago = pd.Timestamp("2025-04-12", tz="UTC")
    now = pd.Timestamp("2026-04-12", tz="UTC")

    all_trades = []
    pair_trades = {}

    for symbol, df_1h in all_data.items():
        mask = (df_1h["time"] >= one_year_ago) & (df_1h["time"] <= now)
        df_period = df_1h[mask].copy().reset_index(drop=True)
        if len(df_period) < 300:
            continue

        engine = BacktestEngine(starting_equity=EQUITY, enabled_patterns=["KZ_HUNT"])
        result = engine.run(df_period, symbol)

        pair_trades[symbol] = result.trades
        all_trades.extend(result.trades)
        print(f"  {symbol}: {result.total_trades} trades, PF={result.profit_factor:.2f}")

    if not all_trades:
        print("No trades — nothing to plot.")
        return

    # Sort all trades by exit time
    all_trades.sort(key=lambda t: t.exit_time)

    # Build equity curves
    times = []
    equity_ideal = []
    equity_slip = []
    eq = EQUITY
    eq_slip = EQUITY
    # Add starting point
    times.append(all_trades[0].entry_time)
    equity_ideal.append(eq)
    equity_slip.append(eq_slip)

    for t in all_trades:
        pip_val = config.PIP_VALUES.get(t.symbol, 0.0001)
        contract_size = 100_000
        slip_cost = SLIPPAGE_PIPS * pip_val * t.lot_size * contract_size
        eq += t.pnl_currency
        eq_slip += t.pnl_currency - slip_cost
        times.append(t.exit_time)
        equity_ideal.append(eq)
        equity_slip.append(eq_slip)

    times = pd.to_datetime(times)

    # Drawdown calculations
    def calc_drawdown(eq_series):
        peak = np.maximum.accumulate(eq_series)
        dd = (eq_series - peak) / peak * 100
        return dd

    eq_arr = np.array(equity_ideal)
    eq_slip_arr = np.array(equity_slip)
    dd_ideal = calc_drawdown(eq_arr)
    dd_slip = calc_drawdown(eq_slip_arr)

    # ─── CHART 1: Equity Curve + Drawdown ────────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[3, 1],
                                    sharex=True, gridspec_kw={"hspace": 0.05})

    ax1.plot(times, equity_ideal, color="#2196F3", linewidth=1.5, label="Backtest (ideal)")
    ax1.plot(times, equity_slip, color="#FF9800", linewidth=1.5, label=f"With {SLIPPAGE_PIPS} pip slippage/trade")
    ax1.axhline(EQUITY, color="gray", linestyle="--", alpha=0.5, linewidth=0.8)
    ax1.set_ylabel("Equity ($)", fontsize=11)
    ax1.set_title("KZ_HUNT Strategy — 1-Year Equity Curve (5 Pairs, $10k Start)", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=10)
    ax1.grid(True, alpha=0.3)

    # Annotate final values
    ax1.annotate(f"${equity_ideal[-1]:,.0f}", xy=(times[-1], equity_ideal[-1]),
                 fontsize=10, color="#2196F3", fontweight="bold",
                 xytext=(10, 5), textcoords="offset points")
    ax1.annotate(f"${equity_slip[-1]:,.0f}", xy=(times[-1], equity_slip[-1]),
                 fontsize=10, color="#FF9800", fontweight="bold",
                 xytext=(10, -15), textcoords="offset points")

    # Drawdown
    ax2.fill_between(times, dd_ideal, 0, alpha=0.3, color="#2196F3", label="Ideal DD")
    ax2.fill_between(times, dd_slip, 0, alpha=0.3, color="#FF9800", label="Slippage DD")
    ax2.set_ylabel("Drawdown (%)", fontsize=11)
    ax2.set_xlabel("Date", fontsize=11)
    ax2.legend(loc="lower left", fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)

    # Stats box
    total_trades = len(all_trades)
    winners = [t for t in all_trades if t.pnl_pips > 0]
    wr = len(winners) / total_trades * 100
    gross_p = sum(t.pnl_currency for t in winners) if winners else 0
    losers = [t for t in all_trades if t.pnl_pips <= 0]
    gross_l = abs(sum(t.pnl_currency for t in losers)) if losers else 0
    pf = gross_p / gross_l if gross_l > 0 else float("inf")
    max_dd = min(dd_ideal)
    max_dd_slip = min(dd_slip)
    total_return = (equity_ideal[-1] / EQUITY - 1) * 100
    slip_return = (equity_slip[-1] / EQUITY - 1) * 100

    stats_text = (
        f"Trades: {total_trades}  |  WR: {wr:.1f}%  |  PF: {pf:.2f}\n"
        f"Return: {total_return:+.1f}% (ideal)  {slip_return:+.1f}% (w/ slip)\n"
        f"Max DD: {max_dd:.1f}% (ideal)  {max_dd_slip:.1f}% (w/ slip)"
    )
    ax1.text(0.02, 0.05, stats_text, transform=ax1.transAxes, fontsize=9,
             verticalalignment="bottom", fontfamily="monospace",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8))

    plt.tight_layout()
    path1 = os.path.join(CHART_DIR, "equity_curve.png")
    plt.savefig(path1, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path1}")

    # ─── CHART 2: Monthly Returns ────────────────────────────────────
    # Group trades by month
    monthly = {}
    for t in all_trades:
        key = t.exit_time.strftime("%Y-%m")
        monthly[key] = monthly.get(key, 0) + t.pnl_currency

    months = sorted(monthly.keys())
    returns = [monthly[m] / EQUITY * 100 for m in months]
    month_labels = [pd.Timestamp(m + "-01").strftime("%b\n%Y") for m in months]
    colors = ["#4CAF50" if r >= 0 else "#F44336" for r in returns]

    fig, ax = plt.subplots(figsize=(14, 5))
    bars = ax.bar(range(len(months)), returns, color=colors, edgecolor="white", linewidth=0.5)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(month_labels, fontsize=9)
    ax.set_ylabel("Return (%)", fontsize=11)
    ax.set_title("KZ_HUNT Monthly Returns (% of Starting Equity)", fontsize=13, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)

    # Label each bar
    for bar, ret in zip(bars, returns):
        y = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, y + (0.2 if y >= 0 else -0.5),
                f"{ret:+.1f}%", ha="center", va="bottom" if y >= 0 else "top", fontsize=8)

    plt.tight_layout()
    path2 = os.path.join(CHART_DIR, "monthly_returns.png")
    plt.savefig(path2, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path2}")

    # ─── CHART 3: Per-Pair Equity Contribution ───────────────────────
    fig, ax = plt.subplots(figsize=(14, 6))
    pair_colors = {
        "EURUSD": "#2196F3", "NZDUSD": "#4CAF50", "EURGBP": "#FF9800",
        "USDCHF": "#9C27B0", "EURAUD": "#F44336",
    }

    for symbol in SYMBOLS:
        trades = pair_trades.get(symbol, [])
        if not trades:
            continue
        trades_sorted = sorted(trades, key=lambda t: t.exit_time)
        t_times = [trades_sorted[0].entry_time]
        cumulative = [0]
        running = 0
        for t in trades_sorted:
            running += t.pnl_pips
            t_times.append(t.exit_time)
            cumulative.append(running)
        ax.plot(t_times, cumulative, label=symbol, color=pair_colors.get(symbol, "gray"), linewidth=1.3)

    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Cumulative Pips", fontsize=11)
    ax.set_xlabel("Date", fontsize=11)
    ax.set_title("KZ_HUNT Per-Pair Pip Contribution (1 Year)", fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)
    plt.tight_layout()
    path3 = os.path.join(CHART_DIR, "pair_contribution.png")
    plt.savefig(path3, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path3}")

    # ─── CHART 4: Trade Distribution ─────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # PnL distribution
    pnl_pips = [t.pnl_pips for t in all_trades]
    ax1.hist(pnl_pips, bins=50, color="#2196F3", edgecolor="white", alpha=0.8)
    ax1.axvline(0, color="red", linewidth=1, linestyle="--")
    ax1.axvline(np.mean(pnl_pips), color="green", linewidth=1.5, linestyle="-",
                label=f"Mean: {np.mean(pnl_pips):+.1f} pips")
    ax1.set_xlabel("PnL (pips)", fontsize=11)
    ax1.set_ylabel("Count", fontsize=11)
    ax1.set_title("Trade PnL Distribution", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)

    # Win/loss streak
    streaks = []
    current = 0
    for t in all_trades:
        if t.pnl_pips > 0:
            if current > 0:
                current += 1
            else:
                if current != 0:
                    streaks.append(current)
                current = 1
        else:
            if current < 0:
                current -= 1
            else:
                if current != 0:
                    streaks.append(current)
                current = -1
    if current != 0:
        streaks.append(current)

    win_streaks = [s for s in streaks if s > 0]
    loss_streaks = [abs(s) for s in streaks if s < 0]

    streak_labels = ["Win Streaks", "Loss Streaks"]
    streak_data = [win_streaks, loss_streaks]
    streak_colors = ["#4CAF50", "#F44336"]

    bp = ax2.boxplot(streak_data, labels=streak_labels, patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], streak_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax2.set_ylabel("Streak Length", fontsize=11)
    ax2.set_title("Win/Loss Streak Distribution", fontsize=12, fontweight="bold")
    ax2.grid(True, alpha=0.3, axis="y")

    max_win = max(win_streaks) if win_streaks else 0
    max_loss = max(loss_streaks) if loss_streaks else 0
    ax2.text(0.95, 0.95, f"Max win streak: {max_win}\nMax loss streak: {max_loss}",
             transform=ax2.transAxes, fontsize=9, va="top", ha="right",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    plt.tight_layout()
    path4 = os.path.join(CHART_DIR, "trade_distribution.png")
    plt.savefig(path4, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path4}")

    print("\nDone. scp charts back:")
    print(f"  scp hvf-vps:'C:/hvf_trader/backtests/charts/equity_curve.png' backtests/charts/")
    print(f"  scp hvf-vps:'C:/hvf_trader/backtests/charts/monthly_returns.png' backtests/charts/")
    print(f"  scp hvf-vps:'C:/hvf_trader/backtests/charts/pair_contribution.png' backtests/charts/")
    print(f"  scp hvf-vps:'C:/hvf_trader/backtests/charts/trade_distribution.png' backtests/charts/")


if __name__ == "__main__":
    main()
