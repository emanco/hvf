"""
HVF Auto-Trader Event and Trade Logging

Provides structured logging for patterns, trades, equity snapshots,
circuit breaker state, and general events. All timestamps are UTC.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from hvf_trader.config import LOG_BACKUP_COUNT, LOG_DIR, LOG_MAX_BYTES
from hvf_trader.database.models import (
    CircuitBreakerState,
    EquitySnapshot,
    EventLog,
    PatternRecord,
    TradeRecord,
    get_session,
)

logger = logging.getLogger("hvf_trader")


class TradeLogger:
    """Unified logging interface for patterns, trades, events, and equity.

    All database writes are committed immediately. Callers do not need
    to manage transactions unless batching writes for performance.
    """

    def __init__(self, session=None):
        """Initialize TradeLogger with a database session.

        Args:
            session: SQLAlchemy session. If None, creates one from config.
        """
        self._session = session or get_session()

    @property
    def session(self):
        return self._session

    # ─── Event Logging ──────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        symbol: str | None = None,
        trade_id: int | None = None,
        pattern_id: int | None = None,
        details: str | dict | None = None,
        severity: str = "INFO",
    ) -> EventLog:
        """Create an EventLog entry and commit.

        Args:
            event_type: Event category (PATTERN_DETECTED, TRADE_OPENED, etc.).
            symbol: Trading instrument symbol.
            trade_id: Associated trade record ID.
            pattern_id: Associated pattern record ID.
            details: Extra data as string or dict (auto-serialized to JSON).
            severity: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).

        Returns:
            The created EventLog record.
        """
        if isinstance(details, dict):
            details = json.dumps(details)

        event = EventLog(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            symbol=symbol,
            trade_id=trade_id,
            pattern_id=pattern_id,
            details=details,
            severity=severity,
        )
        self._session.add(event)
        self._session.commit()
        logger.log(
            getattr(logging, severity, logging.INFO),
            "[%s] %s %s %s",
            event_type,
            symbol or "",
            details or "",
            f"trade={trade_id}" if trade_id else "",
        )
        return event

    # ─── Pattern Logging ────────────────────────────────────────────────

    def log_pattern(self, pattern_data: dict) -> PatternRecord:
        """Create a PatternRecord from a dictionary and commit.

        Args:
            pattern_data: Dictionary with PatternRecord column names as keys.
                Required keys: symbol, timeframe, detected_at,
                h1_price through l3_price.

        Returns:
            The created PatternRecord with its assigned ID.
        """
        record = PatternRecord(**pattern_data)
        if record.status is None:
            record.status = "DETECTED"
        self._session.add(record)
        self._session.commit()

        self.log_event(
            event_type="PATTERN_DETECTED",
            symbol=record.symbol,
            pattern_id=record.id,
            details={
                "direction": record.direction,
                "score": record.score,
                "timeframe": record.timeframe,
            },
        )
        return record

    def update_pattern_status(self, pattern_id: int, status: str, **kwargs) -> None:
        """Update a pattern's status and optional fields.

        Args:
            pattern_id: ID of the PatternRecord to update.
            status: New status (ARMED, TRIGGERED, EXPIRED, INVALIDATED).
            **kwargs: Additional fields to update (entry_price, stop_loss, etc.).
        """
        record = self._session.get(PatternRecord, pattern_id)
        if record is None:
            logger.warning("PatternRecord %d not found for status update", pattern_id)
            return

        record.status = status
        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)

        self._session.commit()

        event_map = {
            "ARMED": "PATTERN_ARMED",
            "TRIGGERED": "PATTERN_TRIGGERED",
            "EXPIRED": "PATTERN_EXPIRED",
            "INVALIDATED": "PATTERN_INVALIDATED",
        }
        self.log_event(
            event_type=event_map.get(status, f"PATTERN_{status}"),
            symbol=record.symbol,
            pattern_id=pattern_id,
            details={"status": status, **kwargs},
        )

    # ─── Trade Logging ──────────────────────────────────────────────────

    def log_trade_open(self, trade_data: dict) -> TradeRecord:
        """Create a TradeRecord for a newly opened trade and commit.

        Args:
            trade_data: Dictionary with TradeRecord column names as keys.
                Required keys: symbol, direction, entry_price, stop_loss,
                lot_size, opened_at.

        Returns:
            The created TradeRecord with its assigned ID.
        """
        record = TradeRecord(**trade_data)
        if record.status is None:
            record.status = "OPEN"
        self._session.add(record)
        self._session.commit()

        self.log_event(
            event_type="TRADE_OPENED",
            symbol=record.symbol,
            trade_id=record.id,
            pattern_id=record.pattern_id,
            details={
                "direction": record.direction,
                "entry_price": record.entry_price,
                "stop_loss": record.stop_loss,
                "lot_size": record.lot_size,
                "mt5_ticket": record.mt5_ticket,
            },
        )
        return record

    def log_trade_update(self, trade_id: int, **kwargs) -> None:
        """Update arbitrary fields on a trade record.

        Args:
            trade_id: ID of the TradeRecord to update.
            **kwargs: Field-value pairs to set on the record.
        """
        record = self._session.get(TradeRecord, trade_id)
        if record is None:
            logger.warning("TradeRecord %d not found for update", trade_id)
            return

        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)

        self._session.commit()

        # Log SL modifications specifically
        if "trailing_sl" in kwargs or "stop_loss" in kwargs:
            self.log_event(
                event_type="SL_MODIFIED",
                symbol=record.symbol,
                trade_id=trade_id,
                details=kwargs,
            )

    def log_trade_close(
        self,
        trade_id: int,
        close_price: float,
        pnl: float,
        pnl_pips: float,
        close_reason: str,
    ) -> None:
        """Record trade closure with final P&L data.

        Args:
            trade_id: ID of the TradeRecord to close.
            close_price: Price at which the trade was closed.
            pnl: Profit/loss in account currency.
            pnl_pips: Profit/loss in pips.
            close_reason: Why the trade closed (TARGET_1, TARGET_2,
                TRAILING_STOP, INVALIDATION, MANUAL, CIRCUIT_BREAKER,
                DISCONNECT).
        """
        record = self._session.get(TradeRecord, trade_id)
        if record is None:
            logger.warning("TradeRecord %d not found for close", trade_id)
            return

        record.closed_at = datetime.now(timezone.utc)
        record.close_price = close_price
        record.pnl = pnl
        record.pnl_pips = pnl_pips
        record.close_reason = close_reason
        record.status = "CLOSED"
        self._session.commit()

        self.log_event(
            event_type="TRADE_CLOSED",
            symbol=record.symbol,
            trade_id=trade_id,
            pattern_id=record.pattern_id,
            details={
                "close_price": close_price,
                "pnl": pnl,
                "pnl_pips": pnl_pips,
                "close_reason": close_reason,
            },
        )

    def log_partial_close(self, trade_id: int, close_price: float) -> None:
        """Record a partial close on a trade (e.g., 50% at target_1).

        Args:
            trade_id: ID of the TradeRecord to partially close.
            close_price: Price at which the partial close executed.
        """
        record = self._session.get(TradeRecord, trade_id)
        if record is None:
            logger.warning("TradeRecord %d not found for partial close", trade_id)
            return

        record.partial_closed = True
        record.partial_close_price = close_price
        record.partial_close_at = datetime.now(timezone.utc)
        record.status = "PARTIAL"
        self._session.commit()

        self.log_event(
            event_type="PARTIAL_CLOSE",
            symbol=record.symbol,
            trade_id=trade_id,
            details={"partial_close_price": close_price},
        )

    # ─── Equity Snapshots ───────────────────────────────────────────────

    def log_equity_snapshot(
        self,
        balance: float,
        equity: float,
        free_margin: float,
        margin_used: float = 0.0,
        open_positions: int = 0,
        daily_pnl: float = 0.0,
        weekly_pnl: float = 0.0,
        monthly_pnl: float = 0.0,
    ) -> EquitySnapshot:
        """Create a periodic equity snapshot.

        Args:
            balance: Account balance.
            equity: Account equity (balance + unrealized P&L).
            free_margin: Available margin.
            margin_used: Margin currently in use.
            open_positions: Number of open positions.
            daily_pnl: Realized P&L for today.
            weekly_pnl: Realized P&L for this week.
            monthly_pnl: Realized P&L for this month.

        Returns:
            The created EquitySnapshot record.
        """
        snapshot = EquitySnapshot(
            timestamp=datetime.now(timezone.utc),
            balance=balance,
            equity=equity,
            free_margin=free_margin,
            margin_used=margin_used,
            open_positions=open_positions,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            monthly_pnl=monthly_pnl,
        )
        self._session.add(snapshot)
        self._session.commit()
        return snapshot

    # ─── Queries ────────────────────────────────────────────────────────

    def get_open_trades(self) -> list[TradeRecord]:
        """Return all trades with status OPEN or PARTIAL.

        Returns:
            List of TradeRecord instances.
        """
        return (
            self._session.query(TradeRecord)
            .filter(TradeRecord.status.in_(["OPEN", "PARTIAL"]))
            .all()
        )

    def get_armed_patterns(self) -> list[PatternRecord]:
        """Return all patterns with status ARMED.

        Returns:
            List of PatternRecord instances.
        """
        return (
            self._session.query(PatternRecord)
            .filter(PatternRecord.status == "ARMED")
            .all()
        )

    def get_recent_patterns(self, hours: int = 24) -> list[PatternRecord]:
        """Return patterns detected within the last N hours (any status)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return (
            self._session.query(PatternRecord)
            .filter(PatternRecord.detected_at >= cutoff)
            .all()
        )

    def get_pnl_since(self, since_dt: datetime) -> float:
        """Sum P&L of all trades closed since a given datetime.

        Args:
            since_dt: Start of the window (inclusive).

        Returns:
            Total realized P&L since since_dt, or 0.0 if no trades.
        """
        now = datetime.now(timezone.utc)
        results = (
            self._session.query(TradeRecord.pnl)
            .filter(
                TradeRecord.status == "CLOSED",
                TradeRecord.closed_at >= since_dt,
                TradeRecord.closed_at <= now,
                TradeRecord.pnl.isnot(None),
            )
            .all()
        )
        return sum(r.pnl for r in results)

    def get_daily_pnl(self) -> float:
        """Sum P&L of all trades closed today (UTC midnight to now).

        Returns:
            Total realized P&L for today, or 0.0 if no trades.
        """
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        results = (
            self._session.query(TradeRecord.pnl)
            .filter(
                TradeRecord.status == "CLOSED",
                TradeRecord.closed_at >= start_of_day,
                TradeRecord.closed_at <= now,
                TradeRecord.pnl.isnot(None),
            )
            .all()
        )
        return sum(r.pnl for r in results)

    def get_weekly_pnl(self) -> float:
        """Sum P&L of trades closed this week (Monday 00:00 UTC to now).

        Returns:
            Total realized P&L for this week, or 0.0 if no trades.
        """
        now = datetime.now(timezone.utc)
        days_since_monday = now.weekday()
        start_of_week = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        results = (
            self._session.query(TradeRecord.pnl)
            .filter(
                TradeRecord.status == "CLOSED",
                TradeRecord.closed_at >= start_of_week,
                TradeRecord.closed_at <= now,
                TradeRecord.pnl.isnot(None),
            )
            .all()
        )
        return sum(r.pnl for r in results)

    def get_monthly_pnl(self) -> float:
        """Sum P&L of trades closed this month (1st 00:00 UTC to now).

        Returns:
            Total realized P&L for this month, or 0.0 if no trades.
        """
        now = datetime.now(timezone.utc)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        results = (
            self._session.query(TradeRecord.pnl)
            .filter(
                TradeRecord.status == "CLOSED",
                TradeRecord.closed_at >= start_of_month,
                TradeRecord.closed_at <= now,
                TradeRecord.pnl.isnot(None),
            )
            .all()
        )
        return sum(r.pnl for r in results)

    # ─── Performance Monitor Queries ─────────────────────────────────────

    def get_recent_closed_trades(
        self,
        limit: int = 20,
        pattern_type: str = None,
        symbol: str = None,
    ) -> list[TradeRecord]:
        """Return the most recent closed trades, optionally filtered."""
        query = self._session.query(TradeRecord).filter(
            TradeRecord.status == "CLOSED",
            TradeRecord.pnl.isnot(None),
        )
        if pattern_type:
            query = query.filter(TradeRecord.pattern_type == pattern_type)
        if symbol:
            query = query.filter(TradeRecord.symbol == symbol)
        return query.order_by(TradeRecord.closed_at.desc()).limit(limit).all()

    def get_closed_trade_count(self) -> int:
        """Return total number of closed trades."""
        return self._session.query(TradeRecord).filter(
            TradeRecord.status == "CLOSED",
        ).count()

    # ─── Circuit Breaker ────────────────────────────────────────────────

    def get_circuit_breaker_state(self, level: str) -> CircuitBreakerState:
        """Get the latest circuit breaker state for a given level.

        If no state exists for the level, creates a default (not tripped)
        record and returns it.

        Args:
            level: Circuit breaker level (DAILY, WEEKLY, MONTHLY).

        Returns:
            The most recent CircuitBreakerState for the level.
        """
        state = (
            self._session.query(CircuitBreakerState)
            .filter(CircuitBreakerState.level == level)
            .order_by(CircuitBreakerState.id.desc())
            .first()
        )
        if state is None:
            state = CircuitBreakerState(level=level, tripped=False)
            self._session.add(state)
            self._session.commit()
        return state

    def update_circuit_breaker(
        self,
        level: str,
        tripped: bool,
        loss_pct: float | None = None,
        resumes_at: datetime | None = None,
        notes: str | None = None,
    ) -> CircuitBreakerState:
        """Update or create a circuit breaker state record.

        Creates a new record each time to preserve history.

        Args:
            level: Circuit breaker level (DAILY, WEEKLY, MONTHLY).
            tripped: Whether the breaker is tripped.
            loss_pct: The loss percentage that tripped it.
            resumes_at: When trading is allowed to resume.
            notes: Optional notes about the trip.

        Returns:
            The newly created CircuitBreakerState record.
        """
        state = CircuitBreakerState(
            level=level,
            tripped=tripped,
            tripped_at=datetime.now(timezone.utc) if tripped else None,
            loss_pct=loss_pct,
            resumes_at=resumes_at,
            notes=notes,
        )
        self._session.add(state)
        self._session.commit()

        self.log_event(
            event_type="CIRCUIT_BREAKER",
            details={
                "level": level,
                "tripped": tripped,
                "loss_pct": loss_pct,
                "resumes_at": resumes_at.isoformat() if resumes_at else None,
            },
            severity="WARNING" if tripped else "INFO",
        )
        return state


