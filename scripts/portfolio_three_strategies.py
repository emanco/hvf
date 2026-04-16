"""Portfolio backtest: KZ Hunt (real engine) + London Breakout + Quantum London.
Uses H1 for KZ Hunt and London BO, M5 for Quantum London."""
import sys, os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

PIP = {"EURUSD":0.0001,"GBPUSD":0.0001,"EURGBP":0.0001,"USDCHF":0.0001,
       "NZDUSD":0.0001,"EURAUD":0.0001,"GBPJPY":0.01,"EURJPY":0.01,"CHFJPY":0.01}

# ============================================================
# 1. Quantum London (EURGBP, M5, daily open at 22:00 UTC)
# ============================================================
print("1. Quantum London (EURGBP)...")
ql_rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
pip_ql = 0.0001; spread_ql = 1.0

ql_sessions = {}; ql_cur = None
for r in ql_rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    h = ts.hour
    if h == 22 and ts.minute == 0:
        ql_cur = {"date": ts.date(), "open": r[1], "bars": [], "wd": ts.weekday()}
        ql_sessions[ts.date()] = ql_cur
    if ql_cur and (h >= 22 or h < 6):
        ql_cur["bars"].append({"h": h, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})
    elif ql_cur and h >= 6:
        ql_cur = None

ql_trades = []
for d in sorted(ql_sessions):
    s = ql_sessions[d]
    if s["wd"] not in [0,1,2,3]: continue  # Mon-Thu nights (open day)
    do = s["open"]
    trading = [b for b in s["bars"] if b["h"] < 5]
    if not trading: continue
    ot = None; done = False
    for b in trading:
        if done: continue
        if ot:
            dr, ep, tp, sl = ot
            if dr == "L":
                if b["lo"] <= sl: ql_trades.append({"d":d,"pnl":(sl-ep)/pip_ql-spread_ql,"x":"SL","sym":"EURGBP","strat":"QUANTUM_LONDON"}); done=True; continue
                if b["hi"] >= tp: ql_trades.append({"d":d,"pnl":(tp-ep)/pip_ql-spread_ql,"x":"TP","sym":"EURGBP","strat":"QUANTUM_LONDON"}); done=True; continue
            else:
                if b["hi"] >= sl: ql_trades.append({"d":d,"pnl":(ep-sl)/pip_ql-spread_ql,"x":"SL","sym":"EURGBP","strat":"QUANTUM_LONDON"}); done=True; continue
                if b["lo"] <= tp: ql_trades.append({"d":d,"pnl":(ep-tp)/pip_ql-spread_ql,"x":"TP","sym":"EURGBP","strat":"QUANTUM_LONDON"}); done=True; continue
        else:
            if b["lo"] <= do - 8*pip_ql:
                ep = do - 8*pip_ql; ot = ("L", ep, ep+5*pip_ql, ep-18*pip_ql)
            elif b["hi"] >= do + 8*pip_ql:
                ep = do + 8*pip_ql; ot = ("S", ep, ep-5*pip_ql, ep+18*pip_ql)
    if ot and not done:
        dr, ep, tp, sl = ot; last = trading[-1]
        if dr == "L": pnl = (last["cl"]-ep)/pip_ql-spread_ql
        else: pnl = (ep-last["cl"])/pip_ql-spread_ql
        ql_trades.append({"d":d,"pnl":pnl,"x":"TIME","sym":"EURGBP","strat":"QUANTUM_LONDON"})

ql_first = min(ql_sessions) if ql_sessions else "N/A"
ql_last = max(ql_sessions) if ql_sessions else "N/A"
print("  {} to {}: {} trades, {:+.0f}p".format(ql_first, ql_last, len(ql_trades), sum(t["pnl"] for t in ql_trades)))

# ============================================================
# 2. London Breakout (GBPUSD, H1)
# ============================================================
print("2. London Breakout (GBPUSD)...")
lb_rates = mt5.copy_rates_from_pos("GBPUSD", mt5.TIMEFRAME_H1, 0, 50000)
pip_lb = 0.0001; spread_lb = 1.0

