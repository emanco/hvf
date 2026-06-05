"""1-year combined backtest of the CURRENT active strategy book (2025-06 → 2026-06).

Active strategies (post 2026-06-05 changes):
  - QL EURGBP (40/12.5/40, M5)              ← QL EURCHF DISABLED 2026-06-04
  - ASB GBPJPY (0.4 ADR threshold)
  - ASB EURJPY (0.3 ADR threshold)
  - BTC Donchian (55/20/1.0 on D1)
  - ETH Donchian (55/20/1.0 on D1)
  - NR7 Breakout US500 (D1)                 ← added 2026-06-05
  - NR7 Breakout DE40 (D1)                  ← added 2026-06-05

NOT included (no backtest harness in repo):
  - LONDON_BO (GBPUSD H1) — live: 3/3 wins +$104 (tiny N)
  - NIGHT_TIDE (M15 BB+RSI 4 cross pairs) — live: 3 trades flat
The omissions are ~5-10% of expected portfolio activity given live sample.

Each strategy runs with $10,000 starting equity, 1% risk per trade
(NR7 production uses 0.5% but we use 1% here for comparability).
Trades collected, sorted by exit time, plotted as single combined curve.
"""
from __future__ import annotations
import random
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

WINDOW_START = pd.Timestamp("2025-06-05", tz="UTC")
WINDOW_END = pd.Timestamp("2026-06-05", tz="UTC")
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0


# ─── QL EURGBP only (EURCHF disabled in production) ───────────────────────
def run_ql():
    import run_ql_eurchf_vs_eurgbp as ql
    gbp = ql.load_eurgbp_m5()
    s_gbp = ql.build_sessions(gbp)

    out = []
    trades, fired, total = ql.simulate(s_gbp, 40, 12.5, 40)
    for t in trades:
        exit_t = pd.Timestamp(t["d"], tz="UTC") + pd.Timedelta(hours=21)
        if not (WINDOW_START <= exit_t < WINDOW_END):
            continue
        # rough $ conversion: pnl is in pips, EURGBP $13.5/pip/lot
        # 1% risk on $10k = $100 / 40p SL = 0.185 lots × $13.5 = $2.5/pip realized
        usd = t["pnl"] * (RISK_PCT / 100.0 * STARTING_EQUITY / 40.0)
        out.append({"strategy": "QL EURGBP", "exit_time": exit_t, "pnl_usd": usd})
    return out


# ─── ASB (GBPJPY + EURJPY) ─────────────────────────────────────────────────
def run_asb():
    import run_asb_threshold_compare as asbt
    import run_asb_validation as asb
    out = []
    for sym, min_pct in [("GBPJPY", 0.4), ("EURJPY", 0.3)]:
        random.seed(1003)
        equity_ref = [STARTING_EQUITY]
        df = asb.load_m5(sym)
        trades = asbt.simulate_pair_with_thresholds(
            sym, df, equity_ref, min_pct, 1.0, True,
        )
        for t in trades:
            if t.exit_time is None or not (WINDOW_START <= t.exit_time < WINDOW_END):
                continue
            out.append({
                "strategy": f"ASB {sym}",
                "exit_time": t.exit_time,
                "pnl_usd": t.pnl_usd,
            })
    return out


# ─── Donchian (BTC + ETH) ──────────────────────────────────────────────────
def run_donchian():
    import run_crypto_donchian as crypto
    out = []
    for sym, dpp, rt, vmin in crypto.INSTRUMENTS:
        if sym not in ("BTCUSD", "ETHUSD"):
            continue
        d1 = crypto.load_d1(sym)
        trades, _, _ = crypto.simulate(sym, d1, dpp, rt)
        for t in trades:
            if t.exit_time is None or not (WINDOW_START <= t.exit_time < WINDOW_END):
                continue
            out.append({
                "strategy": f"Donchian {sym}",
                "exit_time": t.exit_time,
                "pnl_usd": t.pnl_usd,
            })
    return out


# ─── NR7 Breakout (US500 + DE40) ───────────────────────────────────────────
def run_nr7():
    import run_nr7_indices as nr7
    out = []
    for sym, rt in nr7.INDICES:
        if sym not in ("US500", "DE40"):
            continue
        d1 = nr7.load_d1(sym)
        trades, _ = nr7.nr7_breakout(d1, rt)
        for t in trades:
            if t.exit_time is None or not (WINDOW_START <= t.exit_time < WINDOW_END):
                continue
            out.append({
                "strategy": f"NR7 {sym}",
                "exit_time": t.exit_time,
                "pnl_usd": t.pnl_usd,
            })
    return out


