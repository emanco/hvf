"""EMA 200 Pullback + Keltner Channel Breakout — combined backtest."""
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

PAIRS = ["EURUSD", "GBPUSD", "EURGBP", "USDCHF", "NZDUSD", "EURAUD"]
PIP_VALUES = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "EURGBP": 0.0001,
              "USDCHF": 0.0001, "NZDUSD": 0.0001, "EURAUD": 0.0001}


def fetch_and_compute(symbol):
    """Fetch H1 data and compute indicators."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 50000)
    if rates is None or len(rates) == 0:
        return None

    bars = []
    for r in rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        bars.append({"ts": ts, "d": ts.date(), "h": ts.hour, "wd": ts.weekday(),
                     "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

    # EMA 200
    ema200 = bars[0]["cl"]
    mult = 2.0 / 201.0
    for b in bars:
        ema200 = b["cl"] * mult + ema200 * (1 - mult)
        b["ema200"] = ema200

    # EMA 100
    ema100 = bars[0]["cl"]
    mult100 = 2.0 / 101.0
    for b in bars:
        ema100 = b["cl"] * mult100 + ema100 * (1 - mult100)
        b["ema100"] = ema100

    # EMA 20
    ema20 = bars[0]["cl"]
    mult20 = 2.0 / 21.0
    for b in bars:
        ema20 = b["cl"] * mult20 + ema20 * (1 - mult20)
        b["ema20"] = ema20

    # ATR 14
    for i in range(1, len(bars)):
        tr = max(bars[i]["hi"] - bars[i]["lo"],
                 abs(bars[i]["hi"] - bars[i-1]["cl"]),
                 abs(bars[i]["lo"] - bars[i-1]["cl"]))
        bars[i]["tr"] = tr
    bars[0]["tr"] = bars[0]["hi"] - bars[0]["lo"]

    atr = np.mean([bars[i]["tr"] for i in range(1, 15)])
    for i in range(14, len(bars)):
        atr = (atr * 13 + bars[i]["tr"]) / 14
        bars[i]["atr"] = atr
    for i in range(14):
        bars[i]["atr"] = 0

    # ADX 14
    for i in range(1, len(bars)):
        bars[i]["pdm"] = max(bars[i]["hi"] - bars[i-1]["hi"], 0) if (bars[i]["hi"] - bars[i-1]["hi"]) > (bars[i-1]["lo"] - bars[i]["lo"]) else 0
        bars[i]["ndm"] = max(bars[i-1]["lo"] - bars[i]["lo"], 0) if (bars[i-1]["lo"] - bars[i]["lo"]) > (bars[i]["hi"] - bars[i-1]["hi"]) else 0
    bars[0]["pdm"] = bars[0]["ndm"] = 0

    if len(bars) > 28:
        atr_s = np.mean([bars[i]["tr"] for i in range(1, 15)])
        pdm_s = np.mean([bars[i]["pdm"] for i in range(1, 15)])
        ndm_s = np.mean([bars[i]["ndm"] for i in range(1, 15)])
        for i in range(14, len(bars)):
            atr_s = (atr_s * 13 + bars[i]["tr"]) / 14
            pdm_s = (pdm_s * 13 + bars[i]["pdm"]) / 14
            ndm_s = (ndm_s * 13 + bars[i]["ndm"]) / 14
            pdi = 100 * pdm_s / atr_s if atr_s > 0 else 0
            ndi = 100 * ndm_s / atr_s if atr_s > 0 else 0
            di_sum = pdi + ndi
            dx = 100 * abs(pdi - ndi) / di_sum if di_sum > 0 else 0
            bars[i]["adx"] = dx
            bars[i]["pdi"] = pdi
            bars[i]["ndi"] = ndi
        for i in range(14):
            bars[i]["adx"] = bars[i]["pdi"] = bars[i]["ndi"] = 0

    # Keltner channels
    for b in bars:
        if b["atr"] > 0:
            b["kelt_upper"] = b["ema20"] + 2 * b["atr"]
            b["kelt_lower"] = b["ema20"] - 2 * b["atr"]
        else:
            b["kelt_upper"] = b["kelt_lower"] = b["ema20"]

    return bars


# ============================================================
# EMA 200 Pullback Strategy
# ============================================================
def run_ema_pullback(bars, symbol, spread=1.5):
    """Buy pullbacks to EMA100-200 zone in strong trends."""
    pip = PIP_VALUES[symbol]
    trades = []
    cooldown = 0

    for i in range(250, len(bars)):
        b = bars[i]
        if b["wd"] >= 5 or b["atr"] == 0 or b.get("adx", 0) == 0:
            continue
        if i <= cooldown:
            continue

        ema200 = b["ema200"]
        ema100 = b["ema100"]
        adx = b.get("adx", 0)
        atr = b["atr"]

        # Need strong trend: ADX > 25
        if adx < 25:
            continue

        # LONG: price above EMA200 and pulls back to EMA100-200 zone
        if b["cl"] > ema200 and b["lo"] <= ema100 and b["cl"] > ema100:
            # Bullish close above EMA100 after touching it
            entry = b["cl"]
            sl = ema200 - 0.5 * atr
            tp = entry + 2 * (entry - sl)  # 1:2 RR
            stop_dist = (entry - sl) / pip
            if stop_dist < 8 or stop_dist > 50:
                continue

            # Simulate
            for j in range(i + 1, min(i + 48, len(bars))):
                nb = bars[j]
                if nb["lo"] <= sl:
                    trades.append({"d": b["d"], "pnl": -(entry - sl) / pip - spread, "x": "SL",
                                   "sym": symbol, "strat": "EMA_PULLBACK", "dir": "LONG"})
                    cooldown = j + 2; break
                if nb["hi"] >= tp:
                    trades.append({"d": b["d"], "pnl": (tp - entry) / pip - spread, "x": "TP",
                                   "sym": symbol, "strat": "EMA_PULLBACK", "dir": "LONG"})
                    cooldown = j + 2; break
            else:
                last = bars[min(i + 47, len(bars) - 1)]
                trades.append({"d": b["d"], "pnl": (last["cl"] - entry) / pip - spread, "x": "TIME",
                               "sym": symbol, "strat": "EMA_PULLBACK", "dir": "LONG"})
                cooldown = i + 48

        # SHORT: price below EMA200 and pulls back up to EMA100-200 zone
        elif b["cl"] < ema200 and b["hi"] >= ema100 and b["cl"] < ema100:
            entry = b["cl"]
            sl = ema200 + 0.5 * atr
            tp = entry - 2 * (sl - entry)
            stop_dist = (sl - entry) / pip
            if stop_dist < 8 or stop_dist > 50:
                continue

            for j in range(i + 1, min(i + 48, len(bars))):
                nb = bars[j]
                if nb["hi"] >= sl:
                    trades.append({"d": b["d"], "pnl": -(sl - entry) / pip - spread, "x": "SL",
                                   "sym": symbol, "strat": "EMA_PULLBACK", "dir": "SHORT"})
                    cooldown = j + 2; break
                if nb["lo"] <= tp:
                    trades.append({"d": b["d"], "pnl": (entry - tp) / pip - spread, "x": "TP",
                                   "sym": symbol, "strat": "EMA_PULLBACK", "dir": "SHORT"})
                    cooldown = j + 2; break
            else:
                last = bars[min(i + 47, len(bars) - 1)]
                trades.append({"d": b["d"], "pnl": (entry - last["cl"]) / pip - spread, "x": "TIME",
                               "sym": symbol, "strat": "EMA_PULLBACK", "dir": "SHORT"})
                cooldown = i + 48

    return trades


# ============================================================
# Keltner Channel Breakout
# ============================================================
def run_keltner(bars, symbol, spread=1.5):
    """Trade breakouts beyond Keltner Channel with ADX confirmation."""
    pip = PIP_VALUES[symbol]
    trades = []
    cooldown = 0

    for i in range(250, len(bars)):
        b = bars[i]
        if b["wd"] >= 5 or b["atr"] == 0:
            continue
        if i <= cooldown:
            continue

        adx = b.get("adx", 0)
        if adx < 25:
            continue

        atr = b["atr"]
        ema20 = b["ema20"]

        # LONG: close above upper Keltner
        if b["cl"] > b["kelt_upper"]:
            entry = b["cl"]
            sl = ema20  # middle line
            tp = entry + 1.5 * (entry - sl)  # 1:1.5 RR
            stop_dist = (entry - sl) / pip
            if stop_dist < 5 or stop_dist > 60:
                continue

            for j in range(i + 1, min(i + 24, len(bars))):
                nb = bars[j]
                if nb["lo"] <= sl:
                    trades.append({"d": b["d"], "pnl": -(entry - sl) / pip - spread, "x": "SL",
                                   "sym": symbol, "strat": "KELTNER_BO", "dir": "LONG"})
                    cooldown = j + 2; break
                if nb["hi"] >= tp:
                    trades.append({"d": b["d"], "pnl": (tp - entry) / pip - spread, "x": "TP",
                                   "sym": symbol, "strat": "KELTNER_BO", "dir": "LONG"})
                    cooldown = j + 2; break
            else:
                last = bars[min(i + 23, len(bars) - 1)]
                trades.append({"d": b["d"], "pnl": (last["cl"] - entry) / pip - spread, "x": "TIME",
                               "sym": symbol, "strat": "KELTNER_BO", "dir": "LONG"})
                cooldown = i + 24

        # SHORT: close below lower Keltner
        elif b["cl"] < b["kelt_lower"]:
            entry = b["cl"]
            sl = ema20
            tp = entry - 1.5 * (sl - entry)
            stop_dist = (sl - entry) / pip
            if stop_dist < 5 or stop_dist > 60:
                continue

            for j in range(i + 1, min(i + 24, len(bars))):
                nb = bars[j]
                if nb["hi"] >= sl:
                    trades.append({"d": b["d"], "pnl": -(sl - entry) / pip - spread, "x": "SL",
                                   "sym": symbol, "strat": "KELTNER_BO", "dir": "SHORT"})
                    cooldown = j + 2; break
                if nb["lo"] <= tp:
                    trades.append({"d": b["d"], "pnl": (entry - tp) / pip - spread, "x": "TP",
                                   "sym": symbol, "strat": "KELTNER_BO", "dir": "SHORT"})
                    cooldown = j + 2; break
            else:
                last = bars[min(i + 23, len(bars) - 1)]
                trades.append({"d": b["d"], "pnl": (entry - last["cl"]) / pip - spread, "x": "TIME",
                               "sym": symbol, "strat": "KELTNER_BO", "dir": "SHORT"})
                cooldown = i + 24

    return trades


# ============================================================
# Run both on all pairs
# ============================================================
ema_all = []
kelt_all = []

for symbol in PAIRS:
    print("Fetching {}...".format(symbol))
    bars = fetch_and_compute(symbol)
    if bars is None:
        print("  No data")
        continue
    first = bars[0]["d"]; last = bars[-1]["d"]
    print("  {} bars, {} to {}".format(len(bars), first, last))

    ema_trades = run_ema_pullback(bars, symbol)
    kelt_trades = run_keltner(bars, symbol)
    ema_all.extend(ema_trades)
    kelt_all.extend(kelt_trades)
    print("  EMA Pullback: {} trades, {:+.0f}p".format(len(ema_trades), sum(t["pnl"] for t in ema_trades)))
    print("  Keltner BO:   {} trades, {:+.0f}p".format(len(kelt_trades), sum(t["pnl"] for t in kelt_trades)))

# Results
print("\n" + "=" * 70)
print("  RESULTS")
print("=" * 70)

for strat, trades, label in [("EMA_PULLBACK", ema_all, "EMA 200 Pullback"),
                               ("KELTNER_BO", kelt_all, "Keltner Breakout")]:
    if not trades:
        print("\n  {}: 0 trades".format(label)); continue
    pnls = [t["pnl"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    eq = np.cumsum(pnls)
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
    print("\n  {}: {} trades, WR={:.0f}%, PF={:.2f}, Tot={:+.0f}p, DD={:.0f}p".format(
        label, len(trades), w / len(trades) * 100, gp / gl, sum(pnls), dd))

    # Per pair
    pairs = set(t["sym"] for t in trades)
    for sym in sorted(pairs):
        pt = [t for t in trades if t["sym"] == sym]
        pw = sum(1 for t in pt if t["pnl"] > 0)
        print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
            sym, len(pt), pw / len(pt) * 100 if pt else 0, sum(t["pnl"] for t in pt)))

    # Yearly
    yearly = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0})
    for t in trades:
        yr = t["d"].year
        yearly[yr]["n"] += 1; yearly[yr]["pnl"] += t["pnl"]
        if t["pnl"] > 0: yearly[yr]["w"] += 1
    print("  Yearly:")
    for yr in sorted(yearly):
        y = yearly[yr]
        print("    {}: {}T WR={:.0f}% PnL={:+.0f}p".format(
            yr, y["n"], y["w"] / y["n"] * 100 if y["n"] else 0, y["pnl"]))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 1, figsize=(16, 12))
fig.suptitle("Trend-Following Strategies — EMA Pullback vs Keltner Breakout\n6 pairs, H1, full history",
             fontsize=13, fontweight="bold")

for idx, (trades, label, color) in enumerate([
    (ema_all, "EMA 200 Pullback", "#2196F3"),
    (kelt_all, "Keltner Breakout", "#9C27B0"),
]):
    ax = axes[idx]
    if not trades:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center")
        ax.set_title(label)
        continue

    trades_sorted = sorted(trades, key=lambda t: t["d"])
    dates = [t["d"] for t in trades_sorted]
    pnls = [t["pnl"] for t in trades_sorted]
    eq = np.cumsum(pnls)
    w = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0

    c = "#2196F3" if eq[-1] > 0 else "#F44336"
    ax.plot(dates, eq, color=c, linewidth=1.5)
    ax.fill_between(dates, 0, eq, alpha=0.08, color=c)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)

    for j, t in enumerate(trades_sorted):
        if t["x"] == "TP": tc = "#4CAF50"
        elif t["x"] == "SL": tc = "#F44336"
        else: tc = "#FFC107"
        ax.scatter(dates[j], eq[j], color=tc, s=8, zorder=5)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title("{} | {} trades".format(label, len(trades)), fontsize=11, fontweight="bold")
    ax.set_ylabel("Pips", fontsize=10)
    ax.text(0.02, 0.95,
            "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p".format(
                w / len(pnls) * 100, gp / gl, sum(pnls), dd),
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    ax.grid(True, alpha=0.15)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "trend_strategies_backtest.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart: {}".format(outpath))

mt5.shutdown()
