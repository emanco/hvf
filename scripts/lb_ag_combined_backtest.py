"""London Breakout + Asian Gravity only — combined backtest with chart."""
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

pip_gbp = 0.0001
pip_eur = 0.0001

# ---- London Breakout (GBPUSD, full H1 history) ----
print("London Breakout (GBPUSD)...")
rates_lb = mt5.copy_rates_from_pos("GBPUSD", mt5.TIMEFRAME_H1, 0, 50000)
first_lb = datetime.fromtimestamp(rates_lb[0][0], tz=timezone.utc).date()
last_lb = datetime.fromtimestamp(rates_lb[-1][0], tz=timezone.utc).date()

sessions_lb = {}
for r in rates_lb:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5: continue
    bd = ts.date()
    if bd not in sessions_lb:
        sessions_lb[bd] = {"bars": [], "wd": ts.weekday()}
    sessions_lb[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

LB_DAYS=[0,1]; LB_MIN=12; LB_MAX=20; LB_TP=1.0; LB_EX=13; LB_SP=1.0

lb_trades = []
for d in sorted(sessions_lb):
    s = sessions_lb[d]
    if s["wd"] not in LB_DAYS: continue
    asian = [b for b in s["bars"] if b["h"] < 7]
    if len(asian) < 3: continue
    ah=max(b["hi"] for b in asian); al=min(b["lo"] for b in asian)
    ar=(ah-al)/pip_gbp
    if ar<LB_MIN or ar>LB_MAX: continue
    lon=[b for b in s["bars"] if 8<=b["h"]<LB_EX]
    if not lon: continue
    td=ar*LB_TP*pip_gbp; sp=LB_SP*pip_gbp; traded=False
    for b in lon:
        if traded: break
        if b["hi"]>ah+sp:
            e=ah+sp;sl=al-sp;tp=e+td;rk=(e-sl)/pip_gbp
            rem=[bb for bb in lon if bb["h"]>=b["h"]]; hit=None
            for rb in rem:
                if rb["lo"]<=sl: hit="SL";pnl=-rk-LB_SP;break
                if rb["hi"]>=tp: hit="TP";pnl=(tp-e)/pip_gbp-LB_SP;break
            if not hit: lc=rem[-1]["cl"];pnl=(lc-e)/pip_gbp-LB_SP;hit="TIME"
            lb_trades.append({"d":d,"pnl":pnl,"x":hit,"sym":"GBPUSD","strat":"LONDON_BO","dir":"LONG"})
            traded=True
        if not traded and b["lo"]<al-sp:
            e=al-sp;sl=ah+sp;tp=e-td;rk=(sl-e)/pip_gbp
            rem=[bb for bb in lon if bb["h"]>=b["h"]]; hit=None
            for rb in rem:
                if rb["hi"]>=sl: hit="SL";pnl=-rk-LB_SP;break
                if rb["lo"]<=tp: hit="TP";pnl=(e-tp)/pip_gbp-LB_SP;break
            if not hit: lc=rem[-1]["cl"];pnl=(e-lc)/pip_gbp-LB_SP;hit="TIME"
            lb_trades.append({"d":d,"pnl":pnl,"x":hit,"sym":"GBPUSD","strat":"LONDON_BO","dir":"SHORT"})
            traded=True

print("  {} to {}: {} trades, {:+.0f}p".format(first_lb, last_lb, len(lb_trades), sum(t["pnl"] for t in lb_trades)))

# ---- Asian Gravity (EURGBP, M5 history) ----
print("Asian Gravity (EURGBP Thursday SHORT)...")
ag_rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
AG_TRIGGER=5;AG_TARGET=2;AG_STOP=8;AG_MAX_RNG=20;AG_SP=1.0

if ag_rates is not None and len(ag_rates) > 0:
    first_ag = datetime.fromtimestamp(ag_rates[0][0], tz=timezone.utc).date()
    last_ag = datetime.fromtimestamp(ag_rates[-1][0], tz=timezone.utc).date()

    ag_sessions = {}
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
            s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip_eur
        else:
            s["range"] = 999

    ag_trades = []
    for d in sorted(ag_sessions):
        s = ag_sessions[d]
        if s["wd"] != 3 or s["range"] > AG_MAX_RNG or s["range"] < 1: continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot=None; done=False
        for b in trading:
            if done: continue
            if ot:
                ep,tp,sl_p=ot
                if b["hi"]>=sl_p: ag_trades.append({"d":d,"pnl":(ep-sl_p)/pip_eur-AG_SP,"x":"SL","sym":"EURGBP","strat":"ASIAN_GRAVITY","dir":"SHORT"}); done=True; continue
                if b["lo"]<=tp: ag_trades.append({"d":d,"pnl":(ep-tp)/pip_eur-AG_SP,"x":"TP","sym":"EURGBP","strat":"ASIAN_GRAVITY","dir":"SHORT"}); done=True; continue
            else:
                if b["hi"]>=so+AG_TRIGGER*pip_eur:
                    ep=so+AG_TRIGGER*pip_eur; ot=(ep,ep-AG_TARGET*pip_eur,ep+AG_STOP*pip_eur)
        if ot and not done:
            last=trading[-1] if trading else s["bars"][-1]
            ag_trades.append({"d":d,"pnl":(ot[0]-last["cl"])/pip_eur-AG_SP,"x":"TIME","sym":"EURGBP","strat":"ASIAN_GRAVITY","dir":"SHORT"})

    print("  {} to {}: {} trades, {:+.0f}p".format(first_ag, last_ag, len(ag_trades), sum(t["pnl"] for t in ag_trades)))
else:
    ag_trades = []
    first_ag = last_ag = "N/A"
    print("  No M5 data")

# ---- Combine ----
all_trades = lb_trades + ag_trades
all_trades.sort(key=lambda t: t["d"])

print("\n" + "=" * 70)
print("  London Breakout + Asian Gravity Combined")
print("=" * 70)

for strat, label in [("LONDON_BO", "London Breakout"), ("ASIAN_GRAVITY", "Asian Gravity")]:
    st = [t for t in all_trades if t["strat"] == strat]
    if not st: continue
    pnls = [t["pnl"] for t in st]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("\n  {}: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        label, len(st), w/len(st)*100, gp/gl, sum(pnls), dd))

    # Yearly
    yearly = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0})
    for t in st:
        yr = t["d"].year
        yearly[yr]["n"] += 1; yearly[yr]["pnl"] += t["pnl"]
        if t["pnl"] > 0: yearly[yr]["w"] += 1
    for yr in sorted(yearly):
        y = yearly[yr]
        print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
            yr, y["n"], y["w"]/y["n"]*100 if y["n"] else 0, y["pnl"]))

    # Sizing
    pip_usd = 10.0 if strat == "LONDON_BO" else 12.7
    for risk in [1.0, 2.0]:
        avg_loss = abs(np.mean([p for p in pnls if p < 0])) if [p for p in pnls if p < 0] else 15
        lots = (10000 * risk / 100) / (avg_loss * pip_usd)
        t_usd = sum(pnls) * lots * pip_usd
        d_usd = dd * lots * pip_usd
        print("    {}% risk ($10k): ${:+,.0f} total, DD ${:,.0f}".format(risk, t_usd, d_usd))

