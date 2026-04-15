"""
Economic news filter using cached ForexFactory calendar data.

Checks if high-impact news is within a blocking window for a given symbol.
Falls back gracefully: if no cache, trading is not blocked.
"""

import logging
from datetime import datetime, timezone, timedelta

from hvf_trader import config
from hvf_trader.data.calendar_cache import load_cached_events, is_cache_stale

logger = logging.getLogger(__name__)

# Map instrument symbols to ForexFactory country codes
SYMBOL_CURRENCIES = {
    "EURUSD": ["EUR", "USD"],
    "NZDUSD": ["NZD", "USD"],
    "EURGBP": ["EUR", "GBP"],
    "USDCHF": ["USD", "CHF"],
    "EURAUD": ["EUR", "AUD"],
    "GBPUSD": ["GBP", "USD"],
    "AUDUSD": ["AUD", "USD"],
    "USDJPY": ["USD", "JPY"],
    "GBPJPY": ["GBP", "JPY"],
    "EURJPY": ["EUR", "JPY"],
    "CHFJPY": ["CHF", "JPY"],
    "XAUUSD": ["XAU", "USD"],
}


def _parse_event_time(date_str: str) -> datetime | None:
    """Parse ForexFactory ISO 8601 date string to UTC datetime."""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def has_upcoming_news(symbol: str, window_minutes: int = None) -> bool:
    """Check if high-impact news is within the blocking window for a symbol.

    Args:
        symbol: instrument symbol (e.g. "EURUSD")
        window_minutes: override blocking window (default from config)

    Returns:
        True if high-impact news is upcoming OR cache is stale/missing (fail-closed).
        False only when cache is fresh and no matching news found.
    """
    window = window_minutes or config.NEWS_BLOCK_MINUTES
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window)
    window_end = now + timedelta(minutes=window)

    # FAIL-CLOSED: block trading if cache is missing or stale
    if is_cache_stale():
        logger.warning(
            f"News filter blocking {symbol}: calendar cache is missing or stale"
        )
        return True

    currencies = SYMBOL_CURRENCIES.get(symbol, [])
    if not currencies:
        return False

    events = load_cached_events()
    if not events:
        return False

    for event in events:
        if event.get("impact") != "High":
            continue

        if event.get("country") not in currencies:
            continue

        event_time = _parse_event_time(event.get("date", ""))
        if event_time is None:
            continue

        if window_start <= event_time <= window_end:
            logger.info(
                f"High-impact news blocking {symbol}: "
                f"{event.get('title', 'Unknown')} ({event['country']}) "
                f"at {event_time:%H:%M UTC}"
            )
            return True

    return False


def get_upcoming_events(hours_ahead: int = 24) -> list[dict]:
    """Get upcoming medium+ impact events in the next N hours.

    Returns:
        List of event dicts with keys: time, currency, title, impact.
    """
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours_ahead)

    events = load_cached_events()
    if not events:
        return []

    result = []
    for event in events:
        if event.get("impact") not in ("High", "Medium"):
            continue

        event_time = _parse_event_time(event.get("date", ""))
        if event_time is None or event_time < now or event_time > end:
            continue

        result.append({
            "time": event_time,
            "currency": event.get("country", ""),
            "title": event.get("title", ""),
            "impact": event.get("impact", ""),
        })

    return sorted(result, key=lambda x: x["time"])
