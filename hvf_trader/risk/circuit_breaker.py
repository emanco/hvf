"""
Circuit breaker: pauses trading when loss limits are hit.
Persists state to database for crash recovery.

Three levels of protection:
    DAILY   - trips at DAILY_LOSS_LIMIT_PCT, resumes at midnight UTC
    WEEKLY  - trips at WEEKLY_LOSS_LIMIT_PCT, resumes at Monday 00:00 UTC
    MONTHLY - trips at MONTHLY_LOSS_LIMIT_PCT, resumes at 1st of next month 00:00 UTC
"""
import logging
from datetime import datetime, timezone, timedelta

from hvf_trader import config

logger = logging.getLogger(__name__)

_LEVELS = ("DAILY", "WEEKLY", "MONTHLY")

_LIMIT_MAP = {
    "DAILY": config.DAILY_LOSS_LIMIT_PCT,
    "WEEKLY": config.WEEKLY_LOSS_LIMIT_PCT,
    "MONTHLY": config.MONTHLY_LOSS_LIMIT_PCT,
}


class CircuitBreaker:
    """
    Monitors cumulative losses over daily, weekly, and monthly windows.
    When a loss limit is breached the corresponding breaker trips and
    trading is blocked until the window resets.
    """

    def __init__(self, trade_logger=None):
        """
        Args:
            trade_logger: TradeLogger instance for DB persistence and PnL queries.
                          Must expose:
                            - get_circuit_breaker_state(level) -> object with .tripped, .resumes_at
                            - update_circuit_breaker(level, tripped, resumes_at=None)
                            - get_pnl_since(since_dt) -> float (total closed PnL in account currency)
        """
        self.trade_logger = trade_logger
        self._tripped: dict[str, bool] = {lvl: False for lvl in _LEVELS}
        self._resumes_at: dict[str, datetime | None] = {lvl: None for lvl in _LEVELS}
        self._load_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self):
        """Load persisted circuit breaker state from DB on startup."""
        if not self.trade_logger:
            return

        now = datetime.now(timezone.utc)
        for level in _LEVELS:
            state = self.trade_logger.get_circuit_breaker_state(level)
            if state and state.tripped:
                if state.resumes_at and now < state.resumes_at:
                    self._tripped[level] = True
                    self._resumes_at[level] = state.resumes_at
                    logger.info(
                        "Loaded tripped %s circuit breaker, resumes at %s",
                        level,
                        state.resumes_at.isoformat(),
                    )
                else:
                    # Past resume time -- auto-reset
                    self._tripped[level] = False
                    self._resumes_at[level] = None
                    self.trade_logger.update_circuit_breaker(level, tripped=False)
                    logger.info(
                        "Auto-reset expired %s circuit breaker on startup", level
                    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, starting_equity: float) -> tuple[bool, str]:
        """
        Check if any circuit breaker is currently tripped.

        Args:
            starting_equity: Account equity at start of period (unused for
                the pure check -- kept for interface consistency with update()).

        Returns:
            (is_clear, reason) -- True if trading is allowed.
        """
        now = datetime.now(timezone.utc)

        for level in _LEVELS:
            if self._tripped[level]:
                if self._resumes_at[level] and now >= self._resumes_at[level]:
                    self._reset(level)
                else:
                    return (
                        False,
                        f"{level} circuit breaker tripped until {self._resumes_at[level]}",
                    )

        return True, ""

    def update(self, starting_equity: float):
        """
        Called after each trade close.  Checks whether cumulative losses
        in the current daily / weekly / monthly window have breached the
        configured limit.

        Uses trade_logger.get_pnl_since() to retrieve total PnL for the
        window, then compares the loss (if any) against the limit expressed
        as a percentage of *starting_equity*.

        Daily limit:   DAILY_LOSS_LIMIT_PCT   -> resumes at midnight UTC
        Weekly limit:  WEEKLY_LOSS_LIMIT_PCT   -> resumes at Monday 00:00 UTC
        Monthly limit: MONTHLY_LOSS_LIMIT_PCT  -> resumes at 1st of next month 00:00 UTC
        """
        if not self.trade_logger:
            return
        if starting_equity <= 0:
            logger.warning("Cannot evaluate circuit breakers with equity <= 0")
            return

        now = datetime.now(timezone.utc)

        # Build (level, window_start, resume_at) tuples
        checks = [
            (
                "DAILY",
                now.replace(hour=0, minute=0, second=0, microsecond=0),
                self._next_midnight_utc(),
            ),
            (
                "WEEKLY",
                now - timedelta(days=now.weekday()),  # Monday of this week
                self._next_monday_utc(),
            ),
            (
                "MONTHLY",
                now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                self._next_month_start_utc(),
            ),
        ]
        # Normalise the weekly window start to midnight
        weekly_start = checks[1][1].replace(hour=0, minute=0, second=0, microsecond=0)
        checks[1] = ("WEEKLY", weekly_start, checks[1][2])

        for level, window_start, resumes_at in checks:
            if self._tripped[level]:
                # Already tripped -- nothing to do until reset.
                continue

            pnl = self.trade_logger.get_pnl_since(window_start)
            if pnl >= 0:
                # Profitable or break-even -- no action.
                continue

            loss_pct = abs(pnl) / starting_equity * 100.0
            limit_pct = _LIMIT_MAP[level]

            if loss_pct >= limit_pct:
                self._trip(level, loss_pct, resumes_at)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trip(self, level: str, loss_pct: float, resumes_at: datetime):
        """Trip a circuit breaker level."""
        self._tripped[level] = True
        self._resumes_at[level] = resumes_at

        logger.warning(
            "CIRCUIT BREAKER TRIPPED: %s -- loss %.2f%% exceeds %.2f%% limit. "
            "Trading paused until %s",
            level,
            loss_pct,
            _LIMIT_MAP[level],
            resumes_at.isoformat(),
        )

        if self.trade_logger:
            self.trade_logger.update_circuit_breaker(
                level, tripped=True, resumes_at=resumes_at
            )

    def _reset(self, level: str):
        """Reset a circuit breaker level."""
        self._tripped[level] = False
        self._resumes_at[level] = None

        logger.info("Circuit breaker RESET: %s -- trading may resume", level)

        if self.trade_logger:
            self.trade_logger.update_circuit_breaker(level, tripped=False)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_tripped(self) -> bool:
        """True if any level is currently tripped."""
        return any(self._tripped.values())

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _next_midnight_utc() -> datetime:
        """Next midnight UTC."""
        now = datetime.now(timezone.utc)
        return (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    @staticmethod
    def _next_monday_utc() -> datetime:
        """Next Monday 00:00 UTC."""
        now = datetime.now(timezone.utc)
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return (now + timedelta(days=days_until_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    @staticmethod
    def _next_month_start_utc() -> datetime:
        """First day of next month 00:00 UTC."""
        now = datetime.now(timezone.utc)
        if now.month == 12:
            return now.replace(
                year=now.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        return now.replace(
            month=now.month + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
