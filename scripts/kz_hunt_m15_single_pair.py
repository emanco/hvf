"""KZ Hunt: 1-year EURUSD comparison across H1, M30, M15.

Curiosity test only — production stays on M30.

Variants:
  A) H1 / freshness=1
  B) M30 / freshness=2 (60min wall-clock)
  C) M15 / freshness=4 (60min wall-clock)

Output: backtests/charts/kz_hunt_m15_single_pair.png
"""
import sys, os, time
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
SYMBOL = "EURUSD"


def load_bars(tf):
    path = os.path.join(DATA_DIR, f"{SYMBOL}_{tf}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # Constrain to last 1 year
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)
    df = df[df["time"] >= cutoff].reset_index(drop=True)
    df = add_indicators(df)
    if "tick_volume" in df.columns:
        df["volume"] = df["tick_volume"]
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    return df


def run(label, tf, freshness):
    config.PATTERN_FRESHNESS_BARS["KZ_HUNT"] = freshness
    config.INVALIDATION_ENABLED_BY_PATTERN["KZ_HUNT"] = False
    engine = BacktestEngine(
        starting_equity=10000.0,
        enabled_patterns=["KZ_HUNT"],
        simulate_news_blocks=True,
        simulate_circuit_breaker=True,
    )
    print(f"\n=== {label} ({tf}, freshness={freshness}) ===", flush=True)
    df = load_bars(tf)
    if df is None:
        print(f"  No {tf} data", flush=True)
        return []
    print(f"  {len(df)} bars, {df['time'].iloc[0].date()} to {df['time'].iloc[-1].date()}",
          flush=True)
    t0 = time.time()
    res = engine.run(df, SYMBOL)
    elapsed = time.time() - t0
    trades = []
    for t in res.trades:
        d = t.entry_time.date() if t.entry_time else df["time"].iloc[0].date()
        trades.append({"d": d, "pnl": t.pnl_pips, "x": t.exit_reason})
    wins = sum(1 for t in trades if t["pnl"] > 0)
    print(f"  {len(trades)} trades, WR={wins/max(1,len(trades))*100:.0f}%, "
          f"Tot={sum(t['pnl'] for t in trades):+.0f}p ({elapsed:.0f}s)", flush=True)
    return trades


def stats(trades, label):
    if not trades:
        return None
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    return {
        "label": label, "n": len(trades), "wr": w / len(trades) * 100,
        "pf": gp / gl, "tot": sum(pnls), "dd": dd,
        "eq": eq, "dates": [t["d"] for t in sorted(trades, key=lambda x: x["d"])],
    }


variants = [
    ("H1 / fresh=1", "H1", 1),
    ("M30 / fresh=2", "M30", 2),
    ("M15 / fresh=4", "M15", 4),
]

results = []
for label, tf, fresh in variants:
    trades = run(label, tf, fresh)
    s = stats(sorted(trades, key=lambda x: x["d"]), label)
    if s:
        results.append(s)

print("\n" + "=" * 80)
print(f"SUMMARY — {SYMBOL}, last 1 year")
print(f"{'Variant':<22} {'N':>5} {'WR':>5} {'PF':>5} {'Tot':>8} {'DD':>5}")
for s in results:
    print(f"{s['label']:<22} {s['n']:>5d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
          f"{s['tot']:>+7.0f}p {s['dd']:>4.0f}p")
print("=" * 80)

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(14, 7))
fig.suptitle(f"KZ Hunt — Timeframe comparison on {SYMBOL} (1 year)",
             fontsize=13, fontweight="bold")
colors = ["#888", "#2196F3", "#FF6F00"]
for s, c in zip(results, colors):
    ax.plot(s["dates"], s["eq"], color=c, linewidth=1.6,
            label=f"{s['label']}  n={s['n']} WR={s['wr']:.0f}% "
                  f"PF={s['pf']:.2f} Tot={s['tot']:+.0f}p DD={s['dd']:.0f}p")
ax.axhline(0, color="k", linewidth=0.5)
ax.set_ylabel("Cumulative pips")
ax.legend(loc="upper left", fontsize=10)
ax.grid(alpha=0.3)

fig.tight_layout()
out = os.path.join(CHART_DIR, "kz_hunt_m15_single_pair.png")
fig.savefig(out, dpi=110)
print(f"\nChart: {out}")
