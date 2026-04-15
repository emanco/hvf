"""Asian Gravity M5 parameter sweep on VPS."""
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
pip = 0.0001
spread = 1.0

# Build sessions
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
        s["fh"] = max(b["hi"] for b in form)
        s["fl"] = min(b["lo"] for b in form)
        s["range"] = (s["fh"] - s["fl"]) / pip
    else:
        s["range"] = 999

first_date = min(sessions.keys())
last_date = max(sessions.keys())
print(f"Data: {first_date} to {last_date}, {len(sessions)} sessions")


def simulate(trigger, target, stop, max_range, days):
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
    return trades


print(f"\n{'Config':<50} {'N':>4} {'WR':>5} {'PF':>6} {'Exp':>7} {'Tot':>7} {'DD':>5}")
print("-" * 85)

results = []
for trigger in [2, 3, 4, 5]:
    for target in [2, 3, 4, 5]:
        for stop in [3, 4, 5, 6, 8]:
            for max_range in [10, 12, 15, 20, 25, 30]:
                for ds, dl in [
                    ([2], "Wed"),
                    ([4], "Fri"),
                    ([2, 4], "We+Fr"),
                    ([0, 1, 2, 3, 4], "All"),
                    ([1, 2, 3], "Tu-Th"),
                    ([0, 2, 4], "MoWeFr"),
                ]:
                    trades = simulate(trigger, target, stop, max_range, ds)
                    if len(trades) < 5:
                        continue
                    pnls = [t["pnl"] for t in trades]
                    w = sum(1 for p in pnls if p > 0)
                    gp = sum(p for p in pnls if p > 0)
                    gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
                    eq = np.cumsum(pnls)
                    dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
                    pf = gp / gl
                    wr = w / len(trades) * 100
                    if pf < 0.5:
                        continue
                    results.append({
                        "n": len(trades), "wr": wr, "pf": pf,
                        "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd,
                        "trig": trigger, "tgt": target, "sl": stop,
                        "mr": max_range, "days": dl,
                    })

results.sort(key=lambda x: (-x["pf"], -x["tot"]))

seen = set()
ct = 0
for r in results:
    if ct >= 50:
        break
    lab = "T{trig}/T{tgt}/S{sl} rng<{mr} {days}".format(**r)
    if lab in seen:
        continue
    seen.add(lab)
    f = " ***" if r["pf"] > 1.0 and r["n"] >= 10 else " **" if r["pf"] > 1.0 else ""
    print("{:<50} {:>4} {:>4.0f}% {:>6.2f} {:>+6.2f}p {:>+6.1f}p {:>4.0f}p{}".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"], r["dd"], f))
    ct += 1

# Show best with 10+ trades
print("\n=== BEST WITH 10+ TRADES ===")
best10 = [r for r in results if r["n"] >= 10 and r["pf"] > 1.0]
best10.sort(key=lambda x: -x["tot"])
for r in best10[:15]:
    lab = "T{trig}/T{tgt}/S{sl} rng<{mr} {days}".format(**r)
    print("{:<50} {:>4} {:>4.0f}% {:>6.2f} {:>+6.2f}p {:>+6.1f}p {:>4.0f}p".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"], r["dd"]))

# Show best with 20+ trades
print("\n=== BEST WITH 20+ TRADES ===")
best20 = [r for r in results if r["n"] >= 20 and r["pf"] > 1.0]
best20.sort(key=lambda x: -x["tot"])
for r in best20[:15]:
    lab = "T{trig}/T{tgt}/S{sl} rng<{mr} {days}".format(**r)
    print("{:<50} {:>4} {:>4.0f}% {:>6.2f} {:>+6.2f}p {:>+6.1f}p {:>4.0f}p".format(
        lab, r["n"], r["wr"], r["pf"], r["exp"], r["tot"], r["dd"]))

mt5.shutdown()
print("\nDone.")
