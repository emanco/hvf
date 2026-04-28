"""KZ Hunt: backtest comparison H1 vs M30 over 3-year window.

Three variants:
  A) H1 / freshness=1 (current production)
  B) M30 / freshness=1   (30-min confirmation window)
  C) M30 / freshness=2   (60-min confirmation window — same wall clock as H1)

Note: cooldowns/pause windows in BacktestEngine are bar-count-based (24, 48).
On M30 these are halved in wall-clock terms (12h, 24h). Acceptable for a
sanity check; could mismatch if M30 mean-frequency > H1.

Output: backtests/charts/kz_hunt_m30_compare.png
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
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]


def load_bars(symbol, tf):
    path = os.path.join(DATA_DIR, f"{symbol}_{tf}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
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
    all_trades = []
    for sym in INSTRUMENTS:
        t0 = time.time()
        df = load_bars(sym, tf)
        if df is None:
            print(f"  {sym}: no {tf} data", flush=True)
            continue
        # Constrain H1 to last 3 years for fair comparison with M30
        if tf == "H1":
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365 * 3)
            df = df[df["time"] >= cutoff].reset_index(drop=True)
        try:
            res = engine.run(df, sym)
            for t in res.trades:
                d = t.entry_time.date() if t.entry_time else df["time"].iloc[0].date()
                all_trades.append({"d": d, "pnl": t.pnl_pips, "sym": sym})
            wins = sum(1 for t in res.trades if t.pnl_pips > 0)
            tot = sum(t.pnl_pips for t in res.trades)
            elapsed = time.time() - t0
            print(f"  {sym}: {len(res.trades)} trades, "
                  f"WR={wins/max(1,len(res.trades))*100:.0f}%, "
                  f"PnL={tot:+.0f}p ({elapsed:.0f}s)", flush=True)
        except Exception as e:
            print(f"  {sym}: error {e}", flush=True)
    all_trades.sort(key=lambda t: t["d"])
    return all_trades


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
        "eq": eq, "dates": [t["d"] for t in trades], "trades": trades,
    }


# Run all 3
runs = [
    ("H1 / freshness=1", "H1", 1),
    ("M30 / freshness=1 (30min window)", "M30", 1),
    ("M30 / freshness=2 (60min window)", "M30", 2),
]
results = []
for label, tf, fresh in runs:
    trades = run(label, tf, fresh)
    s = stats(trades, label)
    if s:
        results.append(s)

print("\n" + "=" * 80)
print("SUMMARY (last 3 years, 8 pairs)")
print(f"{'Variant':<40} {'N':>5} {'WR':>5} {'PF':>5} {'Tot':>9} {'DD':>5}")
for s in results:
    print(f"{s['label']:<40} {s['n']:>5d} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
          f"{s['tot']:>+8.0f}p {s['dd']:>4.0f}p")
print("=" * 80)

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("KZ Hunt — H1 vs M30 backtest comparison (8 pairs, last 3 years)",
             fontsize=14, fontweight="bold")
ax = axes[0]
colors = ["#888", "#2196F3", "#FF6F00"]
for s, c in zip(results, colors):
    ax.plot(s["dates"], s["eq"], color=c, linewidth=1.6,
            label=f"{s['label']}  n={s['n']} WR={s['wr']:.0f}% "
                  f"PF={s['pf']:.2f} Tot={s['tot']:+.0f}p DD={s['dd']:.0f}p")
ax.axhline(0, color="k", linewidth=0.5)
ax.set_ylabel("Cumulative pips")
ax.legend(loc="upper left", fontsize=10)
ax.grid(alpha=0.3)

# Per-pair
ax2 = axes[1]
x = np.arange(len(INSTRUMENTS))
w = 0.27
for i, (s, c) in enumerate(zip(results, colors)):
    pair_pnls = {sym: sum(t["pnl"] for t in s["trades"] if t["sym"] == sym)
                 for sym in INSTRUMENTS}
    ax2.bar(x + (i - 1) * w, [pair_pnls[sym] for sym in INSTRUMENTS], w,
            color=c, label=s["label"].split(" / ")[0] + "/" + s["label"].split("=")[-1].split(" ")[0])
ax2.axhline(0, color="k", linewidth=0.5)
ax2.set_xticks(x)
ax2.set_xticklabels(INSTRUMENTS)
ax2.set_ylabel("Total pips per pair")
ax2.legend(loc="upper right", fontsize=8)
ax2.grid(alpha=0.3)

fig.tight_layout()
out = os.path.join(CHART_DIR, "kz_hunt_m30_compare.png")
fig.savefig(out, dpi=110)
print(f"\nChart: {out}")
