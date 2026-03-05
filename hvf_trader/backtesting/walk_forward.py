"""
Rolling window walk-forward validation.
6-month train / 2-month test windows sliding across historical data.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config
from hvf_trader.backtesting.backtest_engine import BacktestEngine, BacktestResult

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_result: Optional[BacktestResult] = None
    test_result: Optional[BacktestResult] = None


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
    oos_positive_windows: int = 0
    oos_positive_window_pct: float = 0.0

    def compute_aggregate(self):
        """Compute aggregate metrics across all out-of-sample periods."""
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
        self.oos_max_drawdown_pct = max(
            (r.max_drawdown_pct for r in oos_results), default=0.0
        )

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

    Returns:
        WalkForwardResult with all windows and aggregate metrics
    """
    train_m = train_months or config.WALKFORWARD_TRAIN_MONTHS
    test_m = test_months or config.WALKFORWARD_TEST_MONTHS
    step_m = step_months or test_m

    result = WalkForwardResult(symbol=symbol)

    # Ensure 'time' column exists
    if "time" not in df_1h.columns:
        logger.error("DataFrame must have a 'time' column")
        return result

    data_start = df_1h["time"].iloc[0]
    data_end = df_1h["time"].iloc[-1]

    # Generate windows
    current_start = data_start
    while True:
        train_start = current_start
        train_end = train_start + pd.DateOffset(months=train_m)
        test_start = train_end
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
            engine = BacktestEngine(starting_equity=starting_equity, enabled_patterns=enabled_patterns)
            window.train_result = engine.run(train_df, symbol, train_4h)
            logger.info(
                f"Train {train_start.strftime('%Y-%m')}→{train_end.strftime('%Y-%m')}: "
                f"{window.train_result.total_trades} trades, "
                f"WR={window.train_result.win_rate:.0f}%, "
                f"PF={window.train_result.profit_factor:.2f}"
            )

        # Run backtest on test period (out-of-sample)
        if len(test_df) > 250:
            engine = BacktestEngine(starting_equity=starting_equity, enabled_patterns=enabled_patterns)
            window.test_result = engine.run(test_df, symbol, test_4h)
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
