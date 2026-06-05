"""Quick Donchian 55/20/1.0 on SOLUSD.

Only 1.5 years of broker data available so this is NOT a proper validation —
no walk-forward possible, sample will be tiny. Treat as directional sanity
check only.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_crypto_donchian as cd

# Override the instrument list — only SOL
cd.INSTRUMENTS = [("SOLUSD", 1.0, 0.05, 1.0)]  # 1 lot = $1/$ move; ~5 cents spread; vol_min=1


def main():
    sym, dpp, rt, vmin = cd.INSTRUMENTS[0]
    d1 = cd.load_d1(sym)
    print(f"SOLUSD D1 data: {len(d1)} bars  {d1.index[0]} to {d1.index[-1]}")
    print(f"  ({(d1.index[-1] - d1.index[0]).days} days, ~{(d1.index[-1] - d1.index[0]).days/365.25:.1f} years)\n")

    print(f"=== SOLUSD Daily Donchian 55/20/1.0 ===")
    trades, _, _ = cd.simulate(sym, d1, dpp, rt)
    years = (d1.index[-1] - d1.index[0]).days / 365.25
    s = cd.stats(trades, cd.STARTING_EQUITY + sum(t.pnl_usd for t in trades), years)
    if not s:
        print("  0 trades — strategy hasn't found a setup in this window")
        return
    total_usd = sum(t.pnl_usd for t in trades)
    print(f"  Trades: {s['n']}  WR: {s['wr']:.1f}%  PF: {s['pf']:.2f}")
    print(f"  Total: ${total_usd:+.2f}  Equity: ${cd.STARTING_EQUITY:,.0f} → ${cd.STARTING_EQUITY + total_usd:,.0f}")
    print(f"  Avg win: ${s['avg_win_usd']:+,.2f}   Avg loss: ${s['avg_loss_usd']:+,.2f}")

    print(f"\n  Individual trades:")
    for i, t in enumerate(trades, 1):
        print(f"    {i}. {t.entry_time.date()} {t.direction} @ {t.entry_price:.2f} → "
              f"{t.exit_time.date()} {t.exit_reason} @ {t.exit_price:.2f}  "
              f"pnl=${t.pnl_usd:+,.2f}")

    # Quick chart
    fig, ax = plt.subplots(figsize=(14, 5))
    times = [trades[0].entry_time] + [t.exit_time for t in trades]
    eq = np.concatenate([[cd.STARTING_EQUITY],
                          cd.STARTING_EQUITY + np.cumsum([t.pnl_usd for t in trades])])
    ax.plot(times, eq, color="purple", linewidth=1.5)
    ax.fill_between(times, cd.STARTING_EQUITY, eq, alpha=0.15, color="purple")
    ax.axhline(y=cd.STARTING_EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax.set_title(
        f"SOLUSD Daily Donchian 55/20/1.0 — {years:.1f}y, N={s['n']}, "
        f"PF {s['pf']:.2f}, "
        f"${cd.STARTING_EQUITY:,.0f}→${cd.STARTING_EQUITY+total_usd:,.0f} "
        f"(tiny sample, NOT validated)",
        fontsize=11, fontweight="bold",
    )
    ax.set_ylabel("Equity ($)")
    ax.grid(True, alpha=0.3)
    out = ROOT / "charts" / "donchian_sol.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart: {out}")


if __name__ == "__main__":
    main()
