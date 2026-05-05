"""Combine the top filters from each agent and test their interaction.

Filters tested individually + in combinations:
  A) Score >= 60
  B) Pair in {NZDUSD, CHFJPY, EURGBP}        (PF >= 1.2 subset)
  C) Pair in {NZDUSD, CHFJPY, EURGBP, EURJPY} (PF >= 1.0 subset)
  D) Regime: EMA200-aligned AND ATR(14,M30) NOT in top tercile

Each filter applied to the +12p flat TP simulation on 117 trades.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
BROKER_OFFSET_HOURS = 3
HOLD_DAYS = 7
TP_PIPS = 12

PAIRS_PF_HIGH = {"NZDUSD", "CHFJPY", "EURGBP"}
PAIRS_PF_OK = {"NZDUSD", "CHFJPY", "EURGBP", "EURJPY"}


def pip(s):
    return 0.01 if "JPY" in s else 0.0001


def to_utc(broker_unix):
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


_bar_cache = {}
def load_bars(sym):
    if sym in _bar_cache: return _bar_cache[sym]
    f = ROOT / f"data/{sym}_M30.csv"
    if not f.exists():
        _bar_cache[sym] = None
        return None
    df = pd.read_csv(f)
    df["utc_t"] = df["time"].apply(to_utc)
    _bar_cache[sym] = df
    return df


def simulate_flat_tp(df, opened_at, direction, entry, sl, tp_pips, p):
    end = opened_at + timedelta(days=HOLD_DAYS)
    win = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if win.empty: return None
    tp_price = entry + tp_pips * p if direction == "LONG" else entry - tp_pips * p
    for _, b in win.iterrows():
        if direction == "LONG":
            if b["low"] <= sl: return (sl - entry) / p
            if b["high"] >= tp_price: return tp_pips
        else:
            if b["high"] >= sl: return (entry - sl) / p
            if b["low"] <= tp_price: return tp_pips
    last = win.iloc[-1]
    return ((last["close"] - entry) if direction == "LONG" else (entry - last["close"])) / p


def compute_features(df, opened_at, direction):
    """Compute EMA200-alignment and ATR-tercile flags using bars STRICTLY before opened_at."""
    pre = df[df["utc_t"] < opened_at]
    if len(pre) < 200: return None
    closes = pre["close"].values
    ema200 = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1]
    last_close = closes[-1]
    if direction == "LONG":
        ema_aligned = last_close > ema200
    else:
        ema_aligned = last_close < ema200
    # ATR(14) on M30 — last 14 bars before opened_at
    last14 = pre.tail(15)  # need 15 to compute 14 ATR
    if len(last14) < 15: return None
    tr = np.maximum.reduce([
        (last14["high"] - last14["low"]).values[1:],
        np.abs(last14["high"].values[1:] - last14["close"].values[:-1]),
        np.abs(last14["low"].values[1:]  - last14["close"].values[:-1]),
    ])
    atr = tr.mean()
    return {"ema_aligned": ema_aligned, "atr": atr}


def main():
    trades = pd.read_csv(ROOT / "data/kz_trades_enriched.csv")
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)

    # First pass: compute pnl + features for every trade
    rows = []
    for _, t in trades.iterrows():
        sym = t["symbol"]
        df = load_bars(sym)
        if df is None: continue
        p = pip(sym)
        opened = t["opened_at"].to_pydatetime()
        pnl = simulate_flat_tp(df, opened, t["direction"], t["entry_price"],
                                t["stop_loss"], TP_PIPS, p)
        if pnl is None: continue
        feat = compute_features(df, opened, t["direction"])
        if feat is None: continue
        rows.append({
            "id": int(t["id"]), "symbol": sym, "direction": t["direction"],
            "score": t["score"], "opened_at": opened,
            "pnl": pnl, "ema_aligned": feat["ema_aligned"], "atr": feat["atr"],
        })
    df_out = pd.DataFrame(rows)

    # Compute ATR top-tercile threshold from this dataset (in-sample)
    atr_threshold = df_out["atr"].quantile(2/3)
    df_out["atr_low_mid"] = df_out["atr"] <= atr_threshold
    print(f"ATR top-tercile threshold: {atr_threshold:.5f} (in-sample)\n")

    # Build filter masks
    masks = {
        "BASELINE (no filter)": pd.Series(True, index=df_out.index),
        "A: score>=60": df_out["score"] >= 60,
        "B: pairs PF>=1.2": df_out["symbol"].isin(PAIRS_PF_HIGH),
        "C: pairs PF>=1.0": df_out["symbol"].isin(PAIRS_PF_OK),
        "D: regime (EMA+ATR_low/mid)": df_out["ema_aligned"] & df_out["atr_low_mid"],
        "A+B": (df_out["score"] >= 60) & df_out["symbol"].isin(PAIRS_PF_HIGH),
        "A+C": (df_out["score"] >= 60) & df_out["symbol"].isin(PAIRS_PF_OK),
        "A+D": (df_out["score"] >= 60) & df_out["ema_aligned"] & df_out["atr_low_mid"],
        "B+D": df_out["symbol"].isin(PAIRS_PF_HIGH) & df_out["ema_aligned"] & df_out["atr_low_mid"],
        "C+D": df_out["symbol"].isin(PAIRS_PF_OK) & df_out["ema_aligned"] & df_out["atr_low_mid"],
        "A+B+D": (df_out["score"] >= 60) & df_out["symbol"].isin(PAIRS_PF_HIGH) & df_out["ema_aligned"] & df_out["atr_low_mid"],
        "A+C+D": (df_out["score"] >= 60) & df_out["symbol"].isin(PAIRS_PF_OK) & df_out["ema_aligned"] & df_out["atr_low_mid"],
    }

    def stats(pnls):
        a = np.array(pnls)
        n = len(a)
        if n == 0: return None
        wins = (a > 0).sum()
        gp = a[a > 0].sum() if wins else 0
        gl = abs(a[a <= 0].sum()) if (a <= 0).sum() else 0.001
        eq = np.cumsum(a)
        dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0
        return {"n": n, "wr": wins/n*100, "pf": gp/gl, "tot": a.sum(),
                "avg": a.sum()/n, "dd": dd, "eq": eq, "mar": a.sum()/dd if dd > 0 else 0}

    print(f"{'Filter':<32} {'N':>4} {'WR':>5} {'PF':>5} {'Total':>9} {'Avg':>7} {'MaxDD':>7} {'MAR':>5}")
    print("-" * 85)
    results = {}
    for name, mask in masks.items():
        sub = df_out[mask]
        s = stats(sub["pnl"].tolist())
        if s is None: continue
        results[name] = s
        flag = " ⚠ low N" if s["n"] < 30 else ""
        print(f"{name:<32} {s['n']:>4} {s['wr']:>4.0f}% {s['pf']:>5.2f} "
              f"{s['tot']:>+8.1f}p {s['avg']:>+6.1f}p {s['dd']:>6.1f}p {s['mar']:>5.2f}{flag}")

    # ─── Plot — focus on the meaningful contenders ────────────
    fig, axes = plt.subplots(1, 2, figsize=(16, 8),
                             gridspec_kw={"width_ratios": [3, 1]})
    ax = axes[0]
    headline = [
        ("BASELINE (no filter)",         "#999999", 1.4, "-"),
        ("A: score>=60",                  "#1f77b4", 1.4, "-"),
        ("C: pairs PF>=1.0",              "#17becf", 1.6, "-"),
        ("B: pairs PF>=1.2",              "#2ca02c", 1.4, "-"),
        ("A+C",                           "#d62728", 2.4, "-"),  # winner
        ("A+B",                           "#9467bd", 1.3, "--"),
        ("D: regime (EMA+ATR_low/mid)",   "#ff7f0e", 1.2, ":"),
        ("A+D",                           "#bcbd22", 1.2, ":"),
    ]
    for name, color, lw, ls in headline:
        if name not in results: continue
        s = results[name]
        ax.plot(s["eq"],
                label=f"{name}  •  N={s['n']}, PF={s['pf']:.2f}, "
                      f"Tot={s['tot']:+.0f}p, DD={s['dd']:.0f}p",
                color=color, lw=lw, linestyle=ls)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title(
        f"KZ_HUNT combined-filter equity curves — +12p flat TP, 117 base trades\n"
        f"Winner: A+C (score≥60 + pairs in {{NZDUSD, CHFJPY, EURGBP, EURJPY}})"
    )
    ax.set_ylabel("Cumulative pips")
    ax.set_xlabel("Filtered trade # (within retained subset)")
    ax.legend(fontsize=10, loc="upper left", framealpha=0.9)
    ax.grid(alpha=0.3)

    # Right: stats bar chart
    ax2 = axes[1]
    order = ["BASELINE (no filter)", "A: score>=60", "B: pairs PF>=1.2",
             "C: pairs PF>=1.0", "D: regime (EMA+ATR_low/mid)",
             "A+B", "A+C", "A+D"]
    pf_vals = [results[n]["pf"] for n in order if n in results]
    labels = [n.replace(": ", "\n").replace("(no filter)", "") for n in order if n in results]
    colors = ["#d62728" if n == "A+C" else "#1f77b4" for n in order if n in results]
    bars = ax2.barh(labels, pf_vals, color=colors, edgecolor="black")
    for bar, n in zip(bars, [n for n in order if n in results]):
        s = results[n]
        ax2.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height()/2,
                 f"N={s['n']}\nPF={s['pf']:.2f}\nDD={s['dd']:.0f}p\nMAR={s['mar']:.2f}",
                 va="center", fontsize=8)
    ax2.axvline(1.0, color="black", lw=0.7, linestyle="--")
    ax2.set_xlim(0, 2.1)
    ax2.set_xlabel("Profit Factor")
    ax2.set_title("PF & risk-adj per filter")
    ax2.grid(alpha=0.3, axis="x")
    ax2.invert_yaxis()

    plt.tight_layout()
    out = ROOT / "charts/kz_combined_filter.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
