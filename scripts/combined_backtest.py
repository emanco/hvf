"""
Combined backtest: KZ Hunt + Asian Gravity + London Breakout
Split by strategy and pair, with combined equity curve.
Uses H1 data from MT5 (1 year).
"""
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

# ---- KZ Hunt config (from config.py) ----
KZ_INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]
KZ_KILL_ZONES = {"london": (8, 11), "ny_morning": (13, 15), "ny_evening": (16, 20), "asian": (0, 4)}
KZ_SCORE_THRESHOLD = 50
KZ_MIN_RRR = 1.0
KZ_PARTIAL_PCT = 0.60
KZ_TRAILING_ATR = 1.0
KZ_MIN_STOP_PIPS = 8

# ---- London Breakout config ----
LB_INSTRUMENT = "GBPUSD"
LB_DAYS = [0, 1]  # Mon, Tue
LB_MIN_RANGE = 12
LB_MAX_RANGE = 20
LB_TP_MULT = 1.0
LB_EXIT_HOUR = 13
LB_SPREAD = 1.0

# ---- Asian Gravity config ----
AG_INSTRUMENT = "EURGBP"
AG_DAYS = [3]  # Thursday
AG_TRIGGER = 5
AG_TARGET = 2
AG_STOP = 8
AG_MAX_RANGE = 20
AG_SPREAD = 1.0
AG_DIRECTION = "SHORT"

PIP_VALUES = {
    "EURUSD": 0.0001, "NZDUSD": 0.0001, "EURGBP": 0.0001,
    "USDCHF": 0.0001, "EURAUD": 0.0001, "GBPJPY": 0.01,
    "EURJPY": 0.01, "CHFJPY": 0.01, "GBPUSD": 0.0001,
}


def fetch(symbol, tf, count=50000):
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    return rates


# ============================================================
# London Breakout backtest
# ============================================================
def run_london_breakout():
    rates = fetch(LB_INSTRUMENT, mt5.TIMEFRAME_H1)
    if rates is None:
        return []
    pip = PIP_VALUES[LB_INSTRUMENT]
    sessions = {}
    for r in rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        if ts.weekday() >= 5:
            continue
        bd = ts.date()
        if bd not in sessions:
            sessions[bd] = {"bars": [], "wd": ts.weekday()}
        sessions[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

    # Filter to last year
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)

    trades = []
    for d in sorted(sessions):
        if d < cutoff:
            continue
        s = sessions[d]
        if s["wd"] not in LB_DAYS:
            continue
        asian = [b for b in s["bars"] if b["h"] < 7]
        if len(asian) < 3:
            continue
        ah = max(b["hi"] for b in asian)
        al = min(b["lo"] for b in asian)
        ar = (ah - al) / pip
        if ar < LB_MIN_RANGE or ar > LB_MAX_RANGE:
            continue
        london = [b for b in s["bars"] if 8 <= b["h"] < LB_EXIT_HOUR]
        if not london:
            continue
        td = ar * LB_TP_MULT * pip
        sp = LB_SPREAD * pip
        traded = False
        for b in london:
            if traded:
                break
            if b["hi"] > ah + sp:
                e = ah + sp; sl = al - sp; tp = e + td; rk = (e - sl) / pip
                rem = [bb for bb in london if bb["h"] >= b["h"]]
                hit = None
                for rb in rem:
                    if rb["lo"] <= sl: hit = "SL"; pnl = -rk - LB_SPREAD; break
                    if rb["hi"] >= tp: hit = "TP"; pnl = (tp - e) / pip - LB_SPREAD; break
                if not hit:
                    lc = rem[-1]["cl"]; pnl = (lc - e) / pip - LB_SPREAD; hit = "TIME"
                trades.append({"d": d, "pnl": pnl, "x": hit, "sym": LB_INSTRUMENT,
                               "strat": "LONDON_BO", "dir": "LONG"})
                traded = True
            if not traded and b["lo"] < al - sp:
                e = al - sp; sl = ah + sp; tp = e - td; rk = (sl - e) / pip
                rem = [bb for bb in london if bb["h"] >= b["h"]]
                hit = None
                for rb in rem:
                    if rb["hi"] >= sl: hit = "SL"; pnl = -rk - LB_SPREAD; break
                    if rb["lo"] <= tp: hit = "TP"; pnl = (e - tp) / pip - LB_SPREAD; break
                if not hit:
                    lc = rem[-1]["cl"]; pnl = (e - lc) / pip - LB_SPREAD; hit = "TIME"
                trades.append({"d": d, "pnl": pnl, "x": hit, "sym": LB_INSTRUMENT,
                               "strat": "LONDON_BO", "dir": "SHORT"})
                traded = True
    return trades


