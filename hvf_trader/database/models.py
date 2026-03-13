"""
HVF Auto-Trader Database Models

SQLAlchemy declarative models for pattern tracking, trade management,
event logging, equity monitoring, and circuit breaker state persistence.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from hvf_trader.config import DATABASE_URL

Base = declarative_base()


# ─── Pattern Record ─────────────────────────────────────────────────────────

class PatternRecord(Base):
    """Stores detected HVF (Harmonic Volume Framework) patterns."""

    __tablename__ = "pattern_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    direction = Column(String(10))  # 'LONG' or 'SHORT'
    detected_at = Column(DateTime, nullable=False)

    # Price pivots
    h1_price = Column(Float, nullable=False)
    l1_price = Column(Float, nullable=False)
    h2_price = Column(Float, nullable=False)
    l2_price = Column(Float, nullable=False)
    h3_price = Column(Float, nullable=False)
    l3_price = Column(Float, nullable=False)

    # Bar indices for each pivot
    h1_index = Column(Integer)
    l1_index = Column(Integer)
    h2_index = Column(Integer)
    l2_index = Column(Integer)
    h3_index = Column(Integer)
    l3_index = Column(Integer)

    score = Column(Float)
    status = Column(String(20))  # DETECTED, ARMED, TRIGGERED, EXPIRED, INVALIDATED
    pattern_type = Column(String(20), default="HVF")  # HVF, VIPER, KZ_HUNT, LONDON_SWEEP
    pattern_metadata = Column(Text, nullable=True)  # JSON for pattern-specific data

    # Trade levels
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    rrr = Column(Float, nullable=True)

    expired_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PatternRecord(id={self.id}, symbol={self.symbol!r}, "
            f"direction={self.direction!r}, status={self.status!r})>"
        )


# ─── Trade Record ───────────────────────────────────────────────────────────

class TradeRecord(Base):
    """Stores executed trades and their lifecycle state."""

    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_id = Column(Integer, ForeignKey("pattern_records.id"), nullable=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # 'LONG' or 'SHORT'
    pattern_type = Column(String(20), default="HVF")  # HVF, VIPER, KZ_HUNT, LONDON_SWEEP
    pattern_metadata = Column(Text, nullable=True)  # JSON for pattern-specific data
    mt5_ticket = Column(Integer, nullable=True, unique=True)

    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    lot_size = Column(Float, nullable=False)

    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    close_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    pnl_pips = Column(Float, nullable=True)

    status = Column(String(20))  # OPEN, PARTIAL, CLOSED, CANCELLED

    # Partial close tracking
    partial_closed = Column(Boolean, default=False)
    partial_close_price = Column(Float, nullable=True)
    partial_close_at = Column(DateTime, nullable=True)

    # Trailing stop
    trailing_sl = Column(Float, nullable=True)

    # Close reason
    close_reason = Column(String(50), nullable=True)
    # TARGET_1, TARGET_2, TRAILING_STOP, INVALIDATION, MANUAL, CIRCUIT_BREAKER, DISCONNECT

    # Live vs backtest tracking
    intended_entry = Column(Float, nullable=True)  # Pattern's theoretical entry price
    intended_sl = Column(Float, nullable=True)  # Pattern's original SL before spread adjustment
    slippage = Column(Float, nullable=True)  # fill_price - intended_entry (positive = worse)

    notes = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TradeRecord(id={self.id}, symbol={self.symbol!r}, "
            f"direction={self.direction!r}, status={self.status!r}, pnl={self.pnl})>"
        )


# ─── Event Log ──────────────────────────────────────────────────────────────

class EventLog(Base):
    """Every significant system event for audit and debugging."""

    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    event_type = Column(String(50), nullable=False)
    # PATTERN_DETECTED, PATTERN_ARMED, TRADE_OPENED, PARTIAL_CLOSE,
    # TRADE_CLOSED, SL_MODIFIED, CIRCUIT_BREAKER, ERROR, RECONNECT, etc.

    symbol = Column(String(20), nullable=True)
    trade_id = Column(Integer, nullable=True)
    pattern_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)  # JSON string for extra data
    severity = Column(String(10), default="INFO")
    # DEBUG, INFO, WARNING, ERROR, CRITICAL

    def __repr__(self) -> str:
        return (
            f"<EventLog(id={self.id}, type={self.event_type!r}, "
            f"severity={self.severity!r})>"
        )


# ─── Equity Snapshot ────────────────────────────────────────────────────────

class EquitySnapshot(Base):
    """Periodic equity snapshots for drawdown tracking and reporting."""

    __tablename__ = "equity_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    free_margin = Column(Float, nullable=False)
    margin_used = Column(Float, nullable=True)
    open_positions = Column(Integer, nullable=True)
    daily_pnl = Column(Float, nullable=True)
    weekly_pnl = Column(Float, nullable=True)
    monthly_pnl = Column(Float, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<EquitySnapshot(id={self.id}, balance={self.balance}, "
            f"equity={self.equity})>"
        )


# ─── Circuit Breaker State ──────────────────────────────────────────────────

class CircuitBreakerState(Base):
    """Persisted circuit breaker state for loss-limit enforcement."""

    __tablename__ = "circuit_breaker_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(20), nullable=False)  # DAILY, WEEKLY, MONTHLY
    tripped = Column(Boolean, default=False)
    tripped_at = Column(DateTime, nullable=True)
    loss_pct = Column(Float, nullable=True)
    resumes_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CircuitBreakerState(id={self.id}, level={self.level!r}, "
            f"tripped={self.tripped})>"
        )


# ─── Composite Indexes ──────────────────────────────────────────────────────

Index("ix_pattern_symbol_status", PatternRecord.symbol, PatternRecord.status)
Index("ix_trade_symbol_status", TradeRecord.symbol, TradeRecord.status)
Index("ix_event_type_timestamp", EventLog.event_type, EventLog.timestamp)


# ─── Helper Functions ───────────────────────────────────────────────────────

def get_engine(url: str | None = None):
    """Create a SQLAlchemy engine.

    Args:
        url: Database URL. Falls back to DATABASE_URL from config.

    Returns:
        SQLAlchemy Engine instance.
    """
    db_url = url or DATABASE_URL
    engine = create_engine(db_url, echo=False, pool_pre_ping=True)
    if db_url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


def get_session(engine=None):
    """Create a new database session.

    Args:
        engine: SQLAlchemy engine. If None, creates one from config.

    Returns:
        A new SQLAlchemy Session instance.
    """
    if engine is None:
        engine = get_engine()
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def init_db(engine=None):
    """Create all database tables.

    Args:
        engine: SQLAlchemy engine. If None, creates one from config.
    """
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
