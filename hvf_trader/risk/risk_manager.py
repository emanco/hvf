"""
Pre-trade risk management: 8 sequential checks that ALL must pass.

Check order:
    1. Circuit breaker not tripped
    2. Max concurrent trades not reached
    3. No high-impact news within window
    4. Spread within tolerance
    5. Free margin sufficient
    6. Correlation check (no duplicate directional exposure)
    7. Position sizer returns valid lot
    8. Reward-to-risk ratio still acceptable
"""
import logging
from dataclasses import dataclass

from hvf_trader import config
from hvf_trader.risk.position_sizer import calculate_lot_size, validate_lot_size
from hvf_trader.risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Pairs with strong positive correlation (~80%+).
# If one is already open in a given direction, block the same-direction entry
# on the other to avoid doubling effective exposure.
_CORRELATED_PAIRS: dict[str, str] = {
    "EURUSD": "GBPUSD",
    "GBPUSD": "EURUSD",
}


@dataclass
class RiskCheckResult:
    """Outcome of the 8-gate pre-trade check."""

    passed: bool
    check_name: str
    reason: str = ""
    lot_size: float = 0.0  # Populated only when all checks pass


class RiskManager:
    """
    Orchestrates pre-trade risk validation.

    All eight checks are evaluated sequentially; the first failure
    short-circuits and returns a descriptive rejection.
    """

    def __init__(self, circuit_breaker: CircuitBreaker, trade_logger=None):
        """
        Args:
            circuit_breaker: CircuitBreaker instance
            trade_logger: TradeLogger instance for DB queries
        """
        self.circuit_breaker = circuit_breaker
        self.trade_logger = trade_logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pre_trade_check(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target_2: float,
        equity: float,
        free_margin: float,
        margin_used: float,
        current_spread: float,
        open_trades: list,
        news_within_window: bool = False,
        exchange_rate_to_account: float = 1.0,
        pattern_type: str = "HVF",
    ) -> RiskCheckResult:
        """
        Run 8 sequential pre-trade checks. ALL must pass.

        Checks (in order):
            1. Circuit breaker not tripped (daily/weekly/monthly)
            2. Max concurrent trades not reached (< MAX_CONCURRENT_TRADES)
            3. No high-impact news within NEWS_BLOCK_MINUTES
            4. Spread < MAX_SPREAD_PCT_OF_STOP * stop_distance
            5. Free margin sufficient (margin_used / total < MAX_MARGIN_USAGE_PCT)
            6. Correlation check: no same-direction trade on correlated pair
            7. Position sizer returns valid lot >= 0.01
            8. RRR still >= HVF_MIN_RRR at current price

        Args:
            symbol: instrument (e.g. "EURUSD")
            direction: "BUY" or "SELL"
            entry_price: intended entry price
            stop_loss: stop-loss price
            target_2: full profit target
            equity: current account equity
            free_margin: available margin
            margin_used: currently utilised margin
            current_spread: live spread in price terms
            open_trades: list of dicts with at least {"symbol": str, "direction": str}
            news_within_window: True if high-impact news is imminent
            exchange_rate_to_account: FX rate for pip value conversion

        Returns:
            RiskCheckResult with passed=True and lot_size if all pass,
            or passed=False with the failing check name and reason.
        """
        stop_distance = abs(entry_price - stop_loss)

        # --- 1. Circuit breaker ---
        cb_clear, cb_reason = self.circuit_breaker.check(equity)
        if not cb_clear:
            return self._fail("circuit_breaker", cb_reason)

        # --- 2. Max concurrent trades ---
        if len(open_trades) >= config.MAX_CONCURRENT_TRADES:
            return self._fail(
                "max_concurrent_trades",
                f"Already {len(open_trades)} open trades "
                f"(limit {config.MAX_CONCURRENT_TRADES})",
            )

        # --- 3. News filter ---
        if news_within_window:
            return self._fail(
                "news_filter",
                f"High-impact news within {config.NEWS_BLOCK_MINUTES}-minute window",
            )

        # --- 4. Spread check ---
        max_spread = config.MAX_SPREAD_PCT_OF_STOP * stop_distance
        if current_spread >= max_spread:
            return self._fail(
                "spread_check",
                f"Spread {current_spread:.5f} >= {max_spread:.5f} "
                f"({config.MAX_SPREAD_PCT_OF_STOP * 100:.0f}% of stop distance {stop_distance:.5f})",
            )

        # --- 5. Margin check ---
        total_margin = margin_used + free_margin
        if total_margin <= 0:
            return self._fail("margin_check", "Total margin is zero or negative")
        margin_usage = margin_used / total_margin
        if margin_usage >= config.MAX_MARGIN_USAGE_PCT:
            return self._fail(
                "margin_check",
                f"Margin usage {margin_usage:.2%} >= limit {config.MAX_MARGIN_USAGE_PCT:.2%}",
            )

        # --- 6. Correlation check ---
        corr_ok, corr_reason = self._check_correlation(symbol, direction, open_trades)
        if not corr_ok:
            return self._fail("correlation_check", corr_reason)

        # --- 6b. Same-instrument blocking ---
        for trade in open_trades:
            if trade.get("symbol", "") == symbol:
                return self._fail(
                    "same_instrument",
                    f"Already have open trade on {symbol}",
                )

        # --- 7. Position sizing (per-pattern risk%) ---
        risk_pct = config.RISK_PCT_BY_PATTERN.get(pattern_type, config.RISK_PCT)
        lot_size = calculate_lot_size(
            equity=equity,
            risk_pct=risk_pct,
            stop_distance_price=stop_distance,
            symbol=symbol,
            exchange_rate_to_account=exchange_rate_to_account,
        )
        if lot_size <= 0:
            return self._fail(
                "position_sizing",
                f"Calculated lot size is 0 (equity={equity:.2f}, "
                f"stop_dist={stop_distance:.5f}, risk={config.RISK_PCT}%)",
            )

        # --- 8. RRR check ---
        reward_distance = abs(target_2 - entry_price)
        if stop_distance <= 0:
            return self._fail("rrr_check", "Stop distance is zero or negative")
        rrr = reward_distance / stop_distance
        min_rrr = config.MIN_RRR_BY_PATTERN.get(pattern_type, config.HVF_MIN_RRR)
        if rrr < min_rrr:
            return self._fail(
                "rrr_check",
                f"RRR {rrr:.2f} < minimum {min_rrr:.2f} "
                f"(reward={reward_distance:.5f}, risk={stop_distance:.5f})",
            )

        # --- All checks passed ---
        logger.info(
            "All 8 risk checks PASSED for %s %s: lot=%.2f RRR=%.2f",
            direction,
            symbol,
            lot_size,
            rrr,
        )
        return RiskCheckResult(
            passed=True,
            check_name="all_passed",
            reason="",
            lot_size=lot_size,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_correlation(
        self, symbol: str, direction: str, open_trades: list
    ) -> tuple[bool, str]:
        """
        Check if opening this trade would create correlated exposure.

        EURUSD and GBPUSD are ~80% correlated.  If there is already an
        open trade on the correlated pair in the *same* direction, block
        the new entry to avoid doubling effective exposure.

        Args:
            symbol: instrument to open
            direction: "BUY" or "SELL"
            open_trades: list of dicts with at least {"symbol": str, "direction": str}

        Returns:
            (is_ok, reason) -- True if no correlated conflict found.
        """
        correlated_symbol = _CORRELATED_PAIRS.get(symbol)
        if correlated_symbol is None:
            # No known correlation for this symbol -- pass.
            return True, ""

        for trade in open_trades:
            trade_symbol = trade.get("symbol", "")
            trade_direction = trade.get("direction", "")
            if (
                trade_symbol == correlated_symbol
                and trade_direction.upper() == direction.upper()
            ):
                return (
                    False,
                    f"Correlated exposure: already {trade_direction} on {trade_symbol} "
                    f"(correlated with {symbol})",
                )

        return True, ""

    @staticmethod
    def _fail(check_name: str, reason: str) -> RiskCheckResult:
        """Return a failed RiskCheckResult and log the rejection."""
        logger.warning("Risk check FAILED [%s]: %s", check_name, reason)
        return RiskCheckResult(passed=False, check_name=check_name, reason=reason)
