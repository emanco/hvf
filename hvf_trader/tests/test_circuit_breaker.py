"""Tests for circuit_breaker.py"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from hvf_trader.risk.circuit_breaker import CircuitBreaker


class MockTradeLogger:
    def __init__(self):
        self._cb_states = {}
        self._pnl = 0.0

    def get_circuit_breaker_state(self, level):
        return self._cb_states.get(level)

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
