"""KZ_HUNT diagnostic runs:

1. **Multi-seed variance**: run hardened harness on EURGBP at the current
   buffer (0.5) with N different random-slippage seeds. Measure the
   distribution of OOS PF outcomes. Quantifies how much weight to put on
   any single backtest number.

2. **Geometric-validity ablation**: run with the geometric-validity check
   enabled vs disabled. Quantifies how much the invalid-pattern population
   inflated the May 12 PF 1.19 result.

Both run on EURGBP M30 CSV only (NZDUSD adds 50% runtime, EURGBP is the
2-pair winner under the May 12 hardened backtest, and the diagnostic
conclusions don't change with one more pair).
"""
import logging
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.walk_forward import run_walk_forward

logging.basicConfig(
    level=logging.WARNING,  # quieter — we just want the summary numbers
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kz_variance_geometric")


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df["time"].dtype.kind in "iu":
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(df["time"], utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    return df


def run_arm(df: pd.DataFrame, symbol: str, label: str) -> dict:
    res = run_walk_forward(
        df_1h=df, symbol=symbol, df_4h=None,
        train_months=12, test_months=3,
        starting_equity=700.0, step_months=3,
        enabled_patterns=["KZ_HUNT"],
        embargo_days=14,
        use_realistic_spread=True,
        slippage_random=True,
    )
    # Sum aggregates across the WF result
    if not res.windows or not any(w.test_result for w in res.windows):
        return {"label": label, "n": 0, "pf": 0.0, "wr": 0.0, "pips": 0.0}
    return {
        "label": label,
        "n": res.total_oos_trades,
        "pf": res.oos_profit_factor,
        "wr": res.oos_win_rate,
        "pips": res.oos_total_pnl_pips,
        "pos_windows": res.oos_positive_windows,
        "total_windows": len(res.windows),
    }


def part_1_variance(df: pd.DataFrame, sym: str, n_seeds: int = 5):
    """Run N seeds at current buffer + flags, collect PF distribution."""
    print()
    print("=" * 80)
    print(f"PART 1 — MULTI-SEED PF VARIANCE on {sym}")
    print(f"  buffer=0.5 ATR | skip-conf | broker-LIMIT | geometric-validity ON")
    print(f"  N seeds = {n_seeds}")
    print("=" * 80)

    # Lock current code settings
    original_buffer = getattr(config, "KZ_HUNT_SL_ATR_BUFFER", 0.5)
    original_skip = config.KZ_HUNT_SKIP_CONFIRMATION
    original_valid = getattr(config, "KZ_HUNT_ENFORCE_VALID_GEOMETRY", True)
    original_brokerlim = getattr(config, "KZ_HUNT_USE_BROKER_LIMITS", True)
    try:
        config.KZ_HUNT_SL_ATR_BUFFER = 0.5
        config.KZ_HUNT_SKIP_CONFIRMATION = True
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = True
        config.KZ_HUNT_USE_BROKER_LIMITS = True

        results = []
        for i, seed in enumerate(range(1001, 1001 + n_seeds)):
            random.seed(seed)
            print(f"\n  Run {i+1}/{n_seeds} (seed={seed})...")
            r = run_arm(df, sym, f"seed_{seed}")
            results.append(r)
            print(
                f"    -> N={r['n']:>3} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} "
                f"pips={r['pips']:+8.1f}"
            )
    finally:
        config.KZ_HUNT_SL_ATR_BUFFER = original_buffer
        config.KZ_HUNT_SKIP_CONFIRMATION = original_skip
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = original_valid
        config.KZ_HUNT_USE_BROKER_LIMITS = original_brokerlim

    pfs = [r["pf"] for r in results if r["n"] > 0]
    pips_list = [r["pips"] for r in results if r["n"] > 0]
    if pfs:
        mean_pf = sum(pfs) / len(pfs)
        # Sample std deviation
        var = sum((p - mean_pf) ** 2 for p in pfs) / max(len(pfs) - 1, 1)
        std_pf = var ** 0.5
        min_pf, max_pf = min(pfs), max(pfs)
        mean_pips = sum(pips_list) / len(pips_list)
        print()
        print(f"  Summary across {len(pfs)} seeds:")
        print(f"    mean PF  = {mean_pf:.2f}")
        print(f"    std PF   = {std_pf:.2f}")
        print(f"    range    = [{min_pf:.2f}, {max_pf:.2f}]")
        print(f"    mean pips = {mean_pips:+.1f}")
        # Simple 95% interpretation under normal assumption
        ci_low = mean_pf - 1.96 * (std_pf / max(len(pfs) ** 0.5, 1.0))
        ci_high = mean_pf + 1.96 * (std_pf / max(len(pfs) ** 0.5, 1.0))
        print(f"    95% CI on mean PF ≈ [{ci_low:.2f}, {ci_high:.2f}]")
    return results


def part_2_geometric(df: pd.DataFrame, sym: str, seed: int = 1001):
    """Run with geometric-validity check ON vs OFF, fixed seed for fair compare."""
    print()
    print("=" * 80)
    print(f"PART 2 — GEOMETRIC-VALIDITY ABLATION on {sym}")
    print(f"  buffer=0.5 ATR | skip-conf | broker-LIMIT | fixed seed={seed}")
    print("=" * 80)

    original_buffer = getattr(config, "KZ_HUNT_SL_ATR_BUFFER", 0.5)
    original_skip = config.KZ_HUNT_SKIP_CONFIRMATION
    original_valid = getattr(config, "KZ_HUNT_ENFORCE_VALID_GEOMETRY", True)
    original_brokerlim = getattr(config, "KZ_HUNT_USE_BROKER_LIMITS", True)
    try:
        config.KZ_HUNT_SL_ATR_BUFFER = 0.5
        config.KZ_HUNT_SKIP_CONFIRMATION = True
        config.KZ_HUNT_USE_BROKER_LIMITS = True

        print(f"\n  ARM A: geometric-validity ON (current production)")
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = True
        random.seed(seed)
        a = run_arm(df, sym, "ON")
        print(
            f"    -> N={a['n']:>3} WR={a['wr']:5.1f}% PF={a['pf']:5.2f} "
            f"pips={a['pips']:+8.1f}"
        )

        print(f"\n  ARM B: geometric-validity OFF (May 12 behaviour)")
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = False
        random.seed(seed)
        b = run_arm(df, sym, "OFF")
        print(
            f"    -> N={b['n']:>3} WR={b['wr']:5.1f}% PF={b['pf']:5.2f} "
            f"pips={b['pips']:+8.1f}"
        )
    finally:
        config.KZ_HUNT_SL_ATR_BUFFER = original_buffer
        config.KZ_HUNT_SKIP_CONFIRMATION = original_skip
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = original_valid
        config.KZ_HUNT_USE_BROKER_LIMITS = original_brokerlim

    print()
    print(f"  Delta (OFF - ON):")
    print(f"    trades       : {b['n'] - a['n']:+d}")
    print(f"    PF           : {b['pf'] - a['pf']:+.2f}")
    print(f"    pips         : {b['pips'] - a['pips']:+.1f}")
    if b["n"] - a["n"] > 0:
        # Approximate average contribution per added (invalid-geometry) trade
        added_trades = b["n"] - a["n"]
        added_pips = b["pips"] - a["pips"]
        print(
            f"    avg pips per invalid-geometry trade: "
            f"{added_pips / added_trades:+.2f}"
        )
    return a, b


def main():
    data_dir = REPO_ROOT / "backtests" / "data"
    csv_path = data_dir / "EURGBP_M30.csv"
    df = load_csv(csv_path)
    print(
        f"Loaded {len(df)} M30 bars on EURGBP "
        f"({df['time'].iloc[0]} → {df['time'].iloc[-1]})"
    )

    part_1_variance(df, "EURGBP", n_seeds=5)
    part_2_geometric(df, "EURGBP", seed=1001)


if __name__ == "__main__":
    main()
