"""Tests for circuit_breaker.py"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from hvf_trader.risk.circuit_breaker import CircuitBreaker


class _QueryStub:
    """Chain-proof no-result query: any attribute/call returns self, except
    .all which yields an empty list. Keeps the mock immune to changes in the
    seeding path's filter/order_by/limit chain."""
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        if name == "all":
            return list
        return self


class MockTradeLogger:
    def __init__(self):
        self._cb_states = {}
        self._pattern_states = []
        self._pnl = 0.0
        # _load_state seeds pattern counters from trade history via
        # trade_logger._session when the pattern-state table is empty
        self._session = MagicMock()
        self._session.query = _QueryStub()

    def get_circuit_breaker_state(self, level):
        return self._cb_states.get(level)

    def get_all_pattern_cb_states(self):
        return self._pattern_states

    def upsert_pattern_cb_state(self, pattern_type, symbol,
                                consecutive_losses, paused_until):
        pass

    def update_circuit_breaker(self, level, tripped, **kwargs):
        state = MagicMock()
        state.tripped = tripped
        state.resumes_at = kwargs.get("resumes_at")
        self._cb_states[level] = state

    def get_daily_pnl(self):
        return self._pnl

    def get_weekly_pnl(self):
        return self._pnl

    def get_monthly_pnl(self):
        return self._pnl

    def get_pnl_since(self, since_dt):
        return self._pnl

    def log_event(self, *args, **kwargs):
        pass


class TestCircuitBreaker:
    def test_initial_state_clear(self):
        """Circuit breaker starts clear with no trade history."""
        logger = MockTradeLogger()
        cb = CircuitBreaker(trade_logger=logger)
        clear, reason = cb.check(500.0)
        assert clear is True
        assert reason == ""

    def test_is_tripped_property(self):
        """is_tripped returns False when nothing tripped."""
        cb = CircuitBreaker(trade_logger=MockTradeLogger())
        assert cb.is_tripped is False

    def test_next_midnight_utc(self):
        """Next midnight should be tomorrow."""
        result = CircuitBreaker._next_midnight_utc()
        now = datetime.now(timezone.utc)
        assert result > now
        assert result.hour == 0
        assert result.minute == 0

    def test_next_monday_utc(self):
        """Next Monday should be in the future."""
        result = CircuitBreaker._next_monday_utc()
        now = datetime.now(timezone.utc)
        assert result > now
        assert result.weekday() == 0  # Monday

    def test_next_month_start_utc(self):
        """Next month start should be day 1."""
        result = CircuitBreaker._next_month_start_utc()
        now = datetime.now(timezone.utc)
        assert result > now
        assert result.day == 1


class _HistoryStub:
    """Query stub returning canned TradeRecord-alikes for streak recompute."""

    def __init__(self, rows):
        self._rows = rows

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        if name == "all":
            return lambda: self._rows
        return self


def _trade(pips):
    r = MagicMock()
    r.pnl_pips = pips
    return r


class TestPatternStreakRevision:
    """revise_pattern_streak undoes phantom losses from estimated PnL.

    Reconciliation's estimate assumes the stop was hit, so a trade that really
    hit TP banks a phantom loss in the streak counter. LONDON_BO/GBPUSD tripped
    a false 48h pause this way on 2026-07-20 (real record was W,L,W,L).
    """

    def _cb_with_history(self, rows, stored_streak, paused_until):
        logger = MockTradeLogger()
        state = MagicMock()
        state.pattern_type = "LONDON_BO"
        state.symbol = "GBPUSD"
        state.consecutive_losses = stored_streak
        state.paused_until = paused_until
        logger._pattern_states = [state]
        cb = CircuitBreaker(trade_logger=logger)
        logger._session.query = _HistoryStub(rows)
        return cb

    def test_corrected_history_lifts_false_pause(self):
        # Newest first: L, W, L, W -> true streak is 1, not 3.
        rows = [_trade(-20.8), _trade(29.5), _trade(-5.4), _trade(37.6)]
        cb = self._cb_with_history(
            rows, 3, datetime.now(timezone.utc) + timedelta(hours=48)
        )
        assert cb.check_pattern("LONDON_BO", "GBPUSD")[0] is False

        cb.revise_pattern_streak("LONDON_BO", "GBPUSD")

        assert cb._pattern_consecutive_losses[("LONDON_BO", "GBPUSD")] == 1
        assert cb.check_pattern("LONDON_BO", "GBPUSD")[0] is True

    def test_revision_never_creates_a_pause(self):
        """A worse corrected streak updates the count but must not trip a pause
        retroactively — the 48h window it would have used is long expired."""
        rows = [_trade(-10.0), _trade(-11.0), _trade(-12.0), _trade(-13.0)]
        cb = self._cb_with_history(rows, 1, None)

        cb.revise_pattern_streak("LONDON_BO", "GBPUSD")

        assert cb._pattern_consecutive_losses[("LONDON_BO", "GBPUSD")] == 4
        assert cb._pattern_paused_until.get(("LONDON_BO", "GBPUSD")) is None
        assert cb.check_pattern("LONDON_BO", "GBPUSD")[0] is True

    def test_unreadable_history_leaves_state_untouched(self):
        cb = self._cb_with_history([], 3, datetime.now(timezone.utc) + timedelta(hours=48))
        cb.trade_logger = None

        cb.revise_pattern_streak("LONDON_BO", "GBPUSD")

        assert cb._pattern_consecutive_losses[("LONDON_BO", "GBPUSD")] == 3
        assert cb.check_pattern("LONDON_BO", "GBPUSD")[0] is False
