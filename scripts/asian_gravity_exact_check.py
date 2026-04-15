"""Check the exact 100% WR config on VPS M5 data."""
import sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
pip = 0.0001
spread = 1.0

sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5 or ts.hour >= 6:
        continue
    bd = ts.date()
    if bd not in sessions:
        sessions[bd] = {"wd": ts.weekday(), "bars": []}
    sessions[bd]["bars"].append({"h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})

for s in sessions.values():
    form = [b for b in s["bars"] if b["h"] < 2]
    if form:
        s["open"] = s["bars"][0]["o"]
        s["range"] = (max(b["hi"] for b in form) - min(b["lo"] for b in form)) / pip
    else:
        s["range"] = 999

# Test multiple configs
configs = [
    ("Wed T3/T2/S4 rng<10", 3, 2, 4, 10, [2]),
    ("Wed T3/T3/S4 rng<10", 3, 3, 4, 10, [2]),
    ("Wed T3/T4/S4 rng<10", 3, 4, 4, 10, [2]),
    ("Wed T3/T2/S4 rng<15", 3, 2, 4, 15, [2]),
    ("Wed T3/T2/S4 rng<20", 3, 2, 4, 20, [2]),
    ("Wed T2/T2/S4 rng<10", 2, 2, 4, 10, [2]),
    ("Wed T2/T2/S4 rng<15", 2, 2, 4, 15, [2]),
    ("Wed T2/T2/S4 rng<20", 2, 2, 4, 20, [2]),
    ("All T3/T2/S4 rng<10", 3, 2, 4, 10, [0,1,2,3,4]),
    ("All T2/T2/S4 rng<10", 2, 2, 4, 10, [0,1,2,3,4]),
    ("All T2/T2/S4 rng<15", 2, 2, 4, 15, [0,1,2,3,4]),
    ("All T2/T3/S6 rng<15", 2, 3, 6, 15, [0,1,2,3,4]),
    ("All T2/T3/S6 rng<20", 2, 3, 6, 20, [0,1,2,3,4]),
    ("Fri T2/T3/S6 rng<20", 2, 3, 6, 20, [4]),
]

for label, trigger, target, stop, max_range, days in configs:
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if s["wd"] not in days or s["range"] > max_range or s["range"] < 1:
            continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= 2]
        ot = None
        done = False
        for b in trading:
            if done:
                continue
            if ot:
                ep, tp, sl_p = ot
                if b["lo"] <= sl_p:
                    trades.append({"d": d, "pnl": (sl_p - ep) / pip - spread, "x": "SL"})
                    done = True
                    continue
                if b["hi"] >= tp:
                    trades.append({"d": d, "pnl": (tp - ep) / pip - spread, "x": "TP"})
                    done = True
                    continue
            else:
                if b["lo"] <= so - trigger * pip:
                    ep = so - trigger * pip
                    ot = (ep, ep + target * pip, ep - stop * pip)
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            trades.append({"d": d, "pnl": (last["cl"] - ot[0]) / pip - spread, "x": "TIME"})

    if not trades:
        print("{:<35} {:>4} trades".format(label, 0))
        continue
    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(trades) * 100
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
    print("{:<35} {:>4}T  WR={:>4.0f}%  PF={:>5.2f}  Tot={:>+6.1f}p".format(
        label, len(trades), wr, gp / gl, sum(pnls)))

# Detail the Wed T3/T2/S4 rng<10 trades
print("\n--- Detail: Wed T3/T2/S4 rng<10 ---")
for d in sorted(sessions):
    s = sessions[d]
    if s["wd"] != 2:
        continue
    status = "SKIP rng={:.0f}p".format(s["range"]) if s["range"] > 10 else "rng={:.0f}p".format(s["range"])
    if s["range"] > 10 or s["range"] < 1:
        print("  {} {}".format(d, status))
        continue
    so = s["open"]
    trading = [b for b in s["bars"] if b["h"] >= 2]
    trigger_price = so - 3 * pip
    triggered = False
    for idx, b in enumerate(trading):
        if b["lo"] <= trigger_price:
            triggered = True
            ep = trigger_price
            tp = ep + 2 * pip
            sl = ep - 4 * pip
            hit = "NONE"
            for b2 in trading[idx + 1:]:
                if b2["lo"] <= sl:
                    hit = "SL"
                    break
                if b2["hi"] >= tp:
                    hit = "TP"
                    break
            if hit == "NONE":
                last_cl = trading[-1]["cl"]
                pnl = (last_cl - ep) / pip - spread
                hit = "TIME pnl={:+.1f}p".format(pnl)
            elif hit == "TP":
                pnl = 2 - spread
                hit = "TP pnl={:+.1f}p".format(pnl)
            else:
                pnl = -4 - spread
                hit = "SL pnl={:+.1f}p".format(pnl)
            print("  {} rng={:.0f}p  ENTRY  {}".format(d, s["range"], hit))
            break
    if not triggered:
        print("  {} rng={:.0f}p  NO TRIGGER".format(d, s["range"]))

mt5.shutdown()
