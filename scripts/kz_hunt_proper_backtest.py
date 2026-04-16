"""KZ Hunt proper backtest using the REAL backtest engine, local CSV data."""
import sys, os
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader import config

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests", "data")
CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests", "charts")

INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]

def load_h1(symbol):
    path = os.path.join(DATA_DIR, "{}_H1.csv".format(symbol))
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # Keep time as column (backtest engine expects it) AND as index
    df.index = df["time"]
    # Add indicators that fetch_and_prepare normally adds
    df["tr"] = np.maximum(df["high"] - df["low"],
                          np.maximum(abs(df["high"] - df["close"].shift(1)),
                                     abs(df["low"] - df["close"].shift(1))))
    df["atr"] = df["tr"].ewm(span=14, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    # Volume
    if "tick_volume" in df.columns:
        df["volume"] = df["tick_volume"]
    return df

engine = BacktestEngine()
all_trades = []

print("KZ Hunt Proper Backtest (Real Engine)")
print("=" * 70)

for symbol in INSTRUMENTS:
    print("\n  {}...".format(symbol))
    df = load_h1(symbol)
    if df is None:
        print("    No data")
        continue

    print("    {} bars, {} to {}".format(len(df), df.index[0].date(), df.index[-1].date()))

    try:
        result = engine.run(df, symbol)
        trades = result.trades
        total_pips = sum(t.pnl_pips for t in trades)
        wins = sum(1 for t in trades if t.pnl_pips > 0)
        wr = wins / len(trades) * 100 if trades else 0

        print("    {} trades, WR={:.0f}%, PnL={:+.0f}p".format(len(trades), wr, total_pips))

        for t in trades:
            entry_date = t.entry_time.date() if t.entry_time else df.index[0].date()
            all_trades.append({
                "d": entry_date,
                "pnl": t.pnl_pips,
                "x": t.exit_reason,
                "sym": symbol,
            })
    except Exception as e:
        import traceback
        print("    Error: {}".format(e))
        traceback.print_exc()

all_trades.sort(key=lambda t: t["d"])

if not all_trades:
    print("\nNo trades generated")
    sys.exit(0)

# Stats
pnls = [t["pnl"] for t in all_trades]
w = sum(1 for p in pnls if p > 0)
gp = sum(p for p in pnls if p > 0)
gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
eq = np.cumsum(pnls)
dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0

print("\n" + "=" * 70)
print("  KZ HUNT COMBINED (Real Engine)")
print("  {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
    len(all_trades), w / len(all_trades) * 100, gp / gl, sum(pnls), dd))
print("=" * 70)

# Per pair
print("\n  Per pair:")
for sym in INSTRUMENTS:
    st = [t for t in all_trades if t["sym"] == sym]
    if not st: continue
    sw = sum(1 for t in st if t["pnl"] > 0)
    sp_sum = sum(t["pnl"] for t in st)
    sgp = sum(t["pnl"] for t in st if t["pnl"] > 0)
    sgl = abs(sum(t["pnl"] for t in st if t["pnl"] <= 0)) or 0.001
    print("    {}: {}T WR={:.0f}% PF={:.2f} PnL={:+.0f}p".format(
        sym, len(st), sw / len(st) * 100, sgp / sgl, sp_sum))

# Yearly
yearly = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0})
for t in all_trades:
    yr = t["d"].year if hasattr(t["d"], "year") else 2025
    yearly[yr]["n"] += 1; yearly[yr]["pnl"] += t["pnl"]
    if t["pnl"] > 0: yearly[yr]["w"] += 1

print("\n  Yearly:")
for yr in sorted(yearly):
    y = yearly[yr]
    print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
        yr, y["n"], y["w"] / y["n"] * 100 if y["n"] else 0, y["pnl"]))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(18, 12), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("KZ Hunt — Real Backtest Engine (H1, 8 Years, 8 Pairs)",
             fontsize=14, fontweight="bold")

# Equity curve
ax = axes[0]
dates = [t["d"] for t in all_trades]
color = "#2196F3" if eq[-1] > 0 else "#F44336"
ax.plot(dates, eq, color=color, linewidth=1.5)
ax.fill_between(dates, 0, eq, alpha=0.08, color=color)
ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

for j, t in enumerate(all_trades):
    if t["pnl"] > 0: c = "#4CAF50"
    else: c = "#F44336"
    ax.scatter(dates[j], eq[j], color=c, s=3, zorder=5)

ax.text(0.02, 0.95,
        "{}T  WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
            len(all_trades), w / len(all_trades) * 100, gp / gl, sum(pnls), dd),
        transform=ax.transAxes, fontsize=10, va="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.grid(True, alpha=0.15)

# Per-pair equity
ax2 = axes[1]
pair_colors = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336", "#795548", "#00BCD4", "#E91E63"]
for idx, sym in enumerate(INSTRUMENTS):
    st = sorted([t for t in all_trades if t["sym"] == sym], key=lambda t: t["d"])
    if not st: continue
    sym_eq = np.cumsum([t["pnl"] for t in st])
    sym_dates = [t["d"] for t in st]
    ax2.plot(sym_dates, sym_eq, color=pair_colors[idx], linewidth=1, alpha=0.7, label=sym)

ax2.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
ax2.legend(fontsize=7, ncol=4, loc="upper left")
ax2.set_ylabel("Per-Pair P&L (pips)", fontsize=9)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax2.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(CHART_DIR, "kz_hunt_proper_backtest.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))
