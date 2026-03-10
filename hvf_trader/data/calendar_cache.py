"""
ForexFactory economic calendar cache.

Fetches weekly calendar from nfs.faireconomy.media, caches to local JSON.
Refreshes daily. Graceful fallback: if fetch fails, uses stale cache;
if no cache exists, news filter is disabled (returns empty list).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_FILE = CACHE_DIR / "calendar_cache.json"
USER_AGENT = "HVF-Trader/1.0"


def refresh_calendar() -> bool:
    """Fetch this week's calendar from ForexFactory and cache locally.

    Returns:
        True if refresh succeeded, False otherwise.
    """
    try:
        req = Request(CALENDAR_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")

        events = json.loads(raw)
        if not isinstance(events, list):
            logger.warning("Calendar response is not a list, skipping cache update")
            return False

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "events": events,
        }
        CACHE_FILE.write_text(json.dumps(cache_data, indent=2))

        high_count = sum(1 for e in events if e.get("impact") == "High")
        logger.info(
            f"Calendar refreshed: {len(events)} events, {high_count} high-impact"
        )
        return True

    except (URLError, OSError, json.JSONDecodeError) as e:
        logger.warning(f"Calendar refresh failed: {e}")
        return False


def load_cached_events() -> list[dict]:
    """Load events from local cache file.

    Returns:
        List of event dicts, or empty list if cache missing/corrupt.
    """
    if not CACHE_FILE.exists():
        return []

    try:
        cache_data = json.loads(CACHE_FILE.read_text())
        return cache_data.get("events", [])
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read calendar cache: {e}")
        return []


def get_cache_age_hours() -> float | None:
    """Return age of cache in hours, or None if no cache."""
    if not CACHE_FILE.exists():
        return None

    try:
        cache_data = json.loads(CACHE_FILE.read_text())
        fetched_at = datetime.fromisoformat(cache_data["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        return age
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def ensure_fresh_cache(max_age_hours: float = 12.0) -> bool:
    """Refresh cache if stale or missing. Returns True if cache is fresh."""
    age = get_cache_age_hours()
    if age is not None and age < max_age_hours:
        return True
    return refresh_calendar()
