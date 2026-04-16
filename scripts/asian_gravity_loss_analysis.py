"""Analyze what distinguishes the 5 losing Thursday sessions from the 19 winners."""
import sys, os
from datetime import datetime, timedelta, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

# Get M5 data
rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
# Also get H1 for previous day context
h1_rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_H1, 0, 10000)

pip = 0.0001
spread = 1.0

# Build M5 sessions
sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5 or ts.hour >= 6:
        continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"wd": ts.weekday(), "bars": []}
    sessions[bd]["bars"].append({
        "h": ts.hour, "m": ts.minute,
        "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4], "vol": r[5],
    })

# Build H1 daily data for previous-day context
h1_by_date = {}
for r in h1_rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    bd = ts.date()
    if bd not in h1_by_date:
        h1_by_date[bd] = []
    h1_by_date[bd].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

for s in sessions.values():
    form = [b for b in s["bars"] if b["h"] < 2]
    if form:
        s["open"] = s["bars"][0]["o"]
        s["fh"] = max(b["hi"] for b in form)
        s["fl"] = min(b["lo"] for b in form)
        s["range"] = (s["fh"] - s["fl"]) / pip
    else:
        s["range"] = 999

thu = {d: s for d, s in sessions.items() if s["wd"] == 3}

# Simulate Thursday SHORT T5/T2/S8 rng<20
trigger = 5; target = 2; stop = 8; max_range = 20
trades = []
for d in sorted(thu):
    s = thu[d]
    if s["range"] > max_range or s["range"] < 1:
        continue
    so = s["open"]
    trading = [b for b in s["bars"] if b["h"] >= 2]
    ot = None; done = False; et = ""

    # Compute session characteristics
    all_highs = [b["hi"] for b in trading]
    all_lows = [b["lo"] for b in trading]
    max_drift_up = max((b["hi"] - so) / pip for b in trading) if trading else 0
    max_drift_down = max((so - b["lo"]) / pip for b in trading) if trading else 0
    trading_range = (max(all_highs) - min(all_lows)) / pip if trading else 0
    avg_vol = np.mean([b["vol"] for b in trading]) if trading else 0

    # Formation characteristics
    form_bars = [b for b in s["bars"] if b["h"] < 2]
    form_vol = np.mean([b["vol"] for b in form_bars]) if form_bars else 0

    # Previous day H1 range
    prev_date = d - timedelta(days=1)
    prev_range = 0
    prev_asian_range = 0
    if prev_date in h1_by_date:
        prev_bars = h1_by_date[prev_date]
        if prev_bars:
            prev_range = (max(b["hi"] for b in prev_bars) - min(b["lo"] for b in prev_bars)) / pip
        prev_asian = [b for b in prev_bars if b["h"] < 6]
        if prev_asian:
            prev_asian_range = (max(b["hi"] for b in prev_asian) - min(b["lo"] for b in prev_asian)) / pip

    # Direction of formation (did price drift up or down during formation?)
    if form_bars:
        form_close = form_bars[-1]["cl"]
        form_direction = (form_close - so) / pip  # positive = drifted up during formation
    else:
        form_direction = 0

    for b in trading:
        if done: continue
        if ot:
            ep, tp, sl_p = ot
            if b["hi"] >= sl_p:
                trades.append({"d": d, "pnl": (ep-sl_p)/pip-spread, "x": "SL", "et": et,
                    "rng": s["range"], "max_up": max_drift_up, "max_down": max_drift_down,
                    "trd_rng": trading_range, "avg_vol": avg_vol, "form_vol": form_vol,
                    "prev_range": prev_range, "prev_asian": prev_asian_range,
                    "form_dir": form_direction})
                done = True; continue
            if b["lo"] <= tp:
                trades.append({"d": d, "pnl": (ep-tp)/pip-spread, "x": "TP", "et": et,
                    "rng": s["range"], "max_up": max_drift_up, "max_down": max_drift_down,
                    "trd_rng": trading_range, "avg_vol": avg_vol, "form_vol": form_vol,
                    "prev_range": prev_range, "prev_asian": prev_asian_range,
                    "form_dir": form_direction})
                done = True; continue
        else:
            if b["hi"] >= so + trigger * pip:
                ep = so + trigger * pip
                ot = (ep, ep - target*pip, ep + stop*pip)
                et = "{:02d}:{:02d}".format(b["h"], b["m"])
    if ot and not done:
        last = trading[-1] if trading else s["bars"][-1]
        trades.append({"d": d, "pnl": (ot[0]-last["cl"])/pip-spread, "x": "TIME", "et": et,
            "rng": s["range"], "max_up": max_drift_up, "max_down": max_drift_down,
            "trd_rng": trading_range, "avg_vol": avg_vol, "form_vol": form_vol,
            "prev_range": prev_range, "prev_asian": prev_asian_range,
            "form_dir": form_direction})

