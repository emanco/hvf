"""Tests for position_sizer.py"""

import pytest
from hvf_trader.risk.position_sizer import calculate_lot_size, validate_lot_size


class TestCalculateLotSize:
    def test_basic_eurusd(self):
        """£500 equity, 1% risk, 50-pip stop on EURUSD"""
        lot = calculate_lot_size(
            equity=500.0,
            risk_pct=1.0,
            stop_distance_price=0.0050,  # 50 pips
            symbol="EURUSD",
        )
        # risk = 500 * 0.01 = £5
        # 50 pips at 0.01 lot = 50 * $0.10 = $5
        # So lot_size should be ~0.01
        assert lot >= 0.01
        assert lot <= 0.10

    def test_tiny_equity_returns_zero(self):
        """Very small equity should return 0 (below 0.01 lot minimum)"""
        lot = calculate_lot_size(
            equity=10.0,
            risk_pct=1.0,
            stop_distance_price=0.0100,  # 100 pips
            symbol="EURUSD",
        )
        # risk = 10 * 0.01 = £0.10, way too small for 0.01 lot
        assert lot == 0.0

    def test_zero_stop_distance(self):
        """Zero stop distance should return 0"""
        lot = calculate_lot_size(
            equity=500.0,
            risk_pct=1.0,
            stop_distance_price=0.0,
            symbol="EURUSD",
        )
        assert lot == 0.0

    def test_negative_values(self):
        """Negative inputs should return 0"""
        lot = calculate_lot_size(
            equity=-500.0,
            risk_pct=1.0,
            stop_distance_price=0.0050,
            symbol="EURUSD",
        )
        assert lot == 0.0


class TestValidateLotSize:
    def test_below_minimum(self):
        assert validate_lot_size(0.005) == 0.0

    def test_at_minimum(self):
        assert validate_lot_size(0.01) == 0.01

    def test_above_maximum(self):
        assert validate_lot_size(15.0) == 10.0

    def test_normal_lot(self):
        assert validate_lot_size(0.05) == 0.05
