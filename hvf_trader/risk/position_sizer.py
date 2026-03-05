"""
Calculate lot size from equity, risk%, and stop distance.

Uses the standard forex position sizing formula:
    risk_amount = equity * (risk_pct / 100)
    stop_pips = stop_distance_price / pip_size
    pip_value_per_lot = contract_size * pip_size * exchange_rate_to_account
    lot_size = risk_amount / (stop_pips * pip_value_per_lot)

The result is floored to the nearest 0.01 lots (minimum MT5 micro-lot).
"""
import math
import logging

from hvf_trader import config

logger = logging.getLogger(__name__)


def calculate_lot_size(
    equity: float,
    risk_pct: float,
    stop_distance_price: float,
    symbol: str,
    point_value: float = None,
    contract_size: float = 100_000,
    account_currency: str = "GBP",
    exchange_rate_to_account: float = 1.0,
) -> float:
    """
    Calculate position size in lots.

    Formula:
        risk_amount = equity * (risk_pct / 100)
        pip_value = contract_size * pip_size * exchange_rate_to_account
        stop_pips = stop_distance_price / pip_size
        lot_size = risk_amount / (stop_pips * pip_value_per_lot)

    For EURUSD/GBPUSD (pip = 0.0001):
        1 standard lot (100,000 units), 1 pip = $10
        0.01 lot (1,000 units), 1 pip = $0.10

    Args:
        equity: current account equity in account currency
        risk_pct: risk percentage (e.g. 1.0 for 1%)
        stop_distance_price: distance from entry to SL in price terms
        symbol: instrument symbol
        point_value: override pip size (if None, lookup from config.PIP_VALUES)
        contract_size: standard lot size (100000 for forex)
        account_currency: account denomination
        exchange_rate_to_account: conversion rate if pip value is in different currency

    Returns:
        Lot size rounded down to 0.01 (minimum MT5 lot for most brokers)
        Returns 0.0 if calculated lot < 0.01 or inputs are invalid
    """
    # --- Input validation ---
    if equity <= 0:
        logger.warning("Invalid equity: %.2f", equity)
        return 0.0
    if risk_pct <= 0:
        logger.warning("Invalid risk_pct: %.4f", risk_pct)
        return 0.0
    if stop_distance_price <= 0:
        logger.warning("Invalid stop_distance_price: %.6f", stop_distance_price)
        return 0.0

    # --- Resolve pip size ---
    pip_size = point_value if point_value is not None else config.PIP_VALUES.get(symbol)
    if pip_size is None or pip_size <= 0:
        logger.error("No pip value found for symbol %s", symbol)
        return 0.0

    # --- Core calculation ---
    risk_amount = equity * (risk_pct / 100.0)

    # Convert stop distance from price to pips
    stop_pips = stop_distance_price / pip_size

    # Value of 1 pip for 1 standard lot, converted to account currency
    pip_value_per_lot = contract_size * pip_size * exchange_rate_to_account

    # Guard against division by zero
    denominator = stop_pips * pip_value_per_lot
    if denominator <= 0:
        logger.warning(
            "Position size denominator is zero or negative: stop_pips=%.4f, pip_value_per_lot=%.4f",
            stop_pips,
            pip_value_per_lot,
        )
        return 0.0

    raw_lot_size = risk_amount / denominator

    # Floor to nearest 0.01 (micro-lot precision)
    lot_size = math.floor(raw_lot_size * 100) / 100.0

    logger.debug(
        "Position sizing: symbol=%s equity=%.2f risk_pct=%.2f%% "
        "stop_distance=%.5f stop_pips=%.1f pip_value_per_lot=%.4f "
        "risk_amount=%.2f raw_lots=%.4f floored_lots=%.2f",
        symbol,
        equity,
        risk_pct,
        stop_distance_price,
        stop_pips,
        pip_value_per_lot,
        risk_amount,
        raw_lot_size,
        lot_size,
    )

    return validate_lot_size(lot_size)


def validate_lot_size(
    lot_size: float, min_lot: float = 0.01, max_lot: float = 10.0
) -> float:
    """
    Clamp lot size to broker limits.

    Args:
        lot_size: calculated lot size
        min_lot: broker minimum lot (default 0.01)
        max_lot: broker maximum lot (default 10.0)

    Returns:
        Clamped lot size. Returns 0.0 if below minimum.
    """
    if lot_size < min_lot:
        return 0.0
    return min(lot_size, max_lot)
