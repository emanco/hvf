"""KZ_HUNT harness calibration (2026-06-23).

We KNOW the live answer for KZ_HUNT on EURGBP: no edge (live clean PF ~0.66,
honest backtest PF ~0.44). So KZ is a perfect ruler for validating the
hardened backtest harness. Run three arms on EURGBP M30 walk-forward:

  A. OPTIMISTIC (the old default): flat 1.5p spread, zero slippage, zero
     commission, AND geometric-validity OFF (the May-12 bug). This is the
     configuration that produced the inflated PF ~1.19-1.53 we wrongly
     acted on.
  B. HONEST (pre-hardening): realistic per-symbol/hour spread + random
     slippage, zero commission, geometry ON. Should reproduce the ~0.44
     from the geometric-validity ablation memory.
  C. HARDENED (new default): everything in B PLUS round-trip commission.
     This is the new honest baseline; should sit at or below B.

If A >> 1.0 and B ≈ C ≈ 0.44 (sub-1.0, matching live "no edge"), the
hardened harness is calibrated: it reproduces reality where we can check it.
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

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

SEED = 1001


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df["time"].dtype.kind in "iu":
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(df["time"], utc=True)
    df = add_indicators(df)
    return df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)


def run_arm(df, sym, *, realistic_spread, slippage, commission, geometry_on):
    """Run one walk-forward arm with explicit friction + geometry settings."""
    orig_geo = getattr(config, "KZ_HUNT_ENFORCE_VALID_GEOMETRY", True)
    orig_buf = getattr(config, "KZ_HUNT_SL_ATR_BUFFER", 0.5)
    orig_skip = config.KZ_HUNT_SKIP_CONFIRMATION
    orig_lim = getattr(config, "KZ_HUNT_USE_BROKER_LIMITS", True)
    try:
        config.KZ_HUNT_SL_ATR_BUFFER = 0.5
        config.KZ_HUNT_SKIP_CONFIRMATION = True
        config.KZ_HUNT_USE_BROKER_LIMITS = True
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = geometry_on
        random.seed(SEED)  # determinism across arms (slippage draws)
        res = run_walk_forward(
            df_1h=df, symbol=sym, df_4h=None,
            train_months=12, test_months=3, step_months=3,
            starting_equity=700.0, enabled_patterns=["KZ_HUNT"],
            embargo_days=14,
            use_realistic_spread=realistic_spread,
            slippage_random=slippage,
            commission_per_lot_roundtrip=commission,
        )
    finally:
        config.KZ_HUNT_ENFORCE_VALID_GEOMETRY = orig_geo
        config.KZ_HUNT_SL_ATR_BUFFER = orig_buf
        config.KZ_HUNT_SKIP_CONFIRMATION = orig_skip
        config.KZ_HUNT_USE_BROKER_LIMITS = orig_lim
    return {
        "n": res.total_oos_trades, "pf": res.oos_profit_factor,
        "wr": res.oos_win_rate, "pips": res.oos_total_pnl_pips,
    }


def main():
    df = load_csv(REPO_ROOT / "backtests" / "data" / "EURGBP_M30.csv")
    print(f"EURGBP M30: {len(df)} bars ({df['time'].iloc[0]} -> {df['time'].iloc[-1]})\n")

    arms = [
        ("A  OPTIMISTIC (flat 1.5p, no slip, no comm, geometry OFF)",
         dict(realistic_spread=False, slippage=False, commission=0.0, geometry_on=False)),
        ("B  HONEST (realistic spread+slip, no comm, geometry ON)",
         dict(realistic_spread=True, slippage=True, commission=0.0, geometry_on=True)),
        ("C  HARDENED (realistic spread+slip + $7 comm, geometry ON)",
         dict(realistic_spread=True, slippage=True, commission=7.0, geometry_on=True)),
    ]
    print(f"{'arm':<58}{'N':>5}{'WR%':>7}{'PF':>7}{'pips':>9}")
    print("-" * 86)
    out = {}
    for label, kw in arms:
        r = run_arm(df, "EURGBP", **kw)
        out[label[0]] = r
        print(f"{label:<58}{r['n']:>5}{r['wr']:>6.1f}{r['pf']:>7.2f}{r['pips']:>+9.1f}")
    print("-" * 86)
    print("\nCalibration check:")
    print(f"  Inflation from optimism+bug : PF {out['A']['pf']:.2f} (arm A) — the number we wrongly trusted")
    print(f"  Honest harness              : PF {out['B']['pf']:.2f} (arm B) — should reproduce ~0.44")
    print(f"  Hardened (+commission)      : PF {out['C']['pf']:.2f} (arm C) — new honest baseline")
    print(f"  Live KZ_HUNT (reference)    : PF ~0.66 clean / ~0.44 honest backtest — both 'no edge'")


if __name__ == "__main__":
    main()
