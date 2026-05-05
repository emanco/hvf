"""Side-by-side backtest of flat TP +12p vs +20p on the live KZ_HUNT trade
sample (117 closed trades since 2026-03-25). Same SL as live (spread-comp).

Outputs:
- Equity curves: ACTUAL vs +12p vs +20p
- Per-trade PnL strips
- Per-symbol totals
- WR/PF/DD stats panel
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
BROKER_OFFSET_HOURS = 3
HOLD_DAYS = 7
TRADES_CSV = ROOT / "data/kz_trades.csv"
OUT_PNG = ROOT / "charts/kz_flat_tp_12_vs_20.png"

TP_LEVELS = [12, 20]


def pip(symbol):
    return 0.01 if "JPY" in symbol else 0.0001


def to_utc(broker_unix):
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def load_bars(symbol):
    f = ROOT / f"data/{symbol}_M30.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["utc_t"] = df["time"].apply(to_utc)
    return df


def simulate_flat_tp(df, opened_at, direction, entry, sl, tp_pips, p, hold_days=HOLD_DAYS):
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return None, "NO_DATA"
    tp_price = entry + tp_pips * p if direction == "LONG" else entry - tp_pips * p
    for _, b in window.iterrows():
        if direction == "LONG":
            if b["low"] <= sl:
                return (sl - entry) / p, "SL"
            if b["high"] >= tp_price:
                return tp_pips, "TP"
        else:
            if b["high"] >= sl:
                return (entry - sl) / p, "SL"
            if b["low"] <= tp_price:
                return tp_pips, "TP"
    last = window.iloc[-1]
    pnl = ((last["close"] - entry) if direction == "LONG" else (entry - last["close"])) / p
    return pnl, "TIME"


def stats(pnls):
    a = np.array(pnls)
    n = len(a)
    if n == 0:
        return None
    wins = (a > 0).sum()
    gp = a[a > 0].sum() if wins else 0
    gl = abs(a[a <= 0].sum()) if (a <= 0).sum() else 0.001
    eq = np.cumsum(a)
    dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0
    return {
        "n": n,
        "wr": wins / n * 100,
        "pf": gp / gl,
        "tot": a.sum(),
        "avg": a.sum() / n,
        "dd": dd,
        "eq": eq,
    }


def main():
    trades = pd.read_csv(TRADES_CSV)
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)
    print(f"Loaded {len(trades)} closed KZ_HUNT trades.\n")

    bar_cache = {}
    actual_pnls = []
    sim_results = {tp: {"pnls": [], "outcomes": [], "sym": [], "ids": []} for tp in TP_LEVELS}
    actual_meta = {"sym": [], "ids": []}

    for _, t in trades.iterrows():
        sym = t["symbol"]
        if sym not in bar_cache:
            bar_cache[sym] = load_bars(sym)
        df = bar_cache[sym]
        if df is None:
            continue
        p = pip(sym)
        actual = t["pnl_pips"] if pd.notna(t["pnl_pips"]) else 0

        valid = True
        per_tp = {}
        for tp in TP_LEVELS:
            res, outcome = simulate_flat_tp(
                df, t["opened_at"].to_pydatetime(), t["direction"],
                t["entry_price"], t["stop_loss"], tp, p,
            )
            if res is None:
                valid = False
                break
            per_tp[tp] = (res, outcome)

        if not valid:
            continue

        actual_pnls.append(actual)
        actual_meta["sym"].append(sym)
        actual_meta["ids"].append(int(t["id"]))
        for tp, (res, outcome) in per_tp.items():
            sim_results[tp]["pnls"].append(res)
            sim_results[tp]["outcomes"].append(outcome)
            sim_results[tp]["sym"].append(sym)
            sim_results[tp]["ids"].append(int(t["id"]))

    s_actual = stats(actual_pnls)
    s = {tp: stats(sim_results[tp]["pnls"]) for tp in TP_LEVELS}

    # Print summary
    print(f"{'Strategy':<20} {'N':>4} {'WR':>5} {'PF':>5} {'Total':>9} {'Avg':>7} {'MaxDD':>7}")
    print("-" * 65)
    print(f"{'ACTUAL (live logic)':<20} {s_actual['n']:>4} "
          f"{s_actual['wr']:>4.0f}% {s_actual['pf']:>5.2f} "
          f"{s_actual['tot']:>+8.1f}p {s_actual['avg']:>+6.1f}p "
          f"{s_actual['dd']:>6.1f}p")
    for tp in TP_LEVELS:
        si = s[tp]
        tps_hit = sum(1 for o in sim_results[tp]["outcomes"] if o == "TP")
        sls_hit = sum(1 for o in sim_results[tp]["outcomes"] if o == "SL")
        times_hit = sum(1 for o in sim_results[tp]["outcomes"] if o == "TIME")
        print(f"{'flat TP @ +' + str(tp) + 'p':<20} {si['n']:>4} "
              f"{si['wr']:>4.0f}% {si['pf']:>5.2f} "
              f"{si['tot']:>+8.1f}p {si['avg']:>+6.1f}p "
              f"{si['dd']:>6.1f}p   "
              f"(TP={tps_hit} SL={sls_hit} TIME={times_hit})")

    # ─── Plot ─────────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(3, 2, height_ratios=[2.5, 1, 1])

    # 1. Equity curves (top, full width)
    ax = fig.add_subplot(gs[0, :])
    ax.plot(s_actual["eq"], label=f"ACTUAL (live logic)  PF={s_actual['pf']:.2f}  "
                                  f"WR={s_actual['wr']:.0f}%  Total={s_actual['tot']:+.0f}p",
            color="#d62728", lw=1.6)
    colors_tp = {12: "#2ca02c", 20: "#1f77b4"}
    for tp in TP_LEVELS:
        si = s[tp]
        ax.plot(si["eq"],
                label=f"flat TP @ +{tp}p  PF={si['pf']:.2f}  "
                      f"WR={si['wr']:.0f}%  Total={si['tot']:+.0f}p",
                color=colors_tp[tp], lw=1.8)
    ax.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_title(
        f"KZ_HUNT exit-policy backtest — {s_actual['n']} trades since 2026-03-25\n"
        f"Simulated on M30 IC Markets bars vs actual live exits"
    )
    ax.set_ylabel("Cumulative pips")
    ax.set_xlabel("Trade #")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(alpha=0.3)

    # 2. Per-trade PnL bars: actual + 12p + 20p (left)
    ax = fig.add_subplot(gs[1, 0])
    x = np.arange(len(actual_pnls))
    ax.bar(x, actual_pnls, color="#d62728", alpha=0.7, label="ACTUAL")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Per-trade PnL: ACTUAL")
    ax.set_xlabel("Trade #"); ax.set_ylabel("Pips")
    ax.grid(alpha=0.3, axis="y")

    # 3. Per-trade PnL bars: 12p
    ax = fig.add_subplot(gs[1, 1])
    pnls_12 = sim_results[12]["pnls"]
    colors = ["#2ca02c" if p > 0 else "#d62728" for p in pnls_12]
    ax.bar(np.arange(len(pnls_12)), pnls_12, color=colors, alpha=0.85)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Per-trade PnL: flat TP @ +12p")
    ax.set_xlabel("Trade #"); ax.set_ylabel("Pips")
    ax.grid(alpha=0.3, axis="y")

    # 4. Per-symbol totals (left)
    ax = fig.add_subplot(gs[2, 0])
    df_act = pd.DataFrame({"sym": actual_meta["sym"], "actual": actual_pnls})
    by_sym_act = df_act.groupby("sym").agg(actual=("actual", "sum"))
    df_12 = pd.DataFrame({"sym": sim_results[12]["sym"], "p12": sim_results[12]["pnls"]})
    by_sym_12 = df_12.groupby("sym").agg(p12=("p12", "sum"))
    df_20 = pd.DataFrame({"sym": sim_results[20]["sym"], "p20": sim_results[20]["pnls"]})
    by_sym_20 = df_20.groupby("sym").agg(p20=("p20", "sum"))
    by_sym = by_sym_act.join(by_sym_12).join(by_sym_20)

    width = 0.27
    xb = np.arange(len(by_sym))
    ax.bar(xb - width, by_sym["actual"], width, color="#d62728", label="ACTUAL")
    ax.bar(xb,         by_sym["p12"],    width, color="#2ca02c", label="+12p")
    ax.bar(xb + width, by_sym["p20"],    width, color="#1f77b4", label="+20p")
    ax.set_xticks(xb)
    ax.set_xticklabels(by_sym.index, rotation=30, fontsize=9)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Total pips by symbol")
    ax.set_ylabel("Pips")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    # 5. Per-trade PnL bars: 20p
    ax = fig.add_subplot(gs[2, 1])
    pnls_20 = sim_results[20]["pnls"]
    colors = ["#2ca02c" if p > 0 else "#d62728" for p in pnls_20]
    ax.bar(np.arange(len(pnls_20)), pnls_20, color=colors, alpha=0.85)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Per-trade PnL: flat TP @ +20p")
    ax.set_xlabel("Trade #"); ax.set_ylabel("Pips")
    ax.grid(alpha=0.3, axis="y")

    plt.suptitle(
        f"Flat TP comparison: +12p vs +20p vs ACTUAL — {s_actual['n']} live KZ_HUNT trades",
        fontsize=13, y=0.995,
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {OUT_PNG}")


if __name__ == "__main__":
    main()
