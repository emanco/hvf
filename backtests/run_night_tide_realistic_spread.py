"""NIGHT_TIDE backtest at REALISTIC IC Markets spreads.

Original v2 backtest claimed PF 3.03 / 75% WR using 1.3-1.7p fixed spreads.
Live cross-pair spreads at 22-01 UTC are routinely 3-8p. This script
re-runs the same strategy across spread assumptions {1.5, 3.0, 5.0, 7.0}p
to see how much PF survives.

Strategy:
- BB(20,2) + RSI(14) on M15
- LONG when close < bb_lower AND rsi < 30
- SHORT when close > bb_upper AND rsi > 70
- TP at bb_mid (20-SMA), SL = 12 pips
- Window: 22:00-01:00 UTC (M15 bar starting in window)
- Max hold: 16 bars (= 4h)
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
PIP = 0.0001
SL_PIPS = 12
MAX_HOLD_BARS = 16
RSI_UPPER = 70
RSI_LOWER = 30
BB_PERIOD = 20
BB_STD = 2
RSI_PERIOD = 14
PAIRS = ["AUDCAD", "AUDNZD", "NZDCAD", "EURCHF"]
WINDOW_START_HOUR = 22
WINDOW_END_HOUR = 1   # exclusive (window is 22:00-01:00 UTC)


def load(symbol):
    df = pd.read_csv(ROOT / f"data/{symbol}_M15.csv")
    if "time" in df.columns:
        # Try datetime-string parse first; fall back to broker-time epoch.
        try:
            df["utc_t"] = pd.to_datetime(df["time"], utc=True)
        except (ValueError, TypeError):
            df["utc_t"] = df["time"].astype(int).apply(
                lambda t: datetime.fromtimestamp(t, tz=timezone.utc) - timedelta(hours=3)
            )
    df = df.sort_values("utc_t").reset_index(drop=True)
    return df


def add_indicators(df):
    sma = df["close"].rolling(BB_PERIOD).mean()
    std = df["close"].rolling(BB_PERIOD).std()
    df["bb_mid"] = sma
    df["bb_upper"] = sma + BB_STD * std
    df["bb_lower"] = sma - BB_STD * std
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def in_window(t):
    h = t.hour
    return h >= WINDOW_START_HOUR or h < WINDOW_END_HOUR


def simulate(df, spread_pips):
    trades = []
    in_pos = False
    pos_dir = None; entry = None; tp = None; sl = None; bars_held = 0
    for i, b in df.iterrows():
        if pd.isna(b["bb_mid"]) or pd.isna(b["rsi"]):
            continue
        if in_pos:
            bars_held += 1
            hi, lo = b["high"], b["low"]
            done = False
            # SL-first conservative
            if pos_dir == "L":
                if lo <= sl:
                    pnl = (sl - entry) / PIP - spread_pips
                    trades.append({"d": b["utc_t"], "pnl": pnl, "x": "SL"})
                    done = True
                elif hi >= tp:
                    pnl = (tp - entry) / PIP - spread_pips
                    trades.append({"d": b["utc_t"], "pnl": pnl, "x": "TP"})
                    done = True
            else:
                # SHORT exits BUY at the ask (=bid+spread): SL triggers at
                # ask>=SL (bid>=SL-spread), TP at ask<=TP (bid<=TP-spread).
                # Raw-bid triggers booked near-miss short TPs as wins (the same
                # spread-blind bug fixed in ASB). pnl already nets spread_pips,
                # so this is a selection-only fix (no double counting).
                spread_price = spread_pips * PIP
                if hi >= sl - spread_price:
                    pnl = (entry - sl) / PIP - spread_pips
                    trades.append({"d": b["utc_t"], "pnl": pnl, "x": "SL"})
                    done = True
                elif lo <= tp - spread_price:
                    pnl = (entry - tp) / PIP - spread_pips
                    trades.append({"d": b["utc_t"], "pnl": pnl, "x": "TP"})
                    done = True
            if not done and bars_held >= MAX_HOLD_BARS:
                close_p = b["close"]
                pnl = ((close_p - entry) if pos_dir == "L" else (entry - close_p)) / PIP - spread_pips
                trades.append({"d": b["utc_t"], "pnl": pnl, "x": "TIME"})
                done = True
            if done:
                in_pos = False
                continue
        # Entry check (only in window)
        if not in_pos and in_window(b["utc_t"]):
            close_p = b["close"]
            if close_p < b["bb_lower"] and b["rsi"] < RSI_LOWER:
                in_pos = True; pos_dir = "L"
                entry = close_p
                tp = b["bb_mid"]
                sl = entry - SL_PIPS * PIP
                bars_held = 0
            elif close_p > b["bb_upper"] and b["rsi"] > RSI_UPPER:
                in_pos = True; pos_dir = "S"
                entry = close_p
                tp = b["bb_mid"]
                sl = entry + SL_PIPS * PIP
                bars_held = 0
    return trades


def stats(trades):
    if not trades: return None
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls); wins = (pnls > 0).sum()
    gp = pnls[pnls > 0].sum() if wins else 0
    gl = abs(pnls[pnls <= 0].sum()) if (pnls <= 0).sum() else 0.001
    eq = np.cumsum(pnls)
    dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0
    tps = sum(1 for t in trades if t["x"] == "TP")
    sls = sum(1 for t in trades if t["x"] == "SL")
    tms = sum(1 for t in trades if t["x"] == "TIME")
    return {"n": n, "wr": wins/n*100, "pf": gp/gl, "tot": pnls.sum(),
            "dd": dd, "eq": eq, "tps": tps, "sls": sls, "tms": tms,
            "dates": [pd.Timestamp(t["d"]) for t in trades]}


def main():
    print("Loading + computing indicators...")
    bars = {}
    for sym in PAIRS:
        df = load(sym)
        df = add_indicators(df)
        bars[sym] = df
        period = f"{df['utc_t'].iloc[0].date()} to {df['utc_t'].iloc[-1].date()}"
        print(f"  {sym}: {len(df)} M15 bars, {period}")

    spreads = [1.5, 3.0, 5.0, 7.0]
    print()

    # Aggregate across all 4 pairs
    print(f"{'Spread':<8} {'N':>4} {'WR':>5} {'PF':>5} {'Total':>9} {'Avg':>7} {'DD':>7} {'TP':>4} {'SL':>4} {'TIME':>5}")
    print("-"*80)
    all_results = {}
    for sp in spreads:
        all_trades = []
        for sym in PAIRS:
            tr = simulate(bars[sym], sp)
            all_trades.extend(tr)
        s = stats(all_trades)
        all_results[sp] = s
        print(f"{sp:>4.1f}p  {s['n']:>4} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
              f"{s['tot']:>+8.1f}p {s['tot']/s['n']:>+6.1f}p {s['dd']:>6.1f}p "
              f"{s['tps']:>4} {s['sls']:>4} {s['tms']:>5}")

    print("\nPer-pair @ 3.0p spread (realistic):")
    print(f"{'Pair':<8} {'N':>4} {'WR':>5} {'PF':>5} {'Total':>9} {'DD':>6}")
    print("-"*50)
    for sym in PAIRS:
        tr = simulate(bars[sym], 3.0)
        s = stats(tr)
        if s:
            print(f"{sym:<8} {s['n']:>4} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
                  f"{s['tot']:>+8.1f}p {s['dd']:>5.0f}p")

    # Plot
    fig, ax = plt.subplots(figsize=(13, 7))
    colors = {1.5: "#2ca02c", 3.0: "#1f77b4", 5.0: "#ff7f0e", 7.0: "#d62728"}
    for sp in spreads:
        s = all_results[sp]
        ax.plot(s["dates"], s["eq"],
                label=f"Spread {sp}p — N={s['n']} PF={s['pf']:.2f} "
                      f"Tot={s['tot']:+.0f}p WR={s['wr']:.0f}%",
                color=colors[sp], lw=1.8)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("NIGHT_TIDE backtest at varying spread assumptions\n"
                 "(BB+RSI mean-reversion, M15, 22-01 UTC, 4 cross pairs aggregated)")
    ax.set_ylabel("Cumulative pips (after spread cost)")
    ax.set_xlabel("Date")
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    out = ROOT / "charts/night_tide_realistic_spread.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
