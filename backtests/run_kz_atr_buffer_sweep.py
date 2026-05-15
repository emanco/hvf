"""Sweep KZ_HUNT SL ATR-buffer multiplier through the hardened harness.

Buffer values tested: 0.5 (current), 1.0, 1.5, 2.0.

Theory: the 0.5×ATR buffer was set for H1 timeframe. KZ_HUNT switched to
M30 on 2026-04-28; M30 ATR is roughly half H1 ATR, so 0.5×ATR_M30 produces
stops that fall below MIN_STOP_PIPS=8, getting rejected at the gate.

What we want to see:
- How many MORE patterns survive the min-stop gate at wider buffers?
- Does PF / WR hold up as buffer widens (= SL further away = lower RRR)?
- Is there a sweet spot where rejection rate drops but PF doesn't?

Runs on EURGBP + NZDUSD M30 CSVs (the 2-pair winning subset).
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
logger = logging.getLogger("kz_atr_buffer_sweep")


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df["time"].dtype.kind in "iu":
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(df["time"], utc=True)
    df = add_indicators(df)
    df = df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
    return df


def main():
    symbols = ["EURGBP", "NZDUSD"]
    buffer_grid = (0.5, 1.0, 1.5, 2.0)
    data_dir = REPO_ROOT / "backtests" / "data"

    # Load data once
    data = {}
    for sym in symbols:
        csv_path = data_dir / f"{sym}_M30.csv"
        if not csv_path.exists():
            logger.warning("Missing CSV: %s — skipping %s", csv_path, sym)
            continue
        data[sym] = load_csv(csv_path)
        logger.info(
            "%s loaded: %d M30 bars (%s -> %s)",
            sym, len(data[sym]),
            data[sym]["time"].iloc[0], data[sym]["time"].iloc[-1],
        )

    # Sweep buffers, run hardened harness per (pair, buffer)
    results: dict[float, dict[str, "WalkForwardResult"]] = {}
    original_buffer = getattr(config, "KZ_HUNT_SL_ATR_BUFFER", 0.5)
    original_skip = config.KZ_HUNT_SKIP_CONFIRMATION
    try:
        for buf in buffer_grid:
            config.KZ_HUNT_SL_ATR_BUFFER = buf
            config.KZ_HUNT_SKIP_CONFIRMATION = True
            results[buf] = {}
            for sym in symbols:
                if sym not in data:
                    continue
                logger.info(
                    "=== buffer=%.1f ATR | %s | hardened harness ===", buf, sym,
                )
                results[buf][sym] = run_walk_forward(
                    df_1h=data[sym], symbol=sym, df_4h=None,
                    train_months=12, test_months=3,
                    starting_equity=700.0, step_months=3,
                    enabled_patterns=["KZ_HUNT"],
                    embargo_days=14,
                    use_realistic_spread=True,
                    slippage_random=True,
                )
    finally:
        config.KZ_HUNT_SL_ATR_BUFFER = original_buffer
        config.KZ_HUNT_SKIP_CONFIRMATION = original_skip

    # Summary
    print()
    print("=" * 95)
    print("KZ_HUNT SL ATR-BUFFER SWEEP — hardened harness, EURGBP+NZDUSD M30")
    print("=" * 95)
    print(
        f"{'buffer':<8} {'pair':<8} {'N':>4} {'WR':>6} {'PF':>6} "
        f"{'pips':>9} {'DD%':>6} {'pos-windows':>13}"
    )
    print("-" * 95)
    for buf in buffer_grid:
        for sym in symbols:
            r = results.get(buf, {}).get(sym)
            if r is None or r.total_oos_trades == 0:
                print(f"{buf:<8} {sym:<8} {'0':>4}")
                continue
            print(
                f"{buf:<8} {sym:<8} {r.total_oos_trades:>4} "
                f"{r.oos_win_rate:>5.1f}% {r.oos_profit_factor:>6.2f} "
                f"{r.oos_total_pnl_pips:>+9.1f} {r.oos_max_drawdown_pct:>5.1f}% "
                f"{r.oos_positive_windows}/{len(r.windows):>3}"
            )

    # Portfolio aggregate per buffer
    print()
    print("Portfolio aggregate per buffer:")
    for buf in buffer_grid:
        all_trades = []
        all_windows = 0
        positive_windows = 0
        for sym in symbols:
            r = results.get(buf, {}).get(sym)
            if r is None:
                continue
            all_windows += len(r.windows)
            positive_windows += r.oos_positive_windows
            for w in r.windows:
                if w.test_result:
                    all_trades.extend(w.test_result.trades)
        if not all_trades:
            print(f"  buffer={buf:<5} no trades")
            continue
        wins = [t for t in all_trades if t.pnl_pips > 0]
        gw = sum(t.pnl_pips for t in wins)
        gl = abs(sum(t.pnl_pips for t in all_trades if t.pnl_pips <= 0))
        pf = gw / gl if gl else float("inf")
        wr = len(wins) / len(all_trades) * 100
        pips = sum(t.pnl_pips for t in all_trades)
        # Joined-stream DD in dollars
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
            f"  buffer={buf:<5} N={len(all_trades):>4} WR={wr:5.1f}% "
            f"PF={pf:5.2f} pips={pips:+8.1f} DD=${max_dd:>8.2f} "
            f"windows={positive_windows}/{all_windows}"
        )


if __name__ == "__main__":
    main()