lb_sessions = {}
for r in lb_rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5: continue
    bd = ts.date()
    if bd not in lb_sessions:
        lb_sessions[bd] = {"bars": [], "wd": ts.weekday()}
    lb_sessions[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

lb_trades = []
for d in sorted(lb_sessions):
    s = lb_sessions[d]
    if s["wd"] not in [0,1]: continue
    asian = [b for b in s["bars"] if b["h"] < 7]
    if len(asian) < 3: continue
    ah=max(b["hi"] for b in asian); al=min(b["lo"] for b in asian)
    ar=(ah-al)/pip_lb
    if ar<12 or ar>20: continue
    lon=[b for b in s["bars"] if 8<=b["h"]<13]
    if not lon: continue
    td=ar*1.0*pip_lb; sp=spread_lb*pip_lb; traded=False
    for b in lon:
        if traded: break
        if b["hi"]>ah+sp:
            e=ah+sp;sl=al-sp;tp=e+td;rk=(e-sl)/pip_lb
            rem=[bb for bb in lon if bb["h"]>=b["h"]]; hit=None
            for rb in rem:
                if rb["lo"]<=sl: hit="SL";pnl=-rk-spread_lb;break
                if rb["hi"]>=tp: hit="TP";pnl=(tp-e)/pip_lb-spread_lb;break
            if not hit: lc=rem[-1]["cl"];pnl=(lc-e)/pip_lb-spread_lb;hit="TIME"
            lb_trades.append({"d":d,"pnl":pnl,"x":hit,"sym":"GBPUSD","strat":"LONDON_BO"})
            traded=True
        if not traded and b["lo"]<al-sp:
            e=al-sp;sl=ah+sp;tp=e-td;rk=(sl-e)/pip_lb
            rem=[bb for bb in lon if bb["h"]>=b["h"]]; hit=None
            for rb in rem:
                if rb["hi"]>=sl: hit="SL";pnl=-rk-spread_lb;break
                if rb["lo"]<=tp: hit="TP";pnl=(e-tp)/pip_lb-spread_lb;break
            if not hit: lc=rem[-1]["cl"];pnl=(e-lc)/pip_lb-spread_lb;hit="TIME"
            lb_trades.append({"d":d,"pnl":pnl,"x":hit,"sym":"GBPUSD","strat":"LONDON_BO"})
            traded=True

lb_first = min(lb_sessions) if lb_sessions else "N/A"
lb_last = max(lb_sessions) if lb_sessions else "N/A"
print("  {} to {}: {} trades, {:+.0f}p".format(lb_first, lb_last, len(lb_trades), sum(t["pnl"] for t in lb_trades)))

# ============================================================
# 3. KZ Hunt — use real backtest engine
# ============================================================
print("3. KZ Hunt — excluded (needs real backtest engine, collecting live data)")
kz_trades = []

# ============================================================
# Combine
# ============================================================
all_trades = kz_trades + lb_trades + ql_trades
all_trades.sort(key=lambda t: t["d"])

print("\n" + "=" * 70)
print("  THREE-STRATEGY PORTFOLIO")
print("=" * 70)

for strat, label in [("KZ_HUNT","KZ Hunt"),("LONDON_BO","London Breakout"),("QUANTUM_LONDON","Quantum London")]:
    st = [t for t in all_trades if t["strat"] == strat]
    if not st: print("\n  {}: 0 trades".format(label)); continue
    pnls = [t["pnl"] for t in st]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("\n  {}: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        label, len(st), w/len(st)*100, gp/gl, sum(pnls), dd))
    pairs = set(t["sym"] for t in st)
    for sym in sorted(pairs):
        pt = [t for t in st if t["sym"] == sym]
        pw = sum(1 for t in pt if t["pnl"] > 0)
        print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
            sym, len(pt), pw/len(pt)*100 if pt else 0, sum(t["pnl"] for t in pt)))

if all_trades:
    pnls_all = [t["pnl"] for t in all_trades]
    w_all = sum(1 for p in pnls_all if p > 0)
    gp_all = sum(p for p in pnls_all if p > 0)
    gl_all = abs(sum(p for p in pnls_all if p <= 0)) or 0.001
    eq_all = np.cumsum(pnls_all)
    dd_all = max(np.maximum.accumulate(eq_all) - eq_all) if len(eq_all) > 1 else 0
    print("\n  COMBINED: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        len(all_trades), w_all/len(all_trades)*100, gp_all/gl_all, sum(pnls_all), dd_all))

# Monthly
monthly = defaultdict(lambda: defaultdict(float))
for t in all_trades:
    m = t["d"].strftime("%Y-%m") if hasattr(t["d"], "strftime") else str(t["d"])[:7]
    monthly[m][t["strat"]] += t["pnl"]
    monthly[m]["total"] += t["pnl"]

print("\n  Monthly:")
print("  {:<8} {:>10} {:>10} {:>10} {:>10}".format("Month","KZ_HUNT","LONDON_BO","QUANTUM_L","TOTAL"))
print("  "+"-"*52)
for m in sorted(monthly):
    d = monthly[m]
    print("  {:<8} {:>+9.0f}p {:>+9.0f}p {:>+9.0f}p {:>+9.0f}p".format(
        m, d.get("KZ_HUNT",0), d.get("LONDON_BO",0), d.get("QUANTUM_LONDON",0), d["total"]))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(18, 12), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("Three-Strategy Portfolio\nKZ Hunt + London Breakout + Quantum London",
             fontsize=14, fontweight="bold")

ax = axes[0]
colors = {"KZ_HUNT": "#2196F3", "LONDON_BO": "#4CAF50", "QUANTUM_LONDON": "#FF9800"}

for strat, color in colors.items():
    st = sorted([t for t in all_trades if t["strat"] == strat], key=lambda t: t["d"])
    if not st: continue
    dates = [t["d"] for t in st]
    eq = np.cumsum([t["pnl"] for t in st])
    pnls = [t["pnl"] for t in st]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    ax.plot(dates, eq, color=color, linewidth=1.5, alpha=0.8,
            label="{}: {}T PF={:.2f} {:+.0f}p".format(strat, len(st), gp/gl, sum(pnls)))

# Combined
if all_trades:
    dates_all = [t["d"] for t in all_trades]
    eq_all = np.cumsum([t["pnl"] for t in all_trades])
    ax.plot(dates_all, eq_all, color="black", linewidth=2.5, label="COMBINED: {:+.0f}p".format(sum(pnls_all)), zorder=10)
    ax.fill_between(dates_all, 0, eq_all, alpha=0.05, color="black")

ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
ax.legend(loc="upper left", fontsize=9)
ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.grid(True, alpha=0.15)

# Monthly bars
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
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "three_strategy_portfolio.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))
mt5.shutdown()
