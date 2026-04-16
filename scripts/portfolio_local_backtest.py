"""Three-strategy portfolio backtest — runs locally from CSV data."""
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests", "data")
CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests", "charts")

PIP = {"EURUSD":0.0001,"GBPUSD":0.0001,"EURGBP":0.0001,"USDCHF":0.0001,
       "NZDUSD":0.0001,"EURAUD":0.0001,"GBPJPY":0.01,"EURJPY":0.01,"CHFJPY":0.01}


def load_csv(symbol, tf):
    path = os.path.join(DATA_DIR, "{}_{}.csv".format(symbol, tf))
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


# ============================================================
# 1. Quantum London (EURGBP M5, daily open 22:00 UTC)
# ============================================================
print("1. Quantum London (EURGBP M5)...")
df_ql = load_csv("EURGBP", "M5")
pip_ql = 0.0001; spread_ql = 1.0

ql_sessions = {}; ql_cur = None
for _, r in df_ql.iterrows():
    ts = r["time"]; h = ts.hour
    if h == 22 and ts.minute == 0:
        ql_cur = {"date": ts.date(), "open": r["open"], "bars": [], "wd": ts.weekday()}
        ql_sessions[ts.date()] = ql_cur
    if ql_cur and (h >= 22 or h < 6):
        ql_cur["bars"].append({"h": h, "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"]})
    elif ql_cur and h >= 6:
        ql_cur = None

ql_trades = []
for d in sorted(ql_sessions):
    s = ql_sessions[d]
    if s["wd"] not in [0,1,2,3]: continue
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
            if b["lo"] <= do - 8*pip_ql: ep=do-8*pip_ql; ot=("L",ep,ep+5*pip_ql,ep-18*pip_ql)
            elif b["hi"] >= do + 8*pip_ql: ep=do+8*pip_ql; ot=("S",ep,ep-5*pip_ql,ep+18*pip_ql)
    if ot and not done:
        dr, ep, tp, sl = ot; last = trading[-1]
        if dr == "L": pnl = (last["cl"]-ep)/pip_ql-spread_ql
        else: pnl = (ep-last["cl"])/pip_ql-spread_ql
        ql_trades.append({"d":d,"pnl":pnl,"x":"TIME","sym":"EURGBP","strat":"QUANTUM_LONDON"})

print("  {} trades, {:+.0f}p".format(len(ql_trades), sum(t["pnl"] for t in ql_trades)))

# ============================================================
# 2. London Breakout (GBPUSD H1)
# ============================================================
print("2. London Breakout (GBPUSD H1)...")
df_lb = load_csv("GBPUSD", "H1")
pip_lb = 0.0001; spread_lb = 1.0

lb_sessions = {}
for _, r in df_lb.iterrows():
    ts = r["time"]
    if ts.weekday() >= 5: continue
    bd = ts.date()
    if bd not in lb_sessions: lb_sessions[bd] = {"bars": [], "wd": ts.weekday()}
    lb_sessions[bd]["bars"].append({"h": ts.hour, "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"]})

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

print("  {} trades, {:+.0f}p".format(len(lb_trades), sum(t["pnl"] for t in lb_trades)))

# ============================================================
# 3. KZ Hunt (simplified but better — uses H1 with proper KZ tracking)
# ============================================================
print("3. KZ Hunt (8 pairs, H1, simplified)...")

KZ_ZONES = {"london":(8,11),"ny_morning":(13,15),"ny_evening":(16,20),"asian":(0,4)}
KZ_INSTRUMENTS = ["EURUSD","NZDUSD","EURGBP","USDCHF","EURAUD","GBPJPY","EURJPY","CHFJPY"]

# Only use the M5 date range so all three strategies overlap
cutoff = min(ql_sessions) if ql_sessions else datetime(2025,8,1).date()

