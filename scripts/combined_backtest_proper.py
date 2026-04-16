"""
Combined portfolio backtest using the REAL KZ Hunt backtest engine.
Runs KZ Hunt through the actual detector/scorer, then combines
with London Breakout and Asian Gravity results.
"""
import sys, os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import numpy as np

# Ensure hvf_trader is importable
parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent)

import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(parent, ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader.data.data_fetcher import fetch_and_prepare
from hvf_trader import config

PIP_VALUES = config.PIP_VALUES
cutoff = datetime.now(timezone.utc) - timedelta(days=365)
cutoff_date = cutoff.date()

print("Running proper combined backtest (1 year)")
print("=" * 70)

# ============================================================
# 1. KZ Hunt — use the REAL backtest engine
# ============================================================
print("\n1. KZ Hunt (real engine, {} pairs)...".format(len(config.INSTRUMENTS)))

engine = BacktestEngine()
kz_trades = []

for symbol in config.INSTRUMENTS:
    df_1h = fetch_and_prepare(symbol, "H1", bars=10000)
    if df_1h is None or df_1h.empty:
        print("  {}: no data".format(symbol))
        continue

    # Filter to last year
    df_1h = df_1h[df_1h.index >= cutoff]
    if len(df_1h) < 250:
        print("  {}: insufficient data ({} bars)".format(symbol, len(df_1h)))
        continue

    results = engine.run(df_1h, symbol)
    for t in results.get("trades", []):
        kz_trades.append({
            "d": t.get("entry_date", cutoff_date),
            "pnl": t.get("pnl_pips", 0),
            "x": t.get("exit_reason", ""),
            "sym": symbol,
            "strat": "KZ_HUNT",
            "dir": t.get("direction", ""),
        })
    print("  {}: {} trades, PnL={:+.0f}p".format(
        symbol, len(results.get("trades", [])),
        sum(t.get("pnl_pips", 0) for t in results.get("trades", []))))

print("  Total KZ Hunt: {} trades".format(len(kz_trades)))

# ============================================================
# 2. London Breakout (same as before — accurate on H1)
# ============================================================
print("\n2. London Breakout (GBPUSD)...")

LB_DAYS = [0, 1]; LB_MIN = 12; LB_MAX = 20; LB_TP = 1.0; LB_EX = 13; LB_SP = 1.0

rates = mt5.copy_rates_from_pos("GBPUSD", mt5.TIMEFRAME_H1, 0, 50000)
pip = 0.0001
sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5: continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"bars": [], "wd": ts.weekday()}
    sessions[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

lb_trades = []
for d in sorted(sessions):
    if d < cutoff_date: continue
    s = sessions[d]
    if s["wd"] not in LB_DAYS: continue
    asian = [b for b in s["bars"] if b["h"] < 7]
    if len(asian) < 3: continue
    ah = max(b["hi"] for b in asian); al = min(b["lo"] for b in asian)
    ar = (ah - al) / pip
    if ar < LB_MIN or ar > LB_MAX: continue
    lon = [b for b in s["bars"] if 8 <= b["h"] < LB_EX]
    if not lon: continue
    td = ar * LB_TP * pip; sp = LB_SP * pip; traded = False
    for b in lon:
        if traded: break
        if b["hi"] > ah + sp:
            e=ah+sp; sl=al-sp; tp=e+td; rk=(e-sl)/pip
            rem=[bb for bb in lon if bb["h"]>=b["h"]]; hit=None
            for rb in rem:
                if rb["lo"]<=sl: hit="SL"; pnl=-rk-LB_SP; break
                if rb["hi"]>=tp: hit="TP"; pnl=(tp-e)/pip-LB_SP; break
            if not hit: lc=rem[-1]["cl"]; pnl=(lc-e)/pip-LB_SP; hit="TIME"
            lb_trades.append({"d":d,"pnl":pnl,"x":hit,"sym":"GBPUSD","strat":"LONDON_BO","dir":"LONG"})
            traded=True
        if not traded and b["lo"]<al-sp:
            e=al-sp; sl=ah+sp; tp=e-td; rk=(sl-e)/pip
            rem=[bb for bb in lon if bb["h"]>=b["h"]]; hit=None
            for rb in rem:
                if rb["hi"]>=sl: hit="SL"; pnl=-rk-LB_SP; break
                if rb["lo"]<=tp: hit="TP"; pnl=(e-tp)/pip-LB_SP; break
            if not hit: lc=rem[-1]["cl"]; pnl=(e-lc)/pip-LB_SP; hit="TIME"
            lb_trades.append({"d":d,"pnl":pnl,"x":hit,"sym":"GBPUSD","strat":"LONDON_BO","dir":"SHORT"})
            traded=True

print("  {} trades, PnL={:+.0f}p".format(len(lb_trades), sum(t["pnl"] for t in lb_trades)))

# ============================================================
# 3. Asian Gravity (same as before)
# ============================================================
print("\n3. Asian Gravity (EURGBP Thursday SHORT)...")

AG_TRIGGER=5; AG_TARGET=2; AG_STOP=8; AG_MAX_RNG=20; AG_SP=1.0
ag_rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
ag_pip = 0.0001

ag_sessions = {}
if ag_rates is not None:
    for r in ag_rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        if ts.weekday() >= 5 or ts.hour >= 6: continue
        bd = ts.date()
        if bd not in ag_sessions:
            ag_sessions[bd] = {"wd": ts.weekday(), "bars": []}
        ag_sessions[bd]["bars"].append({"h":ts.hour,"m":ts.minute,"o":r[1],"hi":r[2],"lo":r[3],"cl":r[4]})

for s in ag_sessions.values():
    form = [b for b in s["bars"] if b["h"] < 2]
    if form:
        s["open"] = s["bars"][0]["o"]
        s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / ag_pip
    else:
        s["range"] = 999

ag_trades = []
for d in sorted(ag_sessions):
    if d < cutoff_date: continue
    s = ag_sessions[d]
    if s["wd"] != 3 or s["range"] > AG_MAX_RNG or s["range"] < 1: continue
    so = s["open"]
    trading = [b for b in s["bars"] if b["h"] >= 2]
    ot=None; done=False
    for b in trading:
        if done: continue
        if ot:
            ep,tp,sl_p=ot
            if b["hi"]>=sl_p: ag_trades.append({"d":d,"pnl":(ep-sl_p)/ag_pip-AG_SP,"x":"SL","sym":"EURGBP","strat":"ASIAN_GRAVITY","dir":"SHORT"}); done=True; continue
            if b["lo"]<=tp: ag_trades.append({"d":d,"pnl":(ep-tp)/ag_pip-AG_SP,"x":"TP","sym":"EURGBP","strat":"ASIAN_GRAVITY","dir":"SHORT"}); done=True; continue
        else:
            if b["hi"]>=so+AG_TRIGGER*ag_pip:
                ep=so+AG_TRIGGER*ag_pip; ot=(ep,ep-AG_TARGET*ag_pip,ep+AG_STOP*ag_pip)
    if ot and not done:
        last=trading[-1] if trading else s["bars"][-1]
        ag_trades.append({"d":d,"pnl":(ot[0]-last["cl"])/ag_pip-AG_SP,"x":"TIME","sym":"EURGBP","strat":"ASIAN_GRAVITY","dir":"SHORT"})

print("  {} trades, PnL={:+.0f}p".format(len(ag_trades), sum(t["pnl"] for t in ag_trades)))

# ============================================================
# Combine and report
# ============================================================
all_trades = kz_trades + lb_trades + ag_trades
all_trades.sort(key=lambda t: t["d"])

print("\n" + "=" * 70)
print("  COMBINED PORTFOLIO (1 Year, Real KZ Hunt Engine)")
print("=" * 70)

for strat in ["KZ_HUNT", "LONDON_BO", "ASIAN_GRAVITY"]:
    st = [t for t in all_trades if t["strat"] == strat]
    if not st:
        print("\n  {}: 0 trades".format(strat)); continue
    pnls = [t["pnl"] for t in st]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    print("\n  {}: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p".format(
        strat, len(st), w/len(st)*100, gp/gl, sum(pnls)))
    pairs = set(t["sym"] for t in st)
    for sym in sorted(pairs):
        pt = [t for t in st if t["sym"] == sym]
        pw = sum(1 for t in pt if t["pnl"] > 0)
        print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
            sym, len(pt), pw/len(pt)*100 if pt else 0, sum(t["pnl"] for t in pt)))

