"""
Rolling window walk-forward validation.
6-month train / 2-month test windows sliding across historical data.

Hardened-harness changes (2026-05):
- `embargo_days`: gap between train_end and test_start to prevent
  look-ahead leakage from indicator state crossing the boundary.
- Locked parameters: snapshot relevant config values at train_end;
  warn loudly if anything changes before the test runs.
- Portfolio-level DD aggregation: drawdown is computed on the joined
  OOS PnL stream, not as max(per-window DDs).
- Realistic spread + slippage: BacktestEngine instances are now
  constructed with use_realistic_spread=True by default.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config
from hvf_trader.backtesting.backtest_engine import BacktestEngine, BacktestResult

logger = logging.getLogger(__name__)

# Parameters we snapshot at train_end and require to stay frozen for
# the matching test window. If a value changes between snapshot and
# test execution, we log a WARNING — that's an integrity violation.
_LOCKED_CONFIG_KEYS = (
    "SCORE_THRESHOLD_BY_PATTERN",
    "MIN_RRR_BY_PATTERN",
    "RISK_PCT_BY_PATTERN",
    "MIN_STOP_PIPS_BY_PATTERN",
    "PATTERN_FRESHNESS_BARS",
    "PARTIAL_CLOSE_PCT",
    "TRAILING_STOP_ATR_MULT_BY_PATTERN",
    "INVALIDATION_ENABLED_BY_PATTERN",
    "KZ_HUNT_REQUIRE_SWEEP",
    "TARGET_2_PIPS_BY_PATTERN",
)


def _snapshot_locked_params() -> dict:
    """Capture the current values of all locked config keys."""
    import copy
    snap = {}
    for key in _LOCKED_CONFIG_KEYS:
        if hasattr(config, key):
            snap[key] = copy.deepcopy(getattr(config, key))
    return snap


def _verify_locked_params(snapshot: dict, label: str) -> bool:
    """Compare current config to snapshot; return True if unchanged."""
    drifted: list[str] = []
    for key, old_val in snapshot.items():
        new_val = getattr(config, key, None)
        if new_val != old_val:
            drifted.append(f"{key}: {old_val!r} -> {new_val!r}")
    if drifted:
        logger.warning(
            "[WF] %s — locked parameters drifted between train and test! %s",
            label, "; ".join(drifted),
        )
        return False
    return True


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_result: Optional[BacktestResult] = None
    test_result: Optional[BacktestResult] = None
    locked_params_ok: bool = True


@dataclass
class WalkForwardResult:
    symbol: str
    windows: list[WalkForwardWindow] = field(default_factory=list)

    # Aggregate metrics across all out-of-sample windows
    total_oos_trades: int = 0
    oos_win_rate: float = 0.0
    oos_profit_factor: float = 0.0
    oos_total_pnl_pips: float = 0.0
    oos_max_drawdown_pct: float = 0.0
    oos_max_drawdown_usd: float = 0.0
    oos_positive_windows: int = 0
    oos_positive_window_pct: float = 0.0
    starting_equity: float = 700.0  # used as DD-pct denominator

    def compute_aggregate(self):
        """Compute aggregate metrics across all out-of-sample periods.

        Drawdown is now computed on the JOINED OOS PnL stream (running
        equity peak vs trough across all windows), not as max of per-
        window DDs. The old aggregation under-reported real portfolio
        risk by ignoring losing-streak compounding across windows.
        """
        oos_results = [w.test_result for w in self.windows if w.test_result]
        if not oos_results:
            return

        all_trades = []
        for r in oos_results:
            all_trades.extend(r.trades)

        self.total_oos_trades = len(all_trades)
        if self.total_oos_trades == 0:
            return

        winners = [t for t in all_trades if t.pnl_pips > 0]
        losers = [t for t in all_trades if t.pnl_pips <= 0]

        self.oos_win_rate = len(winners) / self.total_oos_trades * 100

        gross_profit = sum(t.pnl_currency for t in winners) if winners else 0.0
        gross_loss = abs(sum(t.pnl_currency for t in losers)) if losers else 0.0
        self.oos_profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else float("inf")
        )

        self.oos_total_pnl_pips = sum(t.pnl_pips for t in all_trades)

        # Portfolio-level DD: build the joined equity curve from chronological
        # OOS trades, anchored at starting_equity (so DD-pct is meaningful
        # even when the strategy spends the whole period below baseline).
        all_trades_sorted = sorted(
            all_trades,
            key=lambda t: t.exit_time if t.exit_time is not None else pd.Timestamp.max,
        )
        equity_curve = [self.starting_equity]
        for t in all_trades_sorted:
            equity_curve.append(equity_curve[-1] + t.pnl_currency)
        if len(equity_curve) > 1:
            peak = equity_curve[0]
            max_dd_usd = 0.0
            for v in equity_curve:
                if v > peak:
                    peak = v
                dd = peak - v
                if dd > max_dd_usd:
                    max_dd_usd = dd
            self.oos_max_drawdown_usd = max_dd_usd
            # Express DD as pct of starting equity — interpretable across runs
            # even when account has long stretches underwater.
            self.oos_max_drawdown_pct = (
                (max_dd_usd / self.starting_equity) * 100
                if self.starting_equity > 0 else 0.0
            )
        else:
            self.oos_max_drawdown_pct = 0.0
            self.oos_max_drawdown_usd = 0.0

        self.oos_positive_windows = sum(
            1 for r in oos_results if r.total_pnl_pips > 0
        )
        self.oos_positive_window_pct = (
            self.oos_positive_windows / len(oos_results) * 100
        )

    def summary(self) -> str:
        """Generate a human-readable summary."""
        lines = [
            f"Walk-Forward Results: {self.symbol}",
            f"{'='*50}",
            f"Windows: {len(self.windows)}",
            f"Total OOS trades: {self.total_oos_trades}",
            f"OOS Win Rate: {self.oos_win_rate:.1f}%",
            f"OOS Profit Factor: {self.oos_profit_factor:.2f}",
            f"OOS Total PnL (pips): {self.oos_total_pnl_pips:.1f}",
            f"OOS Max Drawdown: {self.oos_max_drawdown_pct:.1f}%",
            f"Positive Windows: {self.oos_positive_windows}/{len(self.windows)} "
            f"({self.oos_positive_window_pct:.0f}%)",
            "",
            "Per-Window Breakdown:",
            f"{'─'*50}",
        ]

        for i, w in enumerate(self.windows):
            if w.test_result:
                r = w.test_result
                lines.append(
                    f"  Window {i+1}: "
                    f"{w.test_start.strftime('%Y-%m')} → {w.test_end.strftime('%Y-%m')} | "
                    f"Trades={r.total_trades}, "
                    f"WR={r.win_rate:.0f}%, "
                    f"PF={r.profit_factor:.2f}, "
                    f"PnL={r.total_pnl_pips:+.1f} pips"
                )

        return "\n".join(lines)


def run_walk_forward(
    df_1h: pd.DataFrame,
    symbol: str,
    df_4h: pd.DataFrame = None,
    train_months: int = None,
    test_months: int = None,
    starting_equity: float = 500.0,
    step_months: int = None,
    enabled_patterns: list[str] = None,
    # Hardened-harness knobs (default ON — flip to disable for legacy runs)
    embargo_days: int = 14,
    use_realistic_spread: bool = True,
    slippage_random: bool = True,
    slippage_pips: float | None = None,
    spread_percentile: str = "median",
    enforce_locked_params: bool = True,
) -> WalkForwardResult:
    """
    Run walk-forward analysis with sliding windows.

    Args:
        df_1h: Full historical 1H data with indicators
        symbol: instrument symbol
        df_4h: Full historical 4H data (optional)
        train_months: training window size (default from config)
        test_months: test window size (default from config)
        starting_equity: starting equity per window
        step_months: how far to slide each step (default = test_months)
        embargo_days: gap between train_end and test_start to prevent
            indicator-state leakage across the train/test boundary
            (default 14 days). Set 0 for legacy behavior.
        use_realistic_spread: use per-symbol+hour spread model. Default True.
        slippage_random: sample slippage from a clipped gaussian per fill.
            Default True.
        slippage_pips: if set, override slippage with this fixed pip value
            (use for sensitivity-test sweeps).
        spread_percentile: "median" or "p95" — controls how punitive the
            spread model is.
        enforce_locked_params: snapshot parameters at train_end and warn
            if anything drifts before test runs.

    Returns:
        WalkForwardResult with all windows and aggregate metrics
    """
    train_m = train_months or config.WALKFORWARD_TRAIN_MONTHS
    test_m = test_months or config.WALKFORWARD_TEST_MONTHS
    step_m = step_months or test_m

    result = WalkForwardResult(symbol=symbol, starting_equity=starting_equity)

    # Ensure 'time' column exists
    if "time" not in df_1h.columns:
        logger.error("DataFrame must have a 'time' column")
        return result

    data_start = df_1h["time"].iloc[0]
    data_end = df_1h["time"].iloc[-1]
    embargo = pd.Timedelta(days=embargo_days)

    def _make_engine() -> BacktestEngine:
        return BacktestEngine(
            starting_equity=starting_equity,
            enabled_patterns=enabled_patterns,
            use_realistic_spread=use_realistic_spread,
            slippage_random=slippage_random,
            slippage_pips=slippage_pips,
            spread_percentile=spread_percentile,
        )

    # Generate windows
    current_start = data_start
    while True:
        train_start = current_start
        train_end = train_start + pd.DateOffset(months=train_m)
        # Embargo: test starts *after* train_end + gap. With overlapping
        # train windows, this also separates the OOS from any indicator
        # warmup leakage in the prior train.
        test_start = train_end + embargo
        test_end = test_start + pd.DateOffset(months=test_m)

        # Stop if test period exceeds data
        if test_end > data_end:
            break

        window = WalkForwardWindow(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        )

        # Slice data for train and test periods
        train_mask = (df_1h["time"] >= train_start) & (df_1h["time"] < train_end)
        test_mask = (df_1h["time"] >= test_start) & (df_1h["time"] < test_end)

        train_df = df_1h[train_mask].copy().reset_index(drop=True)
        test_df = df_1h[test_mask].copy().reset_index(drop=True)

        # Slice 4H data if provided
        train_4h = None
        test_4h = None
        if df_4h is not None and "time" in df_4h.columns:
            train_4h_mask = (df_4h["time"] >= train_start) & (df_4h["time"] < train_end)
            test_4h_mask = (df_4h["time"] >= test_start) & (df_4h["time"] < test_end)
            train_4h = df_4h[train_4h_mask].copy().reset_index(drop=True)
            test_4h = df_4h[test_4h_mask].copy().reset_index(drop=True)

        # Run backtest on train period (for reference/comparison)
        if len(train_df) > 250:
            window.train_result = _make_engine().run(train_df, symbol, train_4h)
            logger.info(
                f"Train {train_start.strftime('%Y-%m')}→{train_end.strftime('%Y-%m')}: "
                f"{window.train_result.total_trades} trades, "
                f"WR={window.train_result.win_rate:.0f}%, "
                f"PF={window.train_result.profit_factor:.2f}"
            )

        # Snapshot locked parameters at the train/test boundary, then
        # check they haven't drifted before running the OOS test.
        param_snapshot = (
            _snapshot_locked_params() if enforce_locked_params else None
        )

        # Run backtest on test period (out-of-sample)
        if len(test_df) > 250:
            if param_snapshot is not None:
                window.locked_params_ok = _verify_locked_params(
                    param_snapshot,
                    label=(
                        f"Window {train_start.strftime('%Y-%m')}-"
                        f"{test_end.strftime('%Y-%m')}"
                    ),
                )
            window.test_result = _make_engine().run(test_df, symbol, test_4h)
            logger.info(
                f"Test {test_start.strftime('%Y-%m')}→{test_end.strftime('%Y-%m')}: "
                f"{window.test_result.total_trades} trades, "
                f"WR={window.test_result.win_rate:.0f}%, "
                f"PF={window.test_result.profit_factor:.2f}"
            )

        result.windows.append(window)

        # Slide forward
        current_start = current_start + pd.DateOffset(months=step_m)

    result.compute_aggregate()
    logger.info(f"\n{result.summary()}")
    return result


def run_slippage_sensitivity(
    df_1h: pd.DataFrame,
    symbol: str,
    df_4h: pd.DataFrame = None,
    slippage_grid: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0),
    **wf_kwargs,
) -> dict[float, WalkForwardResult]:
    """Run the walk-forward at each slippage value in the grid.

    Reports the edge's fragility to slippage assumptions — a strategy whose
    PF collapses from 1.5 at 0p slippage to 0.8 at 1p slippage is not robust
    enough to deploy live.

    Returns:
        Dict mapping slippage_pips -> WalkForwardResult.
    """
    out: dict[float, WalkForwardResult] = {}
    for s in slippage_grid:
        logger.info(
            "[WF] slippage_sensitivity: running with slippage_pips=%.2f", s,
        )
        out[s] = run_walk_forward(
            df_1h, symbol, df_4h,
            slippage_pips=s,
            slippage_random=False,
            **wf_kwargs,
        )
    return out
