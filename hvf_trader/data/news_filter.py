"""
MT5 calendar_events() wrapper for filtering high-impact news.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from hvf_trader import config

# Currency mappings for instruments
SYMBOL_CURRENCIES = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "AUDUSD": ["AUD", "USD"],
    "USDJPY": ["USD", "JPY"],
    "GBPJPY": ["GBP", "JPY"],
    "XAUUSD": ["XAU", "USD"],
    "BTCUSD": ["BTC", "USD"],
    "US30": ["USD"],
}


def has_upcoming_news(symbol: str, window_minutes: int = None) -> bool:
    """
    Check if there's high-impact news within the blocking window for the given symbol.

    Args:
        symbol: instrument symbol
        window_minutes: override blocking window (default from config)

    Returns:
        True if high-impact news is upcoming (should block trading)
    """
    if not MT5_AVAILABLE:
        logger.warning("MT5 not available, skipping news filter")
        return False

    window = window_minutes or config.NEWS_BLOCK_MINUTES
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window)
    window_end = now + timedelta(minutes=window)

    currencies = SYMBOL_CURRENCIES.get(symbol, [])
    if not currencies:
        return False

    try:
        events = mt5.calendar_events(window_start, window_end)
    except Exception as e:
        logger.warning(f"calendar_events failed: {e}")
        return False

    if not events:
        return False

    for event in events:
        # Check if event affects our currencies
        event_currency = getattr(event, "currency", "")
        if event_currency not in currencies:
            continue

        # Check importance (HIGH impact only)
        importance = getattr(event, "importance", 0)
        if importance >= 3:  # MT5: 0=none, 1=low, 2=medium, 3=high
            event_time = getattr(event, "time", None)
            if event_time:
                logger.info(
                    f"High-impact news blocking {symbol}: "
                    f"{getattr(event, 'name', 'Unknown')} at {event_time}"
                )
                return True

    return False


def get_upcoming_events(hours_ahead: int = 24) -> list[dict]:
    """
    Get all upcoming economic events in the next N hours.

    Returns:
        List of event dicts with keys: time, currency, name, importance
    """
    if not MT5_AVAILABLE:
        return []

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours_ahead)

    try:
        events = mt5.calendar_events(now, end)
    except Exception:
        return []

    if not events:
        return []

    result = []
    for event in events:
        importance = getattr(event, "importance", 0)
        if importance >= 2:  # Medium and high
            result.append({
                "time": getattr(event, "time", None),
                "currency": getattr(event, "currency", ""),
                "name": getattr(event, "name", ""),
                "importance": importance,
            })

    return sorted(result, key=lambda x: x["time"] if x["time"] else now)
