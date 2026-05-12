"""Compare KZ_HUNT walk-forward under the rebuilt harness, three arms:
  A) Legacy:    flat 1.5p spread, 0p slippage, no sweep, no skip, 0d embargo
  B) Hardened:  realistic spread, random slippage, sweep=True, 14d embargo
  C) Skip-conf: realistic spread, random slippage, sweep=False but
                SKIP_CONFIRMATION=True (LIMIT at rejection close), 14d embargo

Runs on the local M30 CSV — no MT5 connection required.
"""
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.walk_forward import run_walk_forward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kz_sweep_compare")


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df["time"].dtype.kind in "iu":
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(df["time"], utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    return df


def fmt(r):
    n = r.total_oos_trades
    if n == 0:
        return "  N=0 (no OOS trades)"
    return (
        f"  N={n}  WR={r.oos_win_rate:.1f}%  PF={r.oos_profit_factor:.2f}  "
        f"pips={r.oos_total_pnl_pips:+.1f}  DD={r.oos_max_drawdown_pct:.1f}%  "
        f"positive_windows={r.oos_positive_windows}/{len(r.windows)}"
    )


def run_arm(label: str, df: pd.DataFrame, symbol: str, **kwargs):
    logger.info("=" * 80)
    logger.info("ARM: %s", label)
    logger.info("=" * 80)
    return run_walk_forward(
        df_1h=df,
        symbol=symbol,
        df_4h=None,
        train_months=12,
        test_months=3,
        starting_equity=700.0,
        step_months=3,
        enabled_patterns=["KZ_HUNT"],
        **kwargs,
    )


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument(
        "--pairs", nargs="+",
        default=["EURGBP", "NZDUSD", "EURJPY", "EURAUD"],
        help="Which pairs to run (default: all 4)",
    )
    args = p.parse_args()
    symbols = args.pairs
    data_dir = REPO_ROOT / "backtests" / "data"

    # Run both arms per symbol and collate per-symbol summary
    summary = []
    for sym in symbols:
        csv_path = data_dir / f"{sym}_M30.csv"
        if not csv_path.exists():
            logger.warning("Missing CSV: %s — skipping %s", csv_path, sym)
            continue
        df = load_csv(csv_path)
        logger.info(
            "%s loaded: %d M30 bars (%s -> %s)",
            sym, len(df), df["time"].iloc[0], df["time"].iloc[-1],
        )

        # Temporarily flip flags per arm.
        sweep_original = config.KZ_HUNT_REQUIRE_SWEEP
        skip_original = config.KZ_HUNT_SKIP_CONFIRMATION
        try:
            config.KZ_HUNT_REQUIRE_SWEEP = False
            config.KZ_HUNT_SKIP_CONFIRMATION = False
            res_legacy = run_arm(
                f"{sym} — LEGACY (flat 1.5p, no slip, no sweep, no embargo)",
                df, sym,
                embargo_days=0,
                use_realistic_spread=False,
                slippage_random=False,
                slippage_pips=0.0,
            )
            config.KZ_HUNT_REQUIRE_SWEEP = True
            config.KZ_HUNT_SKIP_CONFIRMATION = False
            res_hardened = run_arm(
                f"{sym} — HARDENED (real spread, random slip, sweep, 14d embargo)",
                df, sym,
                embargo_days=14,
                use_realistic_spread=True,
                slippage_random=True,
            )
            config.KZ_HUNT_REQUIRE_SWEEP = False
            config.KZ_HUNT_SKIP_CONFIRMATION = True
            res_skip = run_arm(
                f"{sym} — SKIP-CONF (real spread, random slip, LIMIT at rejection close, 14d embargo)",
                df, sym,
                embargo_days=14,
                use_realistic_spread=True,
                slippage_random=True,
            )
        finally:
            config.KZ_HUNT_REQUIRE_SWEEP = sweep_original
            config.KZ_HUNT_SKIP_CONFIRMATION = skip_original

        summary.append((sym, res_legacy, res_hardened, res_skip))

    # Print the summary table
    print()
    print("=" * 90)
    print("KZ_HUNT WALK-FORWARD COMPARISON — LEGACY vs HARDENED HARNESS")
    print("=" * 90)
    print(f"{'sym':<8} {'arm':<11} {'N':>4} {'WR':>6} {'PF':>6} {'pips':>9} {'DD':>6} {'win-wins':>10}")
    print("-" * 95)
    for sym, leg, har, skp in summary:
        for label, r in (("legacy", leg), ("hardened", har), ("skip-conf", skp)):
            n = r.total_oos_trades
            if n == 0:
                print(f"{sym:<8} {label:<11} {'0':>4}")
                continue
            print(
                f"{sym:<8} {label:<11} "
                f"{n:>4} {r.oos_win_rate:>5.1f}% {r.oos_profit_factor:>6.2f} "
                f"{r.oos_total_pnl_pips:>+9.1f} {r.oos_max_drawdown_pct:>5.1f}% "
                f"{r.oos_positive_windows}/{len(r.windows):>5}"
            )

    # Combined portfolio numbers (concat trades across pairs per arm)
    print()
    print("Portfolio aggregate:")
    for label, idx in (("legacy", 1), ("hardened", 2), ("skip-conf", 3)):
        all_trades = []
        all_windows = 0
        positive_windows = 0
        for s in summary:
            r = s[idx]
            all_windows += len(r.windows)
            positive_windows += r.oos_positive_windows
            for w in r.windows:
                if w.test_result:
                    all_trades.extend(w.test_result.trades)
        if not all_trades:
            print(f"  {label:<10} no trades")
            continue
        wins = [t for t in all_trades if t.pnl_pips > 0]
        gw = sum(t.pnl_pips for t in wins)
        gl = abs(sum(t.pnl_pips for t in all_trades if t.pnl_pips <= 0))
        pf = gw / gl if gl else float("inf")
        wr = len(wins) / len(all_trades) * 100
        pips = sum(t.pnl_pips for t in all_trades)
        # Joined-stream DD
        all_trades.sort(
            key=lambda t: t.exit_time if t.exit_time is not None else pd.Timestamp.max,
        )
        eq = []
        running = 0.0
        for t in all_trades:
            running += t.pnl_currency
            eq.append(running)
        peak = eq[0]
        max_dd = 0.0
        for v in eq:
            if v > peak:
                peak = v
            if peak - v > max_dd:
                max_dd = peak - v
        print(
            f"  {label:<10} N={len(all_trades):>4} WR={wr:5.1f}% PF={pf:5.2f} "
            f"pips={pips:+8.1f} DD=${max_dd:>8.2f} "
            f"windows={positive_windows}/{all_windows}"
        )


if __name__ == "__main__":
    main()