# ─── File-Based Logging Setup ───────────────────────────────────────────────


class _TradeEventFilter(logging.Filter):
    """Filter that only passes trade-related log records."""

    TRADE_KEYWORDS = frozenset({
        "TRADE_OPENED",
        "TRADE_CLOSED",
        "PARTIAL_CLOSE",
        "SL_MODIFIED",
    })

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return any(keyword in message for keyword in self.TRADE_KEYWORDS)


def setup_file_logging() -> logging.Logger:
    """Configure rotating file handlers for the hvf_trader logger.

    Creates three log files under the configured LOG_DIR:
        - main.log:   All events at INFO level and above.
        - trades.log: Trade-specific events only (open, close, SL changes).
        - errors.log: WARNING level and above for quick error triage.

    Uses RotatingFileHandler with LOG_MAX_BYTES and LOG_BACKUP_COUNT
    from hvf_trader.config.

    Returns:
        The configured 'hvf_trader' logger instance.
    """
    hvf_logger = logging.getLogger("hvf_trader")
    hvf_logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on repeated calls
    if hvf_logger.handlers:
        return hvf_logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Main log: all INFO+
    main_handler = RotatingFileHandler(
        filename=str(LOG_DIR / "main.log"),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    main_handler.setLevel(logging.INFO)
    main_handler.setFormatter(formatter)

    # Trades log: trade events only
    trades_handler = RotatingFileHandler(
        filename=str(LOG_DIR / "trades.log"),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    trades_handler.setLevel(logging.INFO)
    trades_handler.setFormatter(formatter)
    trades_handler.addFilter(_TradeEventFilter())

    # Errors log: WARNING+
    errors_handler = RotatingFileHandler(
        filename=str(LOG_DIR / "errors.log"),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    errors_handler.setLevel(logging.WARNING)
    errors_handler.setFormatter(formatter)

    hvf_logger.addHandler(main_handler)
    hvf_logger.addHandler(trades_handler)
    hvf_logger.addHandler(errors_handler)

    return hvf_logger
