"""
London Breakout Strategy — Backtest

Trade the breakout of the Asian session range at London open.
- Mark Asian high/low (00:00-07:00 UTC)
- At 08:00 UTC, enter on breakout above/below the range
- SL at opposite side of range
- TP at 1.5x range width
- Close by 20:00 UTC if neither TP nor SL hit
- Filter: skip if Asian range > X pips or < Y pips

Uses H1 data from MT5.
"""
import sys, os
from datetime import datetime, timedelta, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mt5.initialize()
mt5.login(int(os.getenv("MT5_LOGIN")), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER"))

PAIRS = ["GBPUSD", "EURUSD"]
PIP_VALUES = {"GBPUSD": 0.0001, "EURUSD": 0.0001, "GBPJPY": 0.01}

for symbol in PAIRS:
    pip = PIP_VALUES[symbol]
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 50000)
    if rates is None or len(rates) == 0:
        print("{}: no data".format(symbol))
        continue

    first = datetime.fromtimestamp(rates[0][0], tz=timezone.utc)
    last = datetime.fromtimestamp(rates[-1][0], tz=timezone.utc)
    print("\n{}".format("=" * 70))
    print("  {} — London Breakout Backtest".format(symbol))
    print("  {} to {} ({} H1 bars)".format(first.date(), last.date(), len(rates)))
    print("=" * 70)

    # Build daily sessions
    sessions = {}
    for r in rates:
        ts = datetime.fromtimestamp(r[0], tz=timezone.utc)
        if ts.weekday() >= 5:
            continue
        bd = ts.date()
        if bd not in sessions:
            sessions[bd] = {"bars": []}
        sessions[bd]["bars"].append({
            "h": ts.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4],
        })

    def simulate(max_range, min_range, tp_mult, exit_hour, spread_pips):
        trades = []
        for d in sorted(sessions):
            s = sessions[d]
            # Asian range: 00:00-07:00 UTC
            asian = [b for b in s["bars"] if b["h"] < 7]
            if len(asian) < 3:
                continue
            a_high = max(b["hi"] for b in asian)
            a_low = min(b["lo"] for b in asian)
            a_range = (a_high - a_low) / pip
            if a_range > max_range or a_range < min_range:
                continue

            # London session bars (08:00 onwards)
            london = [b for b in s["bars"] if 8 <= b["h"] < exit_hour]
            if not london:
                continue

            # Check for breakout
            tp_dist = a_range * tp_mult * pip
            spread = spread_pips * pip
            traded = False

            for b in london:
                if traded:
                    break

                # Breakout ABOVE Asian high — LONG
                if b["hi"] > a_high + spread:
                    entry = a_high + spread
                    sl = a_low - spread
                    tp = entry + tp_dist
                    risk = (entry - sl) / pip

                    # Check SL/TP in remaining bars
                    remaining = [bb for bb in london if bb["h"] >= b["h"]]
                    hit = None
                    for rb in remaining:
                        if rb["lo"] <= sl:
                            hit = "SL"
                            pnl = -risk - spread_pips
                            break
                        if rb["hi"] >= tp:
                            hit = "TP"
                            pnl = (tp - entry) / pip - spread_pips
                            break
                    if hit is None:
                        # Time exit
                        last_cl = remaining[-1]["cl"] if remaining else b["cl"]
                        pnl = (last_cl - entry) / pip - spread_pips
                        hit = "TIME"

                    trades.append({"d": d, "dir": "LONG", "pnl": pnl, "x": hit,
                                   "rng": a_range, "risk": risk})
                    traded = True

                # Breakout BELOW Asian low — SHORT
                elif b["lo"] < a_low - spread:
                    entry = a_low - spread
                    sl = a_high + spread
                    tp = entry - tp_dist
                    risk = (sl - entry) / pip

                    remaining = [bb for bb in london if bb["h"] >= b["h"]]
                    hit = None
                    for rb in remaining:
                        if rb["hi"] >= sl:
                            hit = "SL"
                            pnl = -risk - spread_pips
                            break
                        if rb["lo"] <= tp:
                            hit = "TP"
                            pnl = (entry - tp) / pip - spread_pips
                            break
                    if hit is None:
                        last_cl = remaining[-1]["cl"] if remaining else b["cl"]
                        pnl = (entry - last_cl) / pip - spread_pips
                        hit = "TIME"

                    trades.append({"d": d, "dir": "SHORT", "pnl": pnl, "x": hit,
                                   "rng": a_range, "risk": risk})
                    traded = True

        return trades

    def stats(trades):
        if not trades:
            return None
        pnls = [t["pnl"] for t in trades]
        w = sum(1 for p in pnls if p > 0)
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p <= 0)) or 0.001
        eq = np.cumsum(pnls)
        dd = max(np.maximum.accumulate(eq) - eq) if len(eq) > 1 else 0
        return {"n": len(trades), "wr": w/len(trades)*100, "pf": gp/gl,
                "exp": np.mean(pnls), "tot": sum(pnls), "dd": dd}

    # Parameter sweep
    print("\n{:<45} {:>4} {:>5} {:>7} {:>7} {:>7} {:>6}".format(
        "Config", "N", "WR", "PF", "Exp", "Tot", "DD"))
    print("-" * 90)

    results = []
    for max_rng in [20, 30, 40, 50, 80]:
        for min_rng in [10, 15, 20]:
            if min_rng >= max_rng:
                continue
            for tp_mult in [1.0, 1.5, 2.0]:
                for exit_h in [17, 20]:
                    for spread in [1.0, 1.5]:
                        trades = simulate(max_rng, min_rng, tp_mult, exit_h, spread)
                        if len(trades) < 20:
                            continue
                        s = stats(trades)
                        if s["pf"] < 0.5:
                            continue
                        results.append((s, max_rng, min_rng, tp_mult, exit_h, spread))

    results.sort(key=lambda x: (-x[0]["pf"], -x[0]["tot"]))

    seen = set()
    ct = 0
    for s, mr, mnr, tp, ex, sp in results:
        if ct >= 20:
            break
        lab = "rng {}-{} TP={}x exit@{} sprd={}".format(mnr, mr, tp, ex, sp)
        if lab in seen:
            continue
        seen.add(lab)
        f = " ***" if s["pf"] > 1.3 else " **" if s["pf"] > 1.0 else ""
        print("{:<45} {:>4} {:>4.0f}% {:>7.2f} {:>+6.1f}p {:>+6.0f}p {:>5.0f}p{}".format(
            lab, s["n"], s["wr"], s["pf"], s["exp"], s["tot"], s["dd"], f))
        ct += 1

    # Best config detail
    if results and results[0][0]["pf"] > 1.0:
        best = results[0]
        s, mr, mnr, tp, ex, sp = best
        print("\nBEST: rng {}-{}, TP={}x, exit@{}, spread={}".format(mnr, mr, tp, ex, sp))
        print("  {} trades, WR={:.0f}%, PF={:.2f}, Total={:+.0f}p, DD={:.0f}p".format(
            s["n"], s["wr"], s["pf"], s["tot"], s["dd"]))

        # Yearly breakdown
        trades = simulate(mr, mnr, tp, ex, sp)
        yearly = {}
        for t in trades:
            yr = t["d"].year
            if yr not in yearly:
                yearly[yr] = {"n": 0, "w": 0, "pnl": 0}
            yearly[yr]["n"] += 1
            yearly[yr]["pnl"] += t["pnl"]
            if t["pnl"] > 0:
                yearly[yr]["w"] += 1
        print("\n  Yearly:")
        for yr in sorted(yearly):
            y = yearly[yr]
            wr = y["w"]/y["n"]*100 if y["n"] else 0
            print("    {}: {:>3} trades, WR={:.0f}%, PnL={:+.0f}p".format(yr, y["n"], wr, y["pnl"]))

        # Direction breakdown
        longs = [t for t in trades if t["dir"] == "LONG"]
        shorts = [t for t in trades if t["dir"] == "SHORT"]
        for label, subset in [("LONG", longs), ("SHORT", shorts)]:
            if subset:
                w = sum(1 for t in subset if t["pnl"] > 0)
                print("  {}: {} trades, WR={:.0f}%, PnL={:+.0f}p".format(
                    label, len(subset), w/len(subset)*100, sum(t["pnl"] for t in subset)))

        # Generate equity chart
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        pnls = [t["pnl"] for t in trades]
        eq = np.cumsum(pnls)
        dates = [t["d"] for t in trades]

        fig, ax = plt.subplots(figsize=(16, 6))
        color = "#2196F3" if eq[-1] > 0 else "#F44336"
        ax.plot(dates, eq, color=color, linewidth=1.5)
        ax.fill_between(dates, 0, eq, alpha=0.1, color=color)
        ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)

        for j, t in enumerate(trades):
            if t["x"] == "TP":
                c = "#4CAF50"
            elif t["x"] == "SL":
                c = "#F44336"
            else:
                c = "#FFC107"
            ax.scatter(dates[j], eq[j], color=c, s=8, zorder=5)

        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.set_title("{} London Breakout — rng {}-{}, TP={}x, exit@{}\n{} to {}".format(
            symbol, mnr, mr, tp, ex, first.date(), last.date()),
            fontsize=12, fontweight="bold")
        ax.set_ylabel("Pips", fontsize=10)
        ax.text(0.02, 0.95,
                "WR={:.0f}%  PF={:.2f}  Tot={:+.0f}p  DD={:.0f}p  N={}".format(
                    s["wr"], s["pf"], s["tot"], s["dd"], s["n"]),
                transform=ax.transAxes, fontsize=9, va="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
        ax.grid(True, alpha=0.2)

        plt.tight_layout()
        outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "backtests", "charts")
        os.makedirs(outdir, exist_ok=True)
        outpath = os.path.join(outdir, "london_breakout_{}.png".format(symbol.lower()))
        plt.savefig(outpath, dpi=150, bbox_inches="tight")
        plt.close()
        print("\n  Chart: {}".format(outpath))

mt5.shutdown()
print("\nDone.")