wins = [t for t in trades if t["pnl"] > 0]
losses = [t for t in trades if t["pnl"] <= 0]

print("=" * 80)
print("  LOSS vs WIN Analysis — Thursday SHORT T5/T2/S8 rng<20")
print("=" * 80)

# Detailed comparison
print("\n{:<12} {:>5} {:>5} {:>6} {:>6} {:>6} {:>7} {:>7} {:>7} {:>7} {:>6}".format(
    "Date", "PnL", "Exit", "FmRng", "TdRng", "MaxUp", "MaxDn", "FmVol", "TdVol", "PvRng", "FmDir"))
print("-" * 95)

for t in trades:
    marker = " WIN" if t["pnl"] > 0 else " LOSS"
    print("{} {:>+5.1f}p {:>4} {:>5.0f}p {:>5.0f}p {:>5.0f}p {:>6.0f}p {:>6.0f} {:>6.0f} {:>6.0f}p {:>+5.1f}p{}".format(
        t["d"], t["pnl"], t["x"], t["rng"], t["trd_rng"], t["max_up"],
        t["max_down"], t["form_vol"], t["avg_vol"], t["prev_range"], t["form_dir"], marker))

# Statistical comparison
print("\n" + "=" * 60)
print("  STATISTICAL COMPARISON")
print("=" * 60)
metrics = [
    ("Formation range (pips)", "rng"),
    ("Trading range (pips)", "trd_rng"),
    ("Max drift UP (pips)", "max_up"),
    ("Max drift DOWN (pips)", "max_down"),
    ("Formation volume", "form_vol"),
    ("Trading volume", "avg_vol"),
    ("Prev day H1 range", "prev_range"),
    ("Prev day Asian range", "prev_asian"),
    ("Formation direction", "form_dir"),
]

print("\n{:<30} {:>10} {:>10} {:>10}".format("Metric", "Wins", "Losses", "Diff"))
print("-" * 65)
for name, key in metrics:
    w_vals = [t[key] for t in wins]
    l_vals = [t[key] for t in losses]
    w_mean = np.mean(w_vals) if w_vals else 0
    l_mean = np.mean(l_vals) if l_vals else 0
    diff = l_mean - w_mean
    flag = " ***" if abs(diff) > 0.3 * max(abs(w_mean), 0.01) else ""
    print("{:<30} {:>10.1f} {:>10.1f} {:>+9.1f}{}".format(name, w_mean, l_mean, diff, flag))

# Check specific filters
print("\n" + "=" * 60)
print("  POTENTIAL FILTERS")
print("=" * 60)

# Formation range thresholds
for threshold in [8, 10, 12, 14, 16]:
    filtered_wins = [t for t in wins if t["rng"] <= threshold]
    filtered_losses = [t for t in losses if t["rng"] <= threshold]
    total = len(filtered_wins) + len(filtered_losses)
    wr = len(filtered_wins) / total * 100 if total > 0 else 0
    print("Formation range <= {:.0f}p: {} trades, WR={:.0f}% (W:{} L:{})".format(
        threshold, total, wr, len(filtered_wins), len(filtered_losses)))

print()

# Previous day range thresholds
for threshold in [30, 40, 50, 60, 80]:
    filtered_wins = [t for t in wins if t["prev_range"] <= threshold]
    filtered_losses = [t for t in losses if t["prev_range"] <= threshold]
    total = len(filtered_wins) + len(filtered_losses)
    wr = len(filtered_wins) / total * 100 if total > 0 else 0
    print("Prev day range <= {:.0f}p: {} trades, WR={:.0f}% (W:{} L:{})".format(
        threshold, total, wr, len(filtered_wins), len(filtered_losses)))

print()

# Trading range at time of entry (proxy: formation range)
# Max drift up thresholds
for threshold in [6, 8, 10, 12, 15]:
    filtered_wins = [t for t in wins if t["max_up"] <= threshold]
    filtered_losses = [t for t in losses if t["max_up"] <= threshold]
    total = len(filtered_wins) + len(filtered_losses)
    wr = len(filtered_wins) / total * 100 if total > 0 else 0
    print("Max upward drift <= {:.0f}p: {} trades, WR={:.0f}% (W:{} L:{})".format(
        threshold, total, wr, len(filtered_wins), len(filtered_losses)))

