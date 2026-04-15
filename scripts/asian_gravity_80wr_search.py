"""Search for 80%+ WR configs on 8 months of VPS M5 data."""
import sys, os
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))
rates = mt5.copy_rates_from_pos("EURGBP", mt5.TIMEFRAME_M5, 0, 50000)
pip = 0.0001; spread = 1.0

sessions = {}
for r in rates:
    ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
    if ts.weekday() >= 5 or ts.hour >= 6: continue
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

first_d = min(sessions); last_d = max(sessions)
print("Data: {} to {}, {} sessions".format(first_d, last_d, len(sessions)))

def simulate(trigger, target, stop, max_range, days, min_hour=2):
    trades = []
    for d in sorted(sessions):
        s = sessions[d]
        if s["wd"] not in days or s["range"] > max_range or s["range"] < 1: continue
        so = s["open"]
        trading = [b for b in s["bars"] if b["h"] >= min_hour and b["h"] < 6]
        ot = None; done = False
        for b in trading:
            if done: continue
            if ot:
                ep, tp, sl_p = ot
                if b["lo"] <= sl_p:
                    trades.append((d, (sl_p-ep)/pip-spread, "SL")); done=True; continue
                if b["hi"] >= tp:
                    trades.append((d, (tp-ep)/pip-spread, "TP")); done=True; continue
            else:
                if b["lo"] <= so - trigger*pip:
                    ep = so - trigger*pip
                    ot = (ep, ep+target*pip, ep-stop*pip)
        if ot and not done:
            last = trading[-1] if trading else s["bars"][-1]
            trades.append((d, (last["cl"]-ot[0])/pip-spread, "TIME"))
    return trades

print("\n=== SEARCHING FOR 80%+ WR WITH 5+ TRADES ===\n")
print("{:<55} {:>4} {:>5} {:>6} {:>7} {:>7}".format("Config", "N", "WR", "PF", "Exp", "Tot"))
print("-" * 90)

results = []
for trigger in [2, 3, 4, 5, 7]:
    for target in [2, 3, 4, 5]:
        for stop in [4, 5, 6, 8, 10, 15]:
            for max_range in [8, 10, 12, 15, 20, 25, 30]:
                for min_h in [2, 3, 4]:
                    for ds, dl in [
                        ([0], "Mon"), ([1], "Tue"), ([2], "Wed"),
                        ([3], "Thu"), ([4], "Fri"),
                        ([0,4], "Mo+Fr"), ([1,3], "Tu+Th"),
                        ([2,4], "We+Fr"), ([0,2,4], "MWF"),
                        ([1,2,3], "TuWTh"), ([0,1,2,3,4], "All"),
                    ]:
                        trades = simulate(trigger, target, stop, max_range, ds, min_h)
                        if len(trades) < 5: continue
                        pnls = [t[1] for t in trades]
                        w = sum(1 for p in pnls if p > 0)
                        wr = w / len(trades) * 100
                        if wr < 80: continue
                        gp = sum(p for p in pnls if p > 0)
                        gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
                        pf = gp / gl
                        eq = np.cumsum(pnls)
                        dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
                        h_label = "" if min_h == 2 else " h>{}".format(min_h)
                        results.append({
                            "wr": wr, "pf": pf, "n": len(trades),
                            "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd,
                            "label": "T{}/T{}/S{} rng<{} {} {}".format(
                                trigger, target, stop, max_range, dl, h_label),
                            "trig": trigger, "tgt": target, "sl": stop,
                            "mr": max_range, "days": dl, "min_h": min_h,
                        })

results.sort(key=lambda x: (-x["wr"], -x["tot"], -x["n"]))

seen = set(); ct = 0
for r in results:
    if ct >= 40: break
    if r["label"] in seen: continue
    seen.add(r["label"])
    f = " ***" if r["wr"] >= 90 else " **" if r["wr"] >= 80 else ""
    print("{:<55} {:>4} {:>4.0f}% {:>6.2f} {:>+6.2f}p {:>+6.1f}p{}".format(
        r["label"], r["n"], r["wr"], r["pf"], r["exp"], r["tot"], f))
    ct += 1

# Detail the best one
if results:
    best = results[0]
    print("\n=== BEST CONFIG DETAILS ===")
    print(best["label"])
    trades = simulate(best["trig"], best["tgt"], best["sl"], best["mr"],
                      [{"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Mo+Fr":-1,"Tu+Th":-1,
                        "We+Fr":-1,"MWF":-1,"TuWTh":-1,"All":-1}.get(best["days"], 0)],
                      best["min_h"])
    # This won't work for multi-day, let me just print summary
    print("  Trades: {}, WR: {:.0f}%, PF: {:.2f}".format(best["n"], best["wr"], best["pf"]))
    print("  Total: {:+.1f}p, MaxDD: {:.1f}p".format(best["tot"], best["dd"]))

n90 = sum(1 for r in results if r["wr"] >= 90)
n80 = sum(1 for r in results if 80 <= r["wr"] < 90)
print("\nFound: {} at 90%+, {} at 80-89%".format(n90, n80))

mt5.shutdown()