# Combined
if all_trades:
    pnls = [t["pnl"] for t in all_trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("\n  COMBINED: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        len(all_trades), w/len(all_trades)*100, gp/gl, sum(pnls), dd))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(16, 12), gridspec_kw={"height_ratios": [2, 1]})
fig.suptitle("London Breakout + Asian Gravity — Portfolio Performance",
             fontsize=14, fontweight="bold")

ax = axes[0]

# London Breakout equity
lb_sorted = sorted(lb_trades, key=lambda t: t["d"])
if lb_sorted:
    lb_dates = [t["d"] for t in lb_sorted]
    lb_eq = np.cumsum([t["pnl"] for t in lb_sorted])
    lb_pnls = [t["pnl"] for t in lb_sorted]
    lb_w = sum(1 for p in lb_pnls if p > 0)
    lb_gp = sum(p for p in lb_pnls if p > 0)
    lb_gl = abs(sum(p for p in lb_pnls if p <= 0)) or 0.001
    ax.plot(lb_dates, lb_eq, color="#4CAF50", linewidth=2, label="London BO: {}T PF={:.2f} {:+.0f}p".format(
        len(lb_sorted), lb_gp/lb_gl, sum(lb_pnls)))
    ax.fill_between(lb_dates, 0, lb_eq, alpha=0.08, color="#4CAF50")
    for j, t in enumerate(lb_sorted):
        if t["x"] == "TP": c = "#4CAF50"
        elif t["x"] == "SL": c = "#F44336"
        else: c = "#FFC107"
        ax.scatter(lb_dates[j], lb_eq[j], color=c, s=12, zorder=5)

# Asian Gravity equity
ag_sorted = sorted(ag_trades, key=lambda t: t["d"])
if ag_sorted:
    ag_dates = [t["d"] for t in ag_sorted]
    ag_eq = np.cumsum([t["pnl"] for t in ag_sorted])
    ag_pnls = [t["pnl"] for t in ag_sorted]
    ag_w = sum(1 for p in ag_pnls if p > 0)
    ag_gp = sum(p for p in ag_pnls if p > 0)
    ag_gl = abs(sum(p for p in ag_pnls if p <= 0)) or 0.001
    ax.plot(ag_dates, ag_eq, color="#FF9800", linewidth=2, label="Asian Gravity: {}T PF={:.2f} {:+.0f}p".format(
        len(ag_sorted), ag_gp/ag_gl, sum(ag_pnls)))
    ax.fill_between(ag_dates, 0, ag_eq, alpha=0.08, color="#FF9800")
    for j, t in enumerate(ag_sorted):
        if t["x"] == "TP": c = "#4CAF50"
        elif t["x"] == "SL": c = "#F44336"
        else: c = "#FFC107"
        ax.scatter(ag_dates[j], ag_eq[j], color=c, s=12, zorder=5)

ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
ax.legend(loc="upper left", fontsize=10)
ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.grid(True, alpha=0.15)
ax.set_title("Equity Curves by Strategy", fontsize=11)

# Bottom: trade-by-trade for each
ax2 = axes[1]
if lb_sorted:
    ax2.bar(range(len(lb_sorted)), [t["pnl"] for t in lb_sorted],
            color=["#4CAF50" if t["pnl"] > 0 else "#F44336" for t in lb_sorted],
            alpha=0.7, label="London BO")
offset = len(lb_sorted)
if ag_sorted:
    ax2.bar(range(offset, offset + len(ag_sorted)), [t["pnl"] for t in ag_sorted],
            color=["#FF9800" if t["pnl"] > 0 else "#E65100" for t in ag_sorted],
            alpha=0.7, label="Asian Gravity")
ax2.axhline(y=0, color="gray", linewidth=0.5)
ax2.set_ylabel("Per-trade P&L (pips)", fontsize=9)
ax2.set_xlabel("Trade #", fontsize=9)
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.15)
ax2.set_title("Individual Trades", fontsize=11)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "lb_ag_combined.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