if all_trades:
    pnls = [t["pnl"] for t in all_trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("\n  COMBINED: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        len(all_trades), w/len(all_trades)*100, gp/gl, sum(pnls), dd))

# Monthly
monthly = defaultdict(lambda: defaultdict(float))
for t in all_trades:
    m = t["d"].strftime("%Y-%m") if hasattr(t["d"], "strftime") else str(t["d"])[:7]
    monthly[m][t["strat"]] += t["pnl"]
    monthly[m]["total"] += t["pnl"]

print("\n  Monthly:")
print("  {:<8} {:>10} {:>10} {:>10} {:>10}".format("Month","KZ_HUNT","LONDON_BO","ASIAN_GRV","TOTAL"))
print("  "+"-"*52)
for m in sorted(monthly):
    d = monthly[m]
    print("  {:<8} {:>+9.0f}p {:>+9.0f}p {:>+9.0f}p {:>+9.0f}p".format(
        m, d.get("KZ_HUNT",0), d.get("LONDON_BO",0), d.get("ASIAN_GRAVITY",0), d["total"]))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(16, 12), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("Combined Portfolio (Real KZ Hunt Engine) - 1 Year", fontsize=14, fontweight="bold")

ax = axes[0]
colors = {"KZ_HUNT": "#2196F3", "LONDON_BO": "#4CAF50", "ASIAN_GRAVITY": "#FF9800"}
for strat, color in colors.items():
    st = sorted([t for t in all_trades if t["strat"] == strat], key=lambda t: t["d"])
    if not st: continue
    dates = [t["d"] for t in st]
    eq = np.cumsum([t["pnl"] for t in st])
    ax.plot(dates, eq, color=color, linewidth=1.5, label=strat, alpha=0.8)

dates_all = [t["d"] for t in all_trades]
eq_all = np.cumsum([t["pnl"] for t in all_trades])
ax.plot(dates_all, eq_all, color="black", linewidth=2.5, label="COMBINED", zorder=10)
ax.fill_between(dates_all, 0, eq_all, alpha=0.05, color="black")
ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

if all_trades:
    pnls_all = [t["pnl"] for t in all_trades]
    w_all = sum(1 for p in pnls_all if p > 0)
    gp_all = sum(p for p in pnls_all if p > 0)
    gl_all = abs(sum(p for p in pnls_all if p <= 0)) or 0.001
    ax.text(0.02, 0.95,
        "Combined: {}T  WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
            len(all_trades), w_all/len(all_trades)*100, gp_all/gl_all, sum(pnls_all), dd),
        transform=ax.transAxes, fontsize=10, va="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))

ax.legend(loc="upper left", fontsize=9)
ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.grid(True, alpha=0.15)

ax2 = axes[1]
months = sorted(monthly.keys())
x = np.arange(len(months))
w_bar = 0.25
for i, (strat, color) in enumerate(colors.items()):
    vals = [monthly[m].get(strat, 0) for m in months]
    ax2.bar(x + i * w_bar, vals, w_bar, label=strat, color=color, alpha=0.8)
ax2.set_xticks(x + w_bar)
ax2.set_xticklabels(months, fontsize=8, rotation=45)
ax2.set_ylabel("Monthly P&L (pips)", fontsize=9)
ax2.axhline(y=0, color="gray", linewidth=0.5)
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(parent, "backtests", "charts", "combined_portfolio_proper.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