kz_trades = []
for symbol in KZ_INSTRUMENTS:
    df = load_csv(symbol, "H1")
    if df is None: continue
    pip = PIP[symbol]
    spread = 1.5 if "JPY" not in symbol else 2.0

    bars = []
    for _, r in df.iterrows():
        ts = r["time"]
        if ts.date() < cutoff: continue
        bars.append({"ts": ts, "d": ts.date(), "h": ts.hour, "wd": ts.weekday(),
                     "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"]})

    if len(bars) < 200: continue

    # Compute ATR
    for i in range(1, len(bars)):
        bars[i]["tr"] = max(bars[i]["hi"]-bars[i]["lo"],
                           abs(bars[i]["hi"]-bars[i-1]["cl"]),
                           abs(bars[i]["lo"]-bars[i-1]["cl"]))
    bars[0]["tr"] = bars[0]["hi"] - bars[0]["lo"]
    atr = np.mean([bars[i]["tr"] for i in range(1, min(15, len(bars)))])
    for i in range(14, len(bars)):
        atr = (atr * 13 + bars[i]["tr"]) / 14
        bars[i]["atr"] = atr
    for i in range(14): bars[i]["atr"] = 0

    # Track KZ sessions and find rejections
    kz_data = {}
    for b in bars:
        if b["wd"] >= 5 or b["atr"] == 0: continue
        for kz, (s, e) in KZ_ZONES.items():
            if s <= b["h"] <= e:
                key = (b["d"], kz)
                if key not in kz_data:
                    kz_data[key] = {"hi": b["hi"], "lo": b["lo"], "cnt": 0}
                kz_data[key]["hi"] = max(kz_data[key]["hi"], b["hi"])
                kz_data[key]["lo"] = min(kz_data[key]["lo"], b["lo"])
                kz_data[key]["cnt"] += 1

    traded_dates = set()
    for i in range(30, len(bars)):
        b = bars[i]
        if b["wd"] >= 5 or b["atr"] == 0 or b["d"] in traded_dates: continue

        for kz, (s, e) in KZ_ZONES.items():
            if b["h"] != e + 1: continue
            key = (b["d"], kz)
            if key not in kz_data or kz_data[key]["cnt"] < 2: continue
            kd = kz_data[key]
            kz_range = (kd["hi"] - kd["lo"]) / pip
            atr_val = b["atr"]

            body = abs(b["cl"] - b["o"])
            if body < 0.00001: body = 0.00001

            # LONG rejection at KZ low
            if b["lo"] <= kd["lo"] + 0.3 * atr_val:
                wick = min(b["o"], b["cl"]) - b["lo"]
                if wick > 2 * body:
                    sl = kd["lo"] - 0.5 * atr_val
                    entry = b["cl"]; t1 = kd["hi"]; t2 = entry + kz_range * 1.5 * pip
                    stop_dist = (entry - sl) / pip
                    if stop_dist < 8 or stop_dist <= 0: continue
                    rrr = ((t2 - entry) / pip) / stop_dist
                    if rrr < 1.0: continue

                    # Simulate with 60/40 partial
                    partial_done = False
                    for j in range(i+1, min(i+48, len(bars))):
                        nb = bars[j]
                        if nb["lo"] <= sl:
                            if partial_done:
                                pp = (t1-entry)/pip*0.6 + (sl-entry)/pip*0.4
                            else:
                                pp = -(entry-sl)/pip
                            kz_trades.append({"d":b["d"],"pnl":pp-spread,"x":"SL","sym":symbol,"strat":"KZ_HUNT"})
                            traded_dates.add(b["d"]); break
                        if not partial_done and nb["hi"] >= t1:
                            partial_done = True; sl = entry
                        if nb["hi"] >= t2:
                            pp = (t1-entry)/pip*0.6 + (t2-entry)/pip*0.4
                            kz_trades.append({"d":b["d"],"pnl":pp-spread,"x":"T2","sym":symbol,"strat":"KZ_HUNT"})
                            traded_dates.add(b["d"]); break
                    else:
                        last = bars[min(i+47, len(bars)-1)]
                        if partial_done:
                            pp = (t1-entry)/pip*0.6 + (last["cl"]-entry)/pip*0.4
                        else:
                            pp = (last["cl"]-entry)/pip
                        kz_trades.append({"d":b["d"],"pnl":pp-spread,"x":"TIME","sym":symbol,"strat":"KZ_HUNT"})
                        traded_dates.add(b["d"])
                    break

            # SHORT rejection at KZ high
            if b["hi"] >= kd["hi"] - 0.3 * atr_val:
                wick = b["hi"] - max(b["o"], b["cl"])
                if wick > 2 * body:
                    sl = kd["hi"] + 0.5 * atr_val
                    entry = b["cl"]; t1 = kd["lo"]; t2 = entry - kz_range * 1.5 * pip
                    stop_dist = (sl - entry) / pip
                    if stop_dist < 8 or stop_dist <= 0: continue
                    rrr = ((entry - t2) / pip) / stop_dist
                    if rrr < 1.0: continue

                    partial_done = False
                    for j in range(i+1, min(i+48, len(bars))):
                        nb = bars[j]
                        if nb["hi"] >= sl:
                            if partial_done:
                                pp = (entry-t1)/pip*0.6 + (entry-sl)/pip*0.4
                            else:
                                pp = -(sl-entry)/pip
                            kz_trades.append({"d":b["d"],"pnl":pp-spread,"x":"SL","sym":symbol,"strat":"KZ_HUNT"})
                            traded_dates.add(b["d"]); break
                        if not partial_done and nb["lo"] <= t1:
                            partial_done = True; sl = entry
                        if nb["lo"] <= t2:
                            pp = (entry-t1)/pip*0.6 + (entry-t2)/pip*0.4
                            kz_trades.append({"d":b["d"],"pnl":pp-spread,"x":"T2","sym":symbol,"strat":"KZ_HUNT"})
                            traded_dates.add(b["d"]); break
                    else:
                        last = bars[min(i+47, len(bars)-1)]
                        if partial_done:
                            pp = (entry-t1)/pip*0.6 + (entry-last["cl"])/pip*0.4
                        else:
                            pp = (entry-last["cl"])/pip
                        kz_trades.append({"d":b["d"],"pnl":pp-spread,"x":"TIME","sym":symbol,"strat":"KZ_HUNT"})
                        traded_dates.add(b["d"])
                    break