# ============================================================
# Asian Gravity backtest
# ============================================================
def run_asian_gravity():
    rates = fetch(AG_INSTRUMENT, mt5.TIMEFRAME_M5)
    if rates is None:
        # Try M15
        rates = fetch(AG_INSTRUMENT, mt5.TIMEFRAME_M15)
        if rates is None:
            return []
    pip = PIP_VALUES[AG_INSTRUMENT]
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)

    sessions = {}
    for r in rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        if ts.weekday() >= 5 or ts.hour >= 6:
            continue
        bd = ts.date()
        if bd not in sessions:
            sessions[bd] = {"wd": ts.weekday(), "bars": []}
        sessions[bd]["bars"].append({"h": ts.hour, "m": ts.minute, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

    for s in sessions.values():
        form = [b for b in s["bars"] if b["h"] < 2]
        if form:
            s["open"] = s["bars"][0]["o"]
            s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip
        else:
            s["range"] = 999

    trades = []
    for d in sorted(sessions):
        if d < cutoff:
            continue
        s = sessions[d]
        if s["wd"] not in AG_DAYS or s["range"] > AG_MAX_RANGE or s["range"] < 1:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot = None; done = False
        for b in trading:
            if done:
                continue
            if ot:
                ep, tp, sl_p = ot
                if AG_DIRECTION == "SHORT":
                    if b["hi"] >= sl_p:
                        trades.append({"d": d, "pnl": (ep - sl_p) / pip - AG_SPREAD, "x": "SL",
                                       "sym": AG_INSTRUMENT, "strat": "ASIAN_GRAVITY", "dir": "SHORT"})
                        done = True; continue
                    if b["lo"] <= tp:
                        trades.append({"d": d, "pnl": (ep - tp) / pip - AG_SPREAD, "x": "TP",
                                       "sym": AG_INSTRUMENT, "strat": "ASIAN_GRAVITY", "dir": "SHORT"})
                        done = True; continue
            else:
                if AG_DIRECTION == "SHORT" and b["hi"] >= so + AG_TRIGGER * pip:
                    ep = so + AG_TRIGGER * pip
                    ot = (ep, ep - AG_TARGET * pip, ep + AG_STOP * pip)
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            pnl = (ot[0] - last["cl"]) / pip - AG_SPREAD
            trades.append({"d": d, "pnl": pnl, "x": "TIME", "sym": AG_INSTRUMENT,
                           "strat": "ASIAN_GRAVITY", "dir": "SHORT"})
    return trades


# ============================================================
# KZ Hunt simplified backtest (H1 bar-level)
# ============================================================
def run_kz_hunt():
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)
    all_trades = []

    for symbol in KZ_INSTRUMENTS:
        rates = fetch(symbol, mt5.TIMEFRAME_H1)
        if rates is None:
            continue
        pip = PIP_VALUES[symbol]
        spread = 1.5 * pip  # conservative

        # Build bars
        bars = []
        for r in rates:
            ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
            if ts.date() < cutoff:
                continue
            bars.append({"ts": ts, "h": ts.hour, "d": ts.date(), "wd": ts.weekday(),
                         "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
                         "atr": 0})

        if len(bars) < 250:
            continue

        # Compute ATR(14)
        for i in range(14, len(bars)):
            trs = []
            for j in range(i - 14, i):
                tr = max(bars[j]["hi"] - bars[j]["lo"],
                         abs(bars[j]["hi"] - bars[j - 1]["cl"]) if j > 0 else 0,
                         abs(bars[j]["lo"] - bars[j - 1]["cl"]) if j > 0 else 0)
                trs.append(tr)
            bars[i]["atr"] = np.mean(trs)

        # Track KZ sessions
        kz_sessions = {}  # date -> {kz_name: {high, low, bar_count}}
        for b in bars:
            if b["wd"] >= 5:
                continue
            for kz_name, (start, end) in KZ_KILL_ZONES.items():
                if start <= b["h"] <= end:
                    key = (b["d"], kz_name)
                    if key not in kz_sessions:
                        kz_sessions[key] = {"high": b["hi"], "low": b["lo"], "count": 0, "end_idx": 0}
                    kz_sessions[key]["high"] = max(kz_sessions[key]["high"], b["hi"])
                    kz_sessions[key]["low"] = min(kz_sessions[key]["low"], b["lo"])
                    kz_sessions[key]["count"] += 1

        # Simple KZ Hunt: after KZ completes, look for rejection at extremes
        # This is a simplified version — the real detector is more sophisticated
        trades_this_sym = []
        traded_dates = set()

        for i in range(50, len(bars)):
            b = bars[i]
            if b["wd"] >= 5 or b["atr"] == 0:
                continue
            if b["d"] in traded_dates:
                continue

            # Check completed KZs from previous bars
            for kz_name, (start, end) in KZ_KILL_ZONES.items():
                if b["h"] != end + 1:  # bar right after KZ ends
                    continue
                key = (b["d"], kz_name)
                if key not in kz_sessions or kz_sessions[key]["count"] < 2:
                    continue

                kz = kz_sessions[key]
                kz_range = (kz["high"] - kz["low"]) / pip
                atr = b["atr"]

                # Rejection at KZ low (LONG): bar close near KZ low with lower wick > 2x body
                body = abs(b["cl"] - b["o"])
                if body < 0.00001:
                    body = 0.00001

                # Check LONG: bar near KZ low
                if b["lo"] <= kz["low"] + 0.3 * atr:
                    lower_wick = min(b["o"], b["cl"]) - b["lo"]
                    if lower_wick > 2 * body:
                        sl = kz["low"] - 0.5 * atr
                        entry = b["cl"]
                        t1 = kz["high"]
                        t2 = entry + kz_range * 1.5 * pip
                        stop_dist = (entry - sl) / pip
                        if stop_dist < KZ_MIN_STOP_PIPS or stop_dist <= 0:
                            continue
                        rrr = ((t2 - entry) / pip) / stop_dist
                        if rrr < KZ_MIN_RRR:
                            continue

                        # Simulate: check next bars for SL/T1/T2
                        pnl = _simulate_kz_trade(bars, i, "LONG", entry, sl, t1, t2, pip, spread / pip)
                        if pnl is not None:
                            trades_this_sym.append({"d": b["d"], "pnl": pnl[0], "x": pnl[1],
                                                    "sym": symbol, "strat": "KZ_HUNT", "dir": "LONG"})
                            traded_dates.add(b["d"])
                            break

                # Check SHORT: bar near KZ high
                if b["hi"] >= kz["high"] - 0.3 * atr:
                    upper_wick = b["hi"] - max(b["o"], b["cl"])
                    if upper_wick > 2 * body:
                        sl = kz["high"] + 0.5 * atr
                        entry = b["cl"]
                        t1 = kz["low"]
                        t2 = entry - kz_range * 1.5 * pip
                        stop_dist = (sl - entry) / pip
                        if stop_dist < KZ_MIN_STOP_PIPS or stop_dist <= 0:
                            continue
                        rrr = ((entry - t2) / pip) / stop_dist
                        if rrr < KZ_MIN_RRR:
                            continue

                        pnl = _simulate_kz_trade(bars, i, "SHORT", entry, sl, t1, t2, pip, spread / pip)
                        if pnl is not None:
                            trades_this_sym.append({"d": b["d"], "pnl": pnl[0], "x": pnl[1],
                                                    "sym": symbol, "strat": "KZ_HUNT", "dir": "SHORT"})
                            traded_dates.add(b["d"])
                            break

        all_trades.extend(trades_this_sym)
    return all_trades


def _simulate_kz_trade(bars, entry_idx, direction, entry, sl, t1, t2, pip, spread):
    """Simulate a KZ Hunt trade with 60/40 partial close."""
    partial_pct = KZ_PARTIAL_PCT
    remain_pct = 1.0 - partial_pct
    partial_done = False

    for j in range(entry_idx + 1, min(entry_idx + 48, len(bars))):  # max 48 bars (2 days)
        b = bars[j]
        if direction == "LONG":
            if b["lo"] <= sl:
                if partial_done:
                    pnl_remain = (sl - entry) / pip * remain_pct
                    pnl_partial = (t1 - entry) / pip * partial_pct
                    return (pnl_partial + pnl_remain - spread, "SL_AFTER_T1")
                return (-(entry - sl) / pip - spread, "SL")
            if not partial_done and b["hi"] >= t1:
                partial_done = True
                sl = entry  # move to breakeven
            if b["hi"] >= t2:
                if partial_done:
                    pnl_partial = (t1 - entry) / pip * partial_pct
                    pnl_remain = (t2 - entry) / pip * remain_pct
                    return (pnl_partial + pnl_remain - spread, "T2")
                return ((t2 - entry) / pip - spread, "T2")
        else:
            if b["hi"] >= sl:
                if partial_done:
                    pnl_remain = (entry - sl) / pip * remain_pct
                    pnl_partial = (entry - t1) / pip * partial_pct
                    return (pnl_partial + pnl_remain - spread, "SL_AFTER_T1")
                return (-(sl - entry) / pip - spread, "SL")
            if not partial_done and b["lo"] <= t1:
                partial_done = True
                sl = entry
            if b["lo"] <= t2:
                if partial_done:
                    pnl_partial = (entry - t1) / pip * partial_pct
                    pnl_remain = (entry - t2) / pip * remain_pct
                    return (pnl_partial + pnl_remain - spread, "T2")
                return ((entry - t2) / pip - spread, "T2")

    # Time exit after 48 bars
    last = bars[min(entry_idx + 47, len(bars) - 1)]
    if direction == "LONG":
        pnl = (last["cl"] - entry) / pip - spread
    else:
        pnl = (entry - last["cl"]) / pip - spread
    if partial_done:
        if direction == "LONG":
            pnl = (t1 - entry) / pip * partial_pct + (last["cl"] - entry) / pip * remain_pct - spread
        else:
            pnl = (entry - t1) / pip * partial_pct + (entry - last["cl"]) / pip * remain_pct - spread
    return (pnl, "TIME")


# ============================================================
# Run all and combine
# ============================================================
print("Running backtests...")
print("  KZ Hunt ({} pairs)...".format(len(KZ_INSTRUMENTS)))
kz_trades = run_kz_hunt()
print("    {} trades".format(len(kz_trades)))

print("  London Breakout (GBPUSD)...")
lb_trades = run_london_breakout()
print("    {} trades".format(len(lb_trades)))

print("  Asian Gravity (EURGBP)...")
ag_trades = run_asian_gravity()
print("    {} trades".format(len(ag_trades)))

all_trades = kz_trades + lb_trades + ag_trades
all_trades.sort(key=lambda t: t["d"])

print("\n" + "=" * 70)
print("  COMBINED PORTFOLIO — Past Year")
print("=" * 70)

# Per-strategy summary
for strat in ["KZ_HUNT", "LONDON_BO", "ASIAN_GRAVITY"]:
    st = [t for t in all_trades if t["strat"] == strat]
    if not st:
        print("\n  {}: 0 trades".format(strat))
        continue
    pnls = [t["pnl"] for t in st]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    print("\n  {}: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p".format(
        strat, len(st), w / len(st) * 100, gp / gl, sum(pnls)))

    # Per-pair within strategy
    pairs = set(t["sym"] for t in st)
    for sym in sorted(pairs):
        pt = [t for t in st if t["sym"] == sym]
        pw = sum(1 for t in pt if t["pnl"] > 0)
        pp = sum(t["pnl"] for t in pt)
        print("    {}: {} trades, WR={:.0f}%, PnL={:+.0f}p".format(
            sym, len(pt), pw / len(pt) * 100 if pt else 0, pp))

# Combined stats
if all_trades:
    pnls = [t["pnl"] for t in all_trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0

    print("\n  COMBINED: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        len(all_trades), w / len(all_trades) * 100, gp / gl, sum(pnls), dd))

# Monthly breakdown
monthly = defaultdict(lambda: defaultdict(float))
for t in all_trades:
    m = t["d"].strftime("%Y-%m")
    monthly[m][t["strat"]] += t["pnl"]
    monthly[m]["total"] += t["pnl"]

print("\n  Monthly breakdown:")
print("  {:<8} {:>10} {:>10} {:>10} {:>10}".format(
    "Month", "KZ_HUNT", "LONDON_BO", "ASIAN_GRV", "TOTAL"))
print("  " + "-" * 52)
for m in sorted(monthly):
    d = monthly[m]
    print("  {:<8} {:>+9.0f}p {:>+9.0f}p {:>+9.0f}p {:>+9.0f}p".format(
        m, d.get("KZ_HUNT", 0), d.get("LONDON_BO", 0),
        d.get("ASIAN_GRAVITY", 0), d["total"]))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(16, 12), gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("Combined Portfolio — KZ Hunt + London Breakout + Asian Gravity (1 Year)",
             fontsize=14, fontweight="bold")

# Top: equity curves stacked
ax = axes[0]
colors = {"KZ_HUNT": "#2196F3", "LONDON_BO": "#4CAF50", "ASIAN_GRAVITY": "#FF9800"}

for strat, color in colors.items():
    st = [t for t in all_trades if t["strat"] == strat]
    if not st:
        continue
    st.sort(key=lambda t: t["d"])
    dates = [t["d"] for t in st]
    eq = np.cumsum([t["pnl"] for t in st])
    ax.plot(dates, eq, color=color, linewidth=1.5, label=strat, alpha=0.8)

# Combined
dates_all = [t["d"] for t in all_trades]
eq_all = np.cumsum([t["pnl"] for t in all_trades])
ax.plot(dates_all, eq_all, color="black", linewidth=2.5, label="COMBINED", zorder=10)
ax.fill_between(dates_all, 0, eq_all, alpha=0.05, color="black")
ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

pnls_all = [t["pnl"] for t in all_trades]
w_all = sum(1 for p in pnls_all if p > 0)
gp_all = sum(p for p in pnls_all if p > 0)
gl_all = abs(sum(p for p in pnls_all if p <= 0)) or 0.001
ax.text(0.02, 0.95,
        "Combined: {} trades  WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
            len(all_trades), w_all / len(all_trades) * 100, gp_all / gl_all,
            sum(pnls_all), dd),
        transform=ax.transAxes, fontsize=10, va="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))

ax.legend(loc="lower right", fontsize=9)
ax.set_ylabel("Cumulative P&L (pips)", fontsize=10)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.grid(True, alpha=0.15)

# Bottom: monthly bars by strategy
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
                       "backtests", "charts", "combined_portfolio_1yr.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
