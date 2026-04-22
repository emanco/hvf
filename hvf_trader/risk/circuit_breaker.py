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

# Per-pattern consecutive loss tracking
_PATTERN_LOSS_PAUSE_THRESHOLD = 3  # 3 consecutive losses → 48h pause
_PATTERN_PAUSE_HOURS = 48


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
        # Period-start equity for accurate loss% calculation
        self._period_start_equity: dict[str, float] = {}
        self._period_start_date: dict[str, str] = {}
        # Per-(pattern, symbol) consecutive loss tracking
        self._pattern_consecutive_losses: dict[tuple[str, str], int] = {}
        self._pattern_paused_until: dict[tuple[str, str], datetime | None] = {}
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
                resumes_at = state.resumes_at
                if resumes_at is not None and resumes_at.tzinfo is None:
                    resumes_at = resumes_at.replace(tzinfo=timezone.utc)
                if resumes_at and now < resumes_at:
                    self._tripped[level] = True
                    self._resumes_at[level] = resumes_at
                    logger.info(
                        "Loaded tripped %s circuit breaker, resumes at %s",
                        level,
                        resumes_at.isoformat(),
                    )
                else:
                    # Past resume time -- auto-reset
                    self._tripped[level] = False
                    self._resumes_at[level] = None
                    self.trade_logger.update_circuit_breaker(level, tripped=False)
                    logger.info(
                        "Auto-reset expired %s circuit breaker on startup", level
                    )

        # Per-(pattern, symbol) consecutive-loss state.
        # On first-ever startup (table empty) we backfill from recent trades so
        # the counter reflects current reality rather than starting at 0.
        existing_rows = self.trade_logger.get_all_pattern_cb_states()
        if not existing_rows:
            seeded = self._seed_from_trade_history()
            if seeded:
                existing_rows = self.trade_logger.get_all_pattern_cb_states()

        for row in existing_rows:
            key = (row.pattern_type, row.symbol)
            self._pattern_consecutive_losses[key] = row.consecutive_losses
            paused_until = row.paused_until
            if paused_until is not None and paused_until.tzinfo is None:
                paused_until = paused_until.replace(tzinfo=timezone.utc)
            if paused_until is not None and now >= paused_until:
                # Pause expired during downtime — reset
                self._pattern_consecutive_losses[key] = 0
                self._pattern_paused_until[key] = None
                self.trade_logger.upsert_pattern_cb_state(
                    row.pattern_type, row.symbol, 0, None
                )
                logger.info(
                    "Auto-reset expired pattern circuit breaker for %s/%s on startup",
                    row.pattern_type, row.symbol,
                )
            else:
                self._pattern_paused_until[key] = paused_until
                if paused_until is not None:
                    logger.info(
                        "Loaded paused %s/%s, resumes at %s (%d consecutive losses)",
                        row.pattern_type, row.symbol,
                        paused_until.isoformat(),
                        row.consecutive_losses,
                    )
                elif row.consecutive_losses > 0:
                    logger.info(
                        "Loaded %s/%s with %d consecutive losses",
                        row.pattern_type, row.symbol,
                        row.consecutive_losses,
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

    def update(self, current_balance: float):
        """
        Called every scanner cycle. Checks whether cumulative losses
        in the current daily / weekly / monthly window have breached the
        configured limit.

        Uses trade_logger.get_pnl_since() to retrieve total PnL for the
        window, then compares the loss against the limit expressed
        as a percentage of the period-start equity (captured on first call
        per period, not current balance which shrinks as losses accrue).

        Daily limit:   DAILY_LOSS_LIMIT_PCT   -> resumes at midnight UTC
        Weekly limit:  WEEKLY_LOSS_LIMIT_PCT   -> resumes at Monday 00:00 UTC
        Monthly limit: MONTHLY_LOSS_LIMIT_PCT  -> resumes at 1st of next month 00:00 UTC
        """
        if not self.trade_logger:
            return
        if current_balance <= 0:
            logger.warning("Cannot evaluate circuit breakers with balance <= 0")
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

            # Capture period-start equity on first call in each period
            period_key = window_start.isoformat()
            if self._period_start_date.get(level) != period_key:
                self._period_start_equity[level] = current_balance
                self._period_start_date[level] = period_key

            base_equity = self._period_start_equity.get(level, current_balance)

            pnl = self.trade_logger.get_pnl_since(window_start)
            if pnl >= 0:
                # Profitable or break-even -- no action.
                continue

            loss_pct = abs(pnl) / base_equity * 100.0
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

    # ------------------------------------------------------------------
    # Per-pattern circuit breaker
    # ------------------------------------------------------------------

    def check_pattern(self, pattern_type: str, symbol: str) -> tuple[bool, str]:
        """
        Check if a specific (pattern, symbol) is paused due to consecutive losses.

        Returns:
            (is_clear, reason) -- True if trading is allowed.
        """
        now = datetime.now(timezone.utc)
        key = (pattern_type, symbol)
        paused_until = self._pattern_paused_until.get(key)

        if paused_until is not None:
            if now >= paused_until:
                # Pause expired — reset
                self._pattern_consecutive_losses[key] = 0
                self._pattern_paused_until[key] = None
                self._persist_pattern(pattern_type, symbol)
                logger.info(
                    "Pattern circuit breaker RESET for %s/%s", pattern_type, symbol
                )
                return True, ""
            else:
                return (
                    False,
                    f"{pattern_type}/{symbol} paused until {paused_until.isoformat()} "
                    f"({self._pattern_consecutive_losses.get(key, 0)} consecutive losses)",
                )

        return True, ""

    def record_pattern_result(self, pattern_type: str, symbol: str, is_win: bool):
        """
        Record a trade result for per-(pattern, symbol) consecutive loss tracking.

        Args:
            pattern_type: e.g. "KZ_HUNT", "QUANTUM_LONDON", "LONDON_BO"
            symbol: e.g. "EURGBP"
            is_win: True if trade was profitable
        """
        key = (pattern_type, symbol)
        if is_win:
            if self._pattern_consecutive_losses.get(key, 0) != 0:
                self._pattern_consecutive_losses[key] = 0
                self._persist_pattern(pattern_type, symbol)
            return

        # Loss
        current = self._pattern_consecutive_losses.get(key, 0) + 1
        self._pattern_consecutive_losses[key] = current

        if current >= _PATTERN_LOSS_PAUSE_THRESHOLD:
            pause_until = datetime.now(timezone.utc) + timedelta(
                hours=_PATTERN_PAUSE_HOURS
            )
            self._pattern_paused_until[key] = pause_until
            logger.warning(
                "PATTERN CIRCUIT BREAKER TRIPPED: %s/%s -- %d consecutive losses. "
                "Paused for %dh until %s",
                pattern_type, symbol,
                current,
                _PATTERN_PAUSE_HOURS,
                pause_until.isoformat(),
            )

        self._persist_pattern(pattern_type, symbol)

    def _persist_pattern(self, pattern_type: str, symbol: str) -> None:
        """Write the in-memory per-(pattern, symbol) state to the DB."""
        if not self.trade_logger:
            return
        key = (pattern_type, symbol)
        try:
            self.trade_logger.upsert_pattern_cb_state(
                pattern_type,
                symbol,
                self._pattern_consecutive_losses.get(key, 0),
                self._pattern_paused_until.get(key),
            )
        except Exception as e:
            logger.error(
                "Failed to persist pattern CB state for %s/%s: %s",
                pattern_type, symbol, e,
            )

    def _seed_from_trade_history(self) -> bool:
        """Backfill per-(pattern, symbol) consecutive-loss counters from recent trades.

        Runs once on first startup after this feature is deployed (when the
        pattern_circuit_breaker_states table is empty). For each (pattern, symbol),
        counts the streak of losses since the most recent win on that pair.
        Uses pnl_pips as the source of truth (pnl can be falsely 0 when MT5
        deal-search fails).
        """
        try:
            from hvf_trader.database.models import TradeRecord
        except Exception as e:
            logger.error("Seed pattern CB: import failed: %s", e)
            return False

        session = self.trade_logger._session
        rows = (
            session.query(TradeRecord)
            .filter(TradeRecord.status == "CLOSED")
            .filter(TradeRecord.pattern_type.isnot(None))
            .filter(TradeRecord.symbol.isnot(None))
            .order_by(TradeRecord.closed_at.desc())
            .limit(500)
            .all()
        )

        now = datetime.now(timezone.utc)
        streaks: dict[tuple[str, str], int] = {}
        ended: set[tuple[str, str]] = set()

        for r in rows:
            key = (r.pattern_type, r.symbol)
            if key in ended:
                continue
            pips = r.pnl_pips or 0
            if pips > 0:
                ended.add(key)
            elif pips < 0:
                streaks[key] = streaks.get(key, 0) + 1

        if not streaks:
            return False

        for (pt, sym), streak in streaks.items():
            key = (pt, sym)
            self._pattern_consecutive_losses[key] = streak
            paused_until = None
            if streak >= _PATTERN_LOSS_PAUSE_THRESHOLD:
                paused_until = now + timedelta(hours=_PATTERN_PAUSE_HOURS)
                self._pattern_paused_until[key] = paused_until
                logger.warning(
                    "Seeded %s/%s with %d consecutive losses → PAUSED until %s",
                    pt, sym, streak, paused_until.isoformat(),
                )
            else:
                logger.info(
                    "Seeded %s/%s with %d consecutive losses (below threshold)",
                    pt, sym, streak,
                )
            try:
                self.trade_logger.upsert_pattern_cb_state(pt, sym, streak, paused_until)
            except Exception as e:
                logger.error("Seed: failed to persist %s/%s: %s", pt, sym, e)

        return True

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
