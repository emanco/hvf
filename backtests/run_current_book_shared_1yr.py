"""Shared-capital 1-year backtest of the current active book.

Difference from run_current_book_1yr.py:
  - Each strategy in that script started at its own $10k baseline. The
    combined chart simply summed each strategy's PnL. This understates
    correlated drawdowns because each strategy's lot sizing was based
    on its OWN growing equity, not shared.
  - This script uses a SINGLE shared equity pool. Every trade is sized
    based on the equity at the moment of entry. Drawdowns realized into
    that pool feed forward into the next trade's sizing.

Methodology:
  1. Run each strategy's existing backtest with the standard $10k baseline
     and 1% risk-per-trade. The output PnL per trade implicitly encodes
     the R-multiple (PnL / $100 risk).
  2. Re-simulate using R-multiples: for each trade in chronological order,
     risk_at_entry = shared_equity × 1%, realized_pnl = R × risk_at_entry.
     Apply the PnL to the shared pool at exit time.
  3. Equity curve is the running sum of realized PnLs. Drawdown is
     measured against the rolling peak of this curve.

Caveat: this captures CORRELATED REALIZED drawdowns (the methodological
fix the previous script lacked) but does NOT capture floating-P&L
drawdowns from open positions simultaneously underwater. In practice
floating DD is typically 1.5-2× realized DD.
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
ORIGINAL_RISK_PER_TRADE = STARTING_EQUITY * RISK_PCT / 100.0  # $100


def _r_multiple(original_pnl_usd: float) -> float:
    """Back out the R-multiple of a trade from its $10k-baseline PnL."""
    return original_pnl_usd / ORIGINAL_RISK_PER_TRADE


# ─── Collect trades from each existing strategy backtest ──────────────────
def collect_trades():
    """Returns: list of {entry_time, exit_time, strategy, r_multiple}."""
    all_trades = []

    # QL EURGBP
    import run_ql_eurchf_vs_eurgbp as ql
    gbp = ql.load_eurgbp_m5()
    s_gbp = ql.build_sessions(gbp)
    trades, _, _ = ql.simulate(s_gbp, 40, 12.5, 40)
    for t in trades:
        exit_t = pd.Timestamp(t["d"], tz="UTC") + pd.Timedelta(hours=21)
        entry_t = pd.Timestamp(t["d"], tz="UTC")  # session date proxy
        if not (WINDOW_START <= exit_t < WINDOW_END):
            continue
        # QL pnl is in pips; orig sizing used $10k/40p stop = 0.185 lots × $13.5 = $2.5/pip
        usd = t["pnl"] * (RISK_PCT / 100.0 * STARTING_EQUITY / 40.0)
        all_trades.append({
            "entry_time": entry_t, "exit_time": exit_t,
            "strategy": "QL EURGBP", "r": _r_multiple(usd),
        })

    # ASB (GBPJPY 0.4, EURJPY 0.3)
    import run_asb_threshold_compare as asbt
    import run_asb_validation as asb
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
            all_trades.append({
                "entry_time": t.entry_time, "exit_time": t.exit_time,
                "strategy": f"ASB {sym}", "r": _r_multiple(t.pnl_usd),
            })

    # Donchian (BTC + ETH)
    import run_crypto_donchian as crypto
    for sym, dpp, rt, vmin in crypto.INSTRUMENTS:
        if sym not in ("BTCUSD", "ETHUSD"):
            continue
        d1 = crypto.load_d1(sym)
        trades, _, _ = crypto.simulate(sym, d1, dpp, rt)
        for t in trades:
            if t.exit_time is None or not (WINDOW_START <= t.exit_time < WINDOW_END):
                continue
            all_trades.append({
                "entry_time": t.entry_time, "exit_time": t.exit_time,
                "strategy": f"Donchian {sym}", "r": _r_multiple(t.pnl_usd),
            })

    # NR7 (US500 + DE40)
    import run_nr7_indices as nr7
    for sym, rt in nr7.INDICES:
        if sym not in ("US500", "DE40"):
            continue
        d1 = nr7.load_d1(sym)
        trades, _ = nr7.nr7_breakout(d1, rt)
        for t in trades:
            if t.exit_time is None or not (WINDOW_START <= t.exit_time < WINDOW_END):
                continue
            all_trades.append({
                "entry_time": t.entry_time, "exit_time": t.exit_time,
                "strategy": f"NR7 {sym}", "r": _r_multiple(t.pnl_usd),
            })

    return all_trades


# ─── Shared-capital simulation ─────────────────────────────────────────────
def simulate_shared(trades, risk_pct):
    """Walk events in chronological order, sizing off running shared equity.

    Each trade contributes two events: ENTRY (sizing decision) and EXIT
    (PnL realization). Shared equity grows from prior EXITs and feeds the
    next ENTRY's lot size.
    """
    # Build interleaved event list
    events = []
    for i, t in enumerate(trades):
        events.append((t["entry_time"], 0, i, "ENTRY"))   # ENTRY before EXIT on ties
        events.append((t["exit_time"],  1, i, "EXIT"))
    events.sort()  # by (time, kind, ...)

    shared_eq = STARTING_EQUITY
    pending_pnl = {}    # trade_id → pnl_$ locked in at entry sizing
    enriched = []
    curve_times = [WINDOW_START]
    curve_eq = [STARTING_EQUITY]

    for ts, _, trade_id, event_type in events:
        t = trades[trade_id]
        if event_type == "ENTRY":
            risk_at_entry = shared_eq * risk_pct / 100.0
            pnl = t["r"] * risk_at_entry
            pending_pnl[trade_id] = pnl
            enriched.append({**t, "pnl_usd_shared": pnl,
                             "risk_at_entry": risk_at_entry,
                             "shared_eq_at_entry": shared_eq})
        else:  # EXIT
            shared_eq += pending_pnl[trade_id]
            curve_times.append(ts)
            curve_eq.append(shared_eq)

    return enriched, np.array(curve_times), np.array(curve_eq), shared_eq


def main():
    print("Shared-capital simulation, current active book")
    print(f"Window: {WINDOW_START.date()} → {WINDOW_END.date()}\n")

    trades = collect_trades()
    print(f"Total trades collected: {len(trades)}")

    enriched, times, eq, final_eq = simulate_shared(trades, RISK_PCT)
    peaks = np.maximum.accumulate(eq)
    dd = peaks - eq
    max_dd = dd.max() if len(dd) > 1 else 0
    max_dd_pct = (max_dd / peaks.max() * 100) if peaks.max() > 0 else 0
    ret = (final_eq / STARTING_EQUITY - 1) * 100

    # Per-strategy realized totals
    by_strat = {}
    for t in enriched:
        by_strat.setdefault(t["strategy"], []).append(t["pnl_usd_shared"])

    print(f"\n{'Strategy':<22} {'N':>4} {'Net USD':>11}  Notes")
    print("-" * 60)
    for s in sorted(by_strat):
        pnls = by_strat[s]
        net = sum(pnls)
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        print(f"{s:<22} {n:>4} {net:>+10.2f}  WR {wins/n*100:.0f}%")

    n = len(enriched)
    wins = sum(1 for t in enriched if t["pnl_usd_shared"] > 0)
    gp = sum(t["pnl_usd_shared"] for t in enriched if t["pnl_usd_shared"] > 0)
    gl = abs(sum(t["pnl_usd_shared"] for t in enriched if t["pnl_usd_shared"] <= 0))
    pf = gp / gl if gl else float("inf")
    cagr = ret  # 1-year window, so simple = CAGR

    print()
    print(f"=== Shared-capital combined (1yr) ===")
    print(f"  Trades: {n}  WR: {wins/n*100:.1f}%  PF: {pf:.2f}")
    print(f"  Equity: ${STARTING_EQUITY:,.0f} → ${final_eq:,.2f}  ({ret:+.1f}%)")
    print(f"  Max realized DD: ${max_dd:,.2f} ({max_dd_pct:.1f}%)")
    print(f"  MAR (realized): {cagr/max_dd_pct:.2f}" if max_dd_pct > 0 else "  MAR: inf")

    # Sensitivity: what if simultaneous DD events correlate harder?
    # Run again with 0.5% risk (the production NR7 setting)
    print()
    print("Sensitivity: same trades at 0.5% per-trade risk (matches NR7 production setting):")
    _, _, eq05, final05 = simulate_shared(trades, 0.5)
    peaks05 = np.maximum.accumulate(eq05)
    dd05 = peaks05 - eq05
    max_dd05_pct = (dd05.max() / peaks05.max() * 100) if peaks05.max() > 0 else 0
    print(f"  Equity: ${STARTING_EQUITY:,.0f} → ${final05:,.2f} "
          f"({(final05/STARTING_EQUITY-1)*100:+.1f}%)")
    print(f"  Max DD: {max_dd05_pct:.1f}%")

    # ─── Plot ───
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
    ax1.plot(times, eq, color="black", linewidth=2.5, label="Combined (shared)", zorder=10)
    ax1.fill_between(times, STARTING_EQUITY, eq, alpha=0.08, color="black")
    ax1.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.5)

    # Per-strategy contribution curves — track each strategy's $ contribution
    # to the shared pool over time
    cum_by_strat = {s: [] for s in strat_colors}
    times_by_strat = {s: [WINDOW_START] for s in strat_colors}
    running = {s: 0.0 for s in strat_colors}
    for t in sorted(enriched, key=lambda x: x["exit_time"]):
        s = t["strategy"]
        if s not in running:
            continue
        running[s] += t["pnl_usd_shared"]
        times_by_strat[s].append(t["exit_time"])
        cum_by_strat[s].append(running[s])
    for s in strat_colors:
        ts = times_by_strat[s]
        cums = [0] + cum_by_strat[s]
        n_trades = len([t for t in enriched if t["strategy"] == s])
        if n_trades == 0:
            continue
        ax1.plot(ts, STARTING_EQUITY + np.array(cums),
                 color=strat_colors[s], linewidth=1.3, alpha=0.85,
                 label=f"{s} (N={n_trades})")

    ax1.set_title(
        f"SHARED-capital combined book — 1yr, {WINDOW_START.date()} → {WINDOW_END.date()}\n"
        f"${STARTING_EQUITY:,.0f} → ${final_eq:,.2f} ({ret:+.1f}%) | "
        f"N={n}, WR={wins/n*100:.0f}%, PF={pf:.2f}, MaxDD={max_dd_pct:.1f}% "
        f"(realized only — floating DD typically 1.5-2x)",
        fontsize=12, fontweight="bold",
    )
    ax1.set_ylabel("Equity ($) — shared pool")
    ax1.legend(loc="upper left", fontsize=9, ncol=2)
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    dd_pct_curve = -dd / peaks * 100
    ax2.fill_between(times, dd_pct_curve, 0, color="red", alpha=0.3)
    ax2.plot(times, dd_pct_curve, color="red", linewidth=0.8)
    ax2.set_ylabel("Realized drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(top=1)

    out_png = ROOT / "charts" / "current_book_shared_1yr.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out_png}")


if __name__ == "__main__":
    main()
