"""Tests for search_deal_history retry behavior in deal_utils.py."""

from types import SimpleNamespace
from unittest.mock import patch

from hvf_trader.execution import deal_utils


def _make_deal(ticket, symbol, dtype=1, profit=-100.0, price=1.0, entry=1):
    return SimpleNamespace(
        position_id=ticket,
        symbol=symbol,
        type=dtype,
        profit=profit,
        price=price,
        entry=entry,
        time=0,
    )


class TestSearchDealHistoryRetry:
    def test_resolves_on_second_attempt(self):
        ticket, symbol = 999, "EURUSD"
        deal = _make_deal(ticket, symbol)

        call_count = {"n": 0}

        def fake_history_deals_get(*args, **kwargs):
            call_count["n"] += 1
            # Both the position-filtered and broad calls count as one "attempt"
            # in our retry loop. _query_deal_history makes up to 2 mt5 calls
            # per attempt (by-ticket, then broad fallback). Return empty
            # until call #3 (= start of attempt 2's by-ticket lookup), then
            # return the deal.
            if call_count["n"] < 3:
                return ()
            return (deal,)

        with patch.object(deal_utils, "MT5_AVAILABLE", True), \
             patch.object(deal_utils, "mt5") as mock_mt5, \
             patch.object(deal_utils.time, "sleep") as mock_sleep:
            mock_mt5.history_deals_get.side_effect = fake_history_deals_get
            result = deal_utils.search_deal_history(
                ticket, symbol, retries=3, retry_delay=5.0,
            )

        assert len(result) == 1
        assert result[0].position_id == ticket
        # We retried at least once → time.sleep was invoked
        assert mock_sleep.called

    def test_gives_up_after_exhausting_retries(self):
        ticket, symbol = 999, "EURUSD"

        with patch.object(deal_utils, "MT5_AVAILABLE", True), \
             patch.object(deal_utils, "mt5") as mock_mt5, \
             patch.object(deal_utils.time, "sleep") as mock_sleep:
            mock_mt5.history_deals_get.return_value = ()
            result = deal_utils.search_deal_history(
                ticket, symbol, retries=3, retry_delay=5.0,
            )

        assert result == []
        # 3 attempts → 2 sleeps between them
        assert mock_sleep.call_count == 2

    def test_first_attempt_hit_no_retry(self):
        ticket, symbol = 999, "EURUSD"
        deal = _make_deal(ticket, symbol)

        with patch.object(deal_utils, "MT5_AVAILABLE", True), \
             patch.object(deal_utils, "mt5") as mock_mt5, \
             patch.object(deal_utils.time, "sleep") as mock_sleep:
            mock_mt5.history_deals_get.return_value = (deal,)
            result = deal_utils.search_deal_history(
                ticket, symbol, retries=3, retry_delay=5.0,
            )

        assert len(result) == 1
        # First attempt resolved → no sleeps
        mock_sleep.assert_not_called()

    def test_mt5_unavailable_returns_empty(self):
        with patch.object(deal_utils, "MT5_AVAILABLE", False):
            result = deal_utils.search_deal_history(1, "EURUSD")
        assert result == []
