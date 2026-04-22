"""KZ Hunt proper backtest using the REAL backtest engine, local CSV data."""
import sys, os
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests", "data")
CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests", "charts")

INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]

def load_h1(symbol):
    path = os.path.join(DATA_DIR, "{}_H1.csv".format(symbol))
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # Engine expects integer-indexed df with 'time' as a column.
    df = add_indicators(df)
    if "tick_volume" in df.columns:
        df["volume"] = df["tick_volume"]
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    return df

engine = BacktestEngine(
    starting_equity=10000.0,
    enabled_patterns=["KZ_HUNT"],
    simulate_news_blocks=True,
    simulate_circuit_breaker=True,
)
all_trades = []
per_pair_trades = {}  # sym -> [(date, pnl_pips, exit_reason)]

print("KZ Hunt Proper Backtest (Real Engine)")
print("=" * 70)

for symbol in INSTRUMENTS:
    print("\n  {}...".format(symbol))
    df = load_h1(symbol)
    if df is None:
        print("    No data")
        continue

    print("    {} bars, {} to {}".format(len(df), df["time"].iloc[0].date(), df["time"].iloc[-1].date()))

    try:
        result = engine.run(df, symbol)
        trades = result.trades
        total_pips = sum(t.pnl_pips for t in trades)
        wins = sum(1 for t in trades if t.pnl_pips > 0)
        wr = wins / len(trades) * 100 if trades else 0

        print("    {} trades, WR={:.0f}%, PnL={:+.0f}p".format(len(trades), wr, total_pips))

        pair_list = []
        for t in trades:
            entry_date = t.entry_time.date() if t.entry_time else df["time"].iloc[0].date()
            rec = {"d": entry_date, "pnl": t.pnl_pips, "x": t.exit_reason, "sym": symbol}
            all_trades.append(rec)
            pair_list.append(rec)
        per_pair_trades[symbol] = pair_list

        # Per-pair equity curve chart (saved as soon as pair completes)
        if pair_list:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            pair_list_sorted = sorted(pair_list, key=lambda x: x["d"])
            dates = [r["d"] for r in pair_list_sorted]
            eq_curve = np.cumsum([r["pnl"] for r in pair_list_sorted])
            wins = sum(1 for r in pair_list if r["pnl"] > 0)
            gp = sum(r["pnl"] for r in pair_list if r["pnl"] > 0)
            gl = abs(sum(r["pnl"] for r in pair_list if r["pnl"] <= 0)) or 0.001
            pair_wr = wins / len(pair_list) * 100
            pair_pf = gp / gl
            dd = max(np.maximum.accumulate(eq_curve) - eq_curve) if len(eq_curve) > 1 else 0
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.plot(dates, eq_curve, color="tab:blue", linewidth=1.4)
            ax.fill_between(dates, eq_curve, 0, where=eq_curve >= 0, color="tab:green", alpha=0.15)
            ax.fill_between(dates, eq_curve, 0, where=eq_curve < 0, color="tab:red", alpha=0.15)
            ax.axhline(0, color="k", linewidth=0.5)
            ax.set_title(
                "KZ Hunt — {} ({}-{} H1)  |  n={}  WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
                    symbol,
                    df["time"].iloc[0].year, df["time"].iloc[-1].year,
                    len(pair_list), pair_wr, pair_pf, sum(r["pnl"] for r in pair_list), dd,
                ),
                fontsize=11,
            )
            ax.set_ylabel("Cumulative pips")
            ax.grid(alpha=0.3)
            fig.tight_layout()
            chart_path = os.path.join(CHART_DIR, "kz_hunt_bt_{}.png".format(symbol))
            fig.savefig(chart_path, dpi=110)
            plt.close(fig)
            print("    Chart: {}".format(chart_path))
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