def main():
    print(f"Combined backtest of CURRENT active book")
    print(f"Window: {WINDOW_START.date()} → {WINDOW_END.date()}\n")

    all_trades = []
    for label, fn in [("QL (EURGBP)", run_ql),
                      ("ASB (GBPJPY+EURJPY)", run_asb),
                      ("Donchian (BTC+ETH)", run_donchian),
                      ("NR7 (US500+DE40)", run_nr7)]:
        try:
            trades = fn()
            print(f"  {label}: {len(trades)} trades in window")
            all_trades.extend(trades)
        except Exception as e:
            print(f"  {label}: FAILED — {e}")

    all_trades.sort(key=lambda t: t["exit_time"])
    print(f"\nTotal trades: {len(all_trades)}")
    if not all_trades:
        print("No trades to chart.")
        return

    # Per-strategy stats
    by_strat = {}
    for t in all_trades:
        by_strat.setdefault(t["strategy"], []).append(t["pnl_usd"])

    print(f"\n{'Strategy':<22} {'N':>4} {'WR':>5} {'PF':>5} {'Net USD':>11}")
    print("-" * 60)
    for s, pnls in sorted(by_strat.items()):
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p <= 0))
        pf = gp / gl if gl else float("inf")
        print(f"{s:<22} {n:>4} {wins/n*100:>4.0f}% {pf:>5.2f} {sum(pnls):>+10.2f}")

    times = [WINDOW_START] + [t["exit_time"] for t in all_trades]
    pnls = np.array([t["pnl_usd"] for t in all_trades])
    eq = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(pnls)])
    dd = np.maximum.accumulate(eq) - eq
    max_dd = dd.max() if len(dd) > 1 else 0
    max_dd_pct = (max_dd / np.maximum.accumulate(eq).max()) * 100 if max_dd > 0 else 0
    final_eq = eq[-1]
    ret = (final_eq / STARTING_EQUITY - 1) * 100

    n = len(all_trades)
    wins = sum(1 for t in all_trades if t["pnl_usd"] > 0)
    gp = sum(t["pnl_usd"] for t in all_trades if t["pnl_usd"] > 0)
    gl = abs(sum(t["pnl_usd"] for t in all_trades if t["pnl_usd"] <= 0))
    pf = gp / gl if gl else float("inf")

    print()
    print(f"=== Combined portfolio (1yr, current active book) ===")
    print(f"  Trades: {n}  WR: {wins/n*100:.1f}%  PF: {pf:.2f}")
    print(f"  Equity: ${STARTING_EQUITY:,.0f} → ${final_eq:,.2f}  ({ret:+.1f}%)")
    print(f"  Max DD: ${max_dd:,.2f} ({max_dd_pct:.1f}%)")

    # Per-strategy color palette
    strat_colors = {
        "QL EURGBP":       "#1f77b4",
        "ASB GBPJPY":      "#2ca02c",
        "ASB EURJPY":      "#98df8a",
        "Donchian BTCUSD": "#ff7f0e",
        "Donchian ETHUSD": "#ffbb78",
        "NR7 US500":       "#9467bd",
        "NR7 DE40":        "#c5b0d5",
    }

    fig, axes = plt.subplots(
        2, 1, figsize=(14, 10),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.30},
    )
    ax1 = axes[0]

    # Combined line (bold black)
    ax1.plot(times, eq, color="black", linewidth=2.5, label="Combined", zorder=10)
    ax1.fill_between(times, STARTING_EQUITY, eq, alpha=0.08, color="black")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.5)

    # Per-strategy contribution curves (each starts at $10k baseline)
    for strat, color in strat_colors.items():
        st = [t for t in all_trades if t["strategy"] == strat]
        if not st:
            continue
        ts = [WINDOW_START] + [t["exit_time"] for t in st]
        cum = np.concatenate([[0], np.cumsum([t["pnl_usd"] for t in st])])
        ax1.plot(ts, STARTING_EQUITY + cum, color=color, linewidth=1.3,
                 alpha=0.85, label=f"{strat} (N={len(st)})")

    ax1.set_title(
        f"Current active book — combined 1yr backtest, {WINDOW_START.date()} → {WINDOW_END.date()}\n"
        f"${STARTING_EQUITY:,.0f} → ${final_eq:,.2f} ({ret:+.1f}%) | "
        f"N={n}, WR={wins/n*100:.0f}%, PF={pf:.2f}, MaxDD={max_dd_pct:.1f}%",
        fontsize=12, fontweight="bold",
    )
    ax1.set_ylabel("Equity ($) — each line = per-strategy contribution; black = combined")
    ax1.legend(loc="upper left", fontsize=9, ncol=2)
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    dd_pct_curve = -dd / np.maximum.accumulate(eq) * 100
    ax2.fill_between(times, dd_pct_curve, 0, color="red", alpha=0.3)
    ax2.plot(times, dd_pct_curve, color="red", linewidth=0.8)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out_png = ROOT / "charts" / "current_book_1yr.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out_png}")


if __name__ == "__main__":
    main()