print()

# Formation direction (did price drift up during formation?)
for threshold in [-1, 0, 1, 2]:
    filtered_wins = [t for t in wins if t["form_dir"] <= threshold]
    filtered_losses = [t for t in losses if t["form_dir"] <= threshold]
    total = len(filtered_wins) + len(filtered_losses)
    wr = len(filtered_wins) / total * 100 if total > 0 else 0
    print("Formation direction <= {:+.0f}p: {} trades, WR={:.0f}% (W:{} L:{})".format(
        threshold, total, wr, len(filtered_wins), len(filtered_losses)))

# Chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 3, figsize=(18, 10))
fig.suptitle("Thursday SHORT — What Distinguishes Losses from Wins?", fontsize=13, fontweight="bold")

w_color = "#4CAF50"
l_color = "#F44336"

# 1. Formation range
ax = axes[0][0]
ax.bar([str(t["d"])[5:] for t in wins], [t["rng"] for t in wins], color=w_color, alpha=0.7, label="Wins")
ax.bar([str(t["d"])[5:] for t in losses], [t["rng"] for t in losses], color=l_color, alpha=0.7, label="Losses")
ax.set_title("Formation Range (pips)")
ax.legend(fontsize=8)
ax.tick_params(labelsize=6, rotation=45)
ax.grid(True, alpha=0.2)

# 2. Max upward drift
ax = axes[0][1]
w_ups = [t["max_up"] for t in wins]
l_ups = [t["max_up"] for t in losses]
ax.hist(w_ups, bins=10, alpha=0.6, color=w_color, label="Wins ({:.0f} avg)".format(np.mean(w_ups)))
ax.hist(l_ups, bins=10, alpha=0.6, color=l_color, label="Losses ({:.0f} avg)".format(np.mean(l_ups)))
ax.set_title("Max Upward Drift (pips)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.2)

# 3. Trading range
ax = axes[0][2]
w_tr = [t["trd_rng"] for t in wins]
l_tr = [t["trd_rng"] for t in losses]
ax.hist(w_tr, bins=10, alpha=0.6, color=w_color, label="Wins ({:.0f} avg)".format(np.mean(w_tr)))
ax.hist(l_tr, bins=10, alpha=0.6, color=l_color, label="Losses ({:.0f} avg)".format(np.mean(l_tr)))
ax.set_title("Trading Window Range (pips)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.2)

# 4. Previous day range
ax = axes[1][0]
w_pr = [t["prev_range"] for t in wins]
l_pr = [t["prev_range"] for t in losses]
ax.hist(w_pr, bins=10, alpha=0.6, color=w_color, label="Wins ({:.0f} avg)".format(np.mean(w_pr)))
ax.hist(l_pr, bins=10, alpha=0.6, color=l_color, label="Losses ({:.0f} avg)".format(np.mean(l_pr)))
ax.set_title("Previous Day H1 Range (pips)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.2)

# 5. Formation direction
ax = axes[1][1]
w_fd = [t["form_dir"] for t in wins]
l_fd = [t["form_dir"] for t in losses]
ax.hist(w_fd, bins=10, alpha=0.6, color=w_color, label="Wins ({:+.1f} avg)".format(np.mean(w_fd)))
ax.hist(l_fd, bins=10, alpha=0.6, color=l_color, label="Losses ({:+.1f} avg)".format(np.mean(l_fd)))
ax.set_title("Formation Direction (pips from open)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.2)

# 6. Formation volume
ax = axes[1][2]
w_fv = [t["form_vol"] for t in wins]
l_fv = [t["form_vol"] for t in losses]
ax.hist(w_fv, bins=10, alpha=0.6, color=w_color, label="Wins ({:.0f} avg)".format(np.mean(w_fv)))
ax.hist(l_fv, bins=10, alpha=0.6, color=l_color, label="Losses ({:.0f} avg)".format(np.mean(l_fv)))
ax.set_title("Formation Volume (avg per bar)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.2)

plt.tight_layout()
outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtests", "charts", "asian_gravity_loss_analysis.png")
plt.savefig(outpath, dpi=150, bbox_inches="tight")
plt.close()
print("\nChart saved: {}".format(outpath))

mt5.shutdown()