sym_trades = defaultdict(list)
for t in kz_trades: sym_trades[t["sym"]].append(t)
for sym in sorted(sym_trades):
    st = sym_trades[sym]
    print("  {}: {} trades, {:+.0f}p".format(sym, len(st), sum(t["pnl"] for t in st)))
print("  Total: {} trades".format(len(kz_trades)))

# ============================================================
# Combine and report
# ============================================================
all_trades = kz_trades + lb_trades + ql_trades
all_trades.sort(key=lambda t: t["d"])

print("\n" + "=" * 70)
print("  THREE-STRATEGY PORTFOLIO (overlapping period)")
print("=" * 70)

for strat, label in [("KZ_HUNT","KZ Hunt"),("LONDON_BO","London Breakout"),("QUANTUM_LONDON","Quantum London")]:
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

if all_trades:
    pnls_all = [t["pnl"] for t in all_trades]
    w_all = sum(1 for p in pnls_all if p > 0)
    gp_all = sum(p for p in pnls_all if p > 0)
    gl_all = abs(sum(p for p in pnls_all if p <= 0)) or 0.001
    eq_all = np.cumsum(pnls_all)
    dd_all = max(np.maximum.accumulate(eq_all) - eq_all) if len(eq_all) > 1 else 0
    print("\n  COMBINED: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        len(all_trades), w_all/len(all_trades)*100, gp_all/gl_all, sum(pnls_all), dd_all))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(18, 12), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("Three-Strategy Portfolio (Local Backtest)\nKZ Hunt + London Breakout + Quantum London",
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

if all_trades:
    dates_all = [t["d"] for t in all_trades]
    eq_all = np.cumsum([t["pnl"] for t in all_trades])
    ax.plot(dates_all, eq_all, color="black", linewidth=2.5,
            label="COMBINED: {}T {:+.0f}p".format(len(all_trades), sum(pnls_all)), zorder=10)
    ax.fill_between(dates_all, 0, eq_all, alpha=0.05, color="black")

ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
ax.legend(loc="upper left", fontsize=9)
ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.grid(True, alpha=0.15)

# Monthly bars
monthly = defaultdict(lambda: defaultdict(float))
for t in all_trades:
    m = t["d"].strftime("%Y-%m") if hasattr(t["d"], "strftime") else str(t["d"])[:7]
    monthly[m][t["strat"]] += t["pnl"]

ax2 = axes[1]
months = sorted(monthly.keys())
x = np.arange(len(months))
w_bar = 0.25
for i, (strat, color) in enumerate(colors.items()):
    vals = [monthly[m].get(strat, 0) for m in months]
    ax2.bar(x + i * w_bar, vals, w_bar, label=strat, color=color, alpha=0.8)
ax2.set_xticks(x + w_bar)
ax2.set_xticklabels(months, fontsize=7, rotation=45)
ax2.set_ylabel("Monthly P&L (pips)", fontsize=9)
ax2.axhline(y=0, color="gray", linewidth=0.5)
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(CHART_DIR, "three_strategy_portfolio_local.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))
