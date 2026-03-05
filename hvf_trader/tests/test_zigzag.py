"""Tests for zigzag.py"""

import pytest
import numpy as np
import pandas as pd
from hvf_trader.detector.zigzag import compute_zigzag, Pivot


def _make_df(closes, highs=None, lows=None, n=None):
    """Create a simple OHLCV DataFrame for testing."""
    if n is None:
        n = len(closes)
    if highs is None:
        highs = np.array(closes) + 0.0005
    if lows is None:
        lows = np.array(closes) - 0.0005
    dates = pd.date_range("2025-01-01", periods=n, freq="h")
    atr = np.full(n, 0.002)
    return pd.DataFrame({
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "tick_volume": np.full(n, 100),
        "time": dates,
        "atr": atr,
    })


class TestComputeZigzag:
    def test_returns_pivots_on_trending_data(self):
        """Trending data should produce some pivots."""
        n = 200
        # Create a zigzag pattern: up-down-up-down
        t = np.linspace(0, 8 * np.pi, n)
        closes = 1.1000 + 0.01 * np.sin(t)
        df = _make_df(closes, highs=closes + 0.001, lows=closes - 0.001, n=n)
        pivots = compute_zigzag(df, atr_multiplier=1.5)
        assert len(pivots) >= 2

    def test_pivots_alternate(self):
        """Pivots should alternate between H and L."""
        n = 200
        t = np.linspace(0, 8 * np.pi, n)
        closes = 1.1000 + 0.01 * np.sin(t)
        df = _make_df(closes, highs=closes + 0.001, lows=closes - 0.001, n=n)
        pivots = compute_zigzag(df, atr_multiplier=1.5)
        for i in range(1, len(pivots)):
            assert pivots[i].pivot_type != pivots[i - 1].pivot_type

    def test_flat_data_minimal_pivots(self):
        """Flat data should produce few or no pivots."""
        n = 100
        closes = np.full(n, 1.1000)
        df = _make_df(closes, n=n)
        pivots = compute_zigzag(df, atr_multiplier=1.5)
        assert len(pivots) <= 2

    def test_too_few_bars_returns_empty(self):
        """Fewer than 20 bars should return empty list."""
        n = 10
        closes = np.linspace(1.1, 1.12, n)
        df = _make_df(closes, n=n)
        pivots = compute_zigzag(df, atr_multiplier=1.5)
        assert pivots == []

    def test_pivot_indices_in_range(self):
        """All pivot indices should be valid DataFrame indices."""
        n = 200
        t = np.linspace(0, 6 * np.pi, n)
        closes = 1.1000 + 0.015 * np.sin(t)
        df = _make_df(closes, highs=closes + 0.001, lows=closes - 0.001, n=n)
        pivots = compute_zigzag(df, atr_multiplier=1.5)
        for p in pivots:
            assert 0 <= p.index < n
