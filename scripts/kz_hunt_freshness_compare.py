"""KZ Hunt: backtest comparison freshness=24 (old) vs freshness=1 (new).

The freshness fix is the dominant lever in the 7-fix bundle. The backtest
engine fully supports it via PATTERN_FRESHNESS_BARS. The other fixes
(drift gate, BE@50%T1, ATR trail, time stop, limit orders) aren't yet wired
into the engine; the chart below isolates the freshness effect on its own.

Output: backtests/charts/kz_hunt_freshness_compare.png
"""
import sys, os
from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backtests", "data")
CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "backtests", "charts")
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]


def load_h1(symbol):
    path = os.path.join(DATA_DIR, f"{symbol}_H1.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = add_indicators(df)
    if "tick_volume" in df.columns:
        df["volume"] = df["tick_volume"]
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    return df


def run_backtest(freshness_bars, label):
    """Run KZ_HUNT engine across all pairs with given freshness setting."""
    config.PATTERN_FRESHNESS_BARS["KZ_HUNT"] = freshness_bars
    config.INVALIDATION_ENABLED_BY_PATTERN["KZ_HUNT"] = (freshness_bars != 1)  # Old config had invalidation on
    engine = BacktestEngine(
        starting_equity=10000.0,
        enabled_patterns=["KZ_HUNT"],
        simulate_news_blocks=True,
        simulate_circuit_breaker=True,
    )
    all_trades = []
    print(f"\n=== {label} (freshness={freshness_bars}) ===")
    for sym in INSTRUMENTS:
        df = load_h1(sym)
        if df is None:
            continue
        try:
            res = engine.run(df, sym)
            for t in res.trades:
                d = t.entry_time.date() if t.entry_time else df["time"].iloc[0].date()
                all_trades.append({"d": d, "pnl": t.pnl_pips, "x": t.exit_reason, "sym": sym})
            wins = sum(1 for t in res.trades if t.pnl_pips > 0)
            tot = sum(t.pnl_pips for t in res.trades)
            print(f"  {sym}: {len(res.trades)} trades, WR={wins/max(1,len(res.trades))*100:.0f}%, "
                  f"PnL={tot:+.0f}p")
        except Exception as e:
            print(f"  {sym}: error {e}")
    all_trades.sort(key=lambda t: t["d"])
    return all_trades


def stats(trades):
    if not trades:
        return None
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    return {
        "n": len(trades), "wr": w / len(trades) * 100, "pf": gp / gl,
        "tot": sum(pnls), "dd": dd, "eq": eq, "dates": [t["d"] for t in trades],
    }


# Run both
old_trades = run_backtest(24, "OLD CONFIG (freshness=24, invalidation=ON)")
new_trades = run_backtest(1, "NEW CONFIG (freshness=1, invalidation=OFF)")

s_old = stats(old_trades)
s_new = stats(new_trades)

print("\n" + "=" * 70)
print("SUMMARY")
print(f"  OLD: n={s_old['n']:5d}  WR={s_old['wr']:.0f}%  PF={s_old['pf']:.2f}  "
      f"Tot={s_old['tot']:+.0f}p  DD={s_old['dd']:.0f}p")
print(f"  NEW: n={s_new['n']:5d}  WR={s_new['wr']:.0f}%  PF={s_new['pf']:.2f}  "
      f"Tot={s_new['tot']:+.0f}p  DD={s_new['dd']:.0f}p")
print("=" * 70)

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("KZ Hunt — Backtest comparison: OLD vs NEW config (8 pairs, H1)",
             fontsize=14, fontweight="bold")

# Equity curves
ax = axes[0]
ax.plot(s_old["dates"], s_old["eq"], color="#888", linewidth=1.4,
        label=f"OLD (freshness=24, inval ON)  n={s_old['n']} WR={s_old['wr']:.0f}% "
              f"PF={s_old['pf']:.2f} Tot={s_old['tot']:+.0f}p DD={s_old['dd']:.0f}p")
ax.plot(s_new["dates"], s_new["eq"], color="#2196F3", linewidth=1.8,
        label=f"NEW (freshness=1, inval OFF)  n={s_new['n']} WR={s_new['wr']:.0f}% "
              f"PF={s_new['pf']:.2f} Tot={s_new['tot']:+.0f}p DD={s_new['dd']:.0f}p")
ax.fill_between(s_new["dates"], 0, s_new["eq"],
                where=np.array(s_new["eq"]) >= 0, alpha=0.10, color="green")
ax.fill_between(s_new["dates"], 0, s_new["eq"],
                where=np.array(s_new["eq"]) < 0, alpha=0.10, color="red")
ax.axhline(0, color="k", linewidth=0.5)
ax.set_ylabel("Cumulative pips")
ax.set_title("Equity curves — pure freshness fix isolated. Other fixes (drift gate, "
             "BE@50%T1, ATR trail, time stop, limit) layered on live but not in backtest engine.",
             fontsize=10, color="#666")
ax.legend(loc="upper left", fontsize=10)
ax.grid(alpha=0.3)

# Per-pair bars
ax2 = axes[1]
pair_pnls_old = {}
pair_pnls_new = {}
for sym in INSTRUMENTS:
    pair_pnls_old[sym] = sum(t["pnl"] for t in old_trades if t["sym"] == sym)
    pair_pnls_new[sym] = sum(t["pnl"] for t in new_trades if t["sym"] == sym)
x = np.arange(len(INSTRUMENTS))
w = 0.4
ax2.bar(x - w/2, [pair_pnls_old[s] for s in INSTRUMENTS], w, color="#888", label="OLD")
ax2.bar(x + w/2, [pair_pnls_new[s] for s in INSTRUMENTS], w, color="#2196F3", label="NEW")
ax2.axhline(0, color="k", linewidth=0.5)
ax2.set_xticks(x)
ax2.set_xticklabels(INSTRUMENTS, rotation=0)
ax2.set_ylabel("Total pips per pair")
ax2.legend(loc="upper right")
ax2.grid(alpha=0.3)

fig.tight_layout()
out = os.path.join(CHART_DIR, "kz_hunt_freshness_compare.png")
fig.savefig(out, dpi=110)
print(f"\nChart: {out}")
