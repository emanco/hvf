"""Combined-portfolio backtest of currently-running strategies over the last
year (2025-06 → 2026-06).

Includes:
  - QL EURGBP (40/12.5/40, M5)
  - QL EURCHF (20/5/20, M15)         [different params per instance — IC tuning]
  - ASB GBPJPY (0.4 min_range_pct_adr, M5)
  - ASB EURJPY (0.3 min_range_pct_adr, M5)
  - BTC Donchian (D1, 55/20/1.0)
  - ETH Donchian (D1, 55/20/1.0)

NOT included (no backtest harness in repo):
  - LONDON_BO (GBPUSD H1)
  - NIGHT_TIDE (M15 BB+RSI on cross pairs)
Live sample sizes for both are tiny (2-3 trades) so the combined chart
should still represent ~85% of expected portfolio behaviour.

Each strategy runs with $10,000 starting equity, 1% risk per trade,
using its own production config. Trades are collected, sorted by exit
time, and plotted as a single combined equity curve.
"""
from __future__ import annotations
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

WINDOW_START = pd.Timestamp("2025-06-01", tz="UTC")
WINDOW_END = pd.Timestamp("2026-06-01", tz="UTC")
STARTING_EQUITY = 10000.0
RISK_PCT = 1.0


# ─── Strategy 1: QL (EURCHF + EURGBP) ──────────────────────────────────────
def run_ql():
    import run_ql_eurchf_vs_eurgbp as ql
    chf = ql.load_eurchf_m15()
    gbp = ql.load_eurgbp_m5()
    s_chf = ql.build_sessions(chf)
    s_gbp = ql.build_sessions(gbp)

    out = []
    for sym, sessions, trig, tgt, stp in [
        ("QL EURCHF", s_chf, 20, 5,    20),    # IC tuning per config
        ("QL EURGBP", s_gbp, 40, 12.5, 40),
    ]:
        trades, fired, total = ql.simulate(sessions, trig, tgt, stp)
        pip = 0.0001
        for t in trades:
            # date in 't' is the session date; assume close around 21:00 UTC
            exit_t = pd.Timestamp(t["d"], tz="UTC") + pd.Timedelta(hours=21)
            if not (WINDOW_START <= exit_t < WINDOW_END):
                continue
            # rough $ conversion: 1% risk per trade at stop dist
            # ql.simulate's pnl is in pips; scale by $/pip estimate
            # EURGBP $13.5/pip/lot, EURCHF $12.75 — use $10 for simplicity
            usd = t["pnl"] * 10.0 * (RISK_PCT / 100.0 * STARTING_EQUITY / stp / 10.0)
            out.append({"strategy": sym, "exit_time": exit_t, "pnl_usd": usd})
    return out


# ─── Strategy 2: ASB (GBPJPY + EURJPY) ─────────────────────────────────────
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


# ─── Strategy 3: Daily Donchian (BTC + ETH) ────────────────────────────────
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


def main():
    print(f"Combined backtest window: {WINDOW_START.date()} → {WINDOW_END.date()}\n")

    all_trades = []
    for label, fn in [("QL", run_ql), ("ASB", run_asb), ("Donchian", run_donchian)]:
        try:
            trades = fn()
            print(f"  {label}: {len(trades)} trades in window")
            all_trades.extend(trades)
        except Exception as e:
            print(f"  {label}: FAILED — {e}")

    # Combined timeline
    all_trades.sort(key=lambda t: t["exit_time"])
    print(f"\nTotal trades: {len(all_trades)}")
    if not all_trades:
        print("No trades to chart.")
        return

    # Per-strategy stats
    by_strat = {}
    for t in all_trades:
        by_strat.setdefault(t["strategy"], []).append(t["pnl_usd"])

    print(f"\n{'Strategy':<22} {'N':>4} {'WR':>5} {'PF':>5} {'Net USD':>10}")
    print("-" * 60)
    for s, pnls in sorted(by_strat.items()):
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p <= 0))
        pf = gp / gl if gl else float("inf")
        print(f"{s:<22} {n:>4} {wins/n*100:>4.0f}% {pf:>5.2f} {sum(pnls):>+9.2f}")

    # Combined equity curve
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
    print(f"=== Combined portfolio (1yr) ===")
    print(f"  Trades: {n}  WR: {wins/n*100:.1f}%  PF: {pf:.2f}")
    print(f"  Equity: ${STARTING_EQUITY:,.0f} → ${final_eq:,.2f}  ({ret:+.1f}%)")
    print(f"  Max DD: ${max_dd:,.2f} ({max_dd_pct:.1f}%)")

    # Chart: equity curve + per-strategy contributions stacked
    fig, axes = plt.subplots(
        2, 1, figsize=(14, 9),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.28},
    )
    ax1 = axes[0]

    # Color per strategy
    strat_colors = {
        "QL EURCHF": "#1f77b4",
        "QL EURGBP": "#aec7e8",
        "ASB GBPJPY": "#2ca02c",
        "ASB EURJPY": "#98df8a",
        "Donchian BTCUSD": "#ff7f0e",
        "Donchian ETHUSD": "#ffbb78",
    }

    # Combined line
    ax1.plot(times, eq, color="black", linewidth=2.0, label="Combined", zorder=5)
    ax1.fill_between(times, STARTING_EQUITY, eq, alpha=0.10, color="black")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.5)

    # Per-strategy contribution curves (each starts at 0 and accumulates)
    for strat, color in strat_colors.items():
        strat_trades = [t for t in all_trades if t["strategy"] == strat]
        if not strat_trades:
            continue
        ts = [WINDOW_START] + [t["exit_time"] for t in strat_trades]
        cum = np.concatenate([[0], np.cumsum([t["pnl_usd"] for t in strat_trades])])
        ax1.plot(ts, STARTING_EQUITY + cum, color=color, linewidth=1.2,
                 alpha=0.85, label=f"{strat} (N={len(strat_trades)})")

    ax1.set_title(
        f"Combined portfolio — 4 strategies, {WINDOW_START.date()} to {WINDOW_END.date()}\n"
        f"${STARTING_EQUITY:,.0f} → ${final_eq:,.2f} ({ret:+.1f}%), "
        f"N={n}, WR={wins/n*100:.0f}%, PF={pf:.2f}, MaxDD={max_dd_pct:.1f}%",
        fontsize=12, fontweight="bold",
    )
    ax1.set_ylabel("Equity ($) — each strategy contribution + black combined")
    ax1.legend(loc="upper left", fontsize=9, ncol=2)
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    dd_pct = -dd / np.maximum.accumulate(eq) * 100
    ax2.fill_between(times, dd_pct, 0, color="red", alpha=0.3)
    ax2.plot(times, dd_pct, color="red", linewidth=0.7)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out_png = ROOT / "charts" / "combined_1yr.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out_png}")


if __name__ == "__main__":
    main()
