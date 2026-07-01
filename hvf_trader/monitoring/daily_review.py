"""Operational-health signals for the daily report.

The standalone "Daily Review" message was merged into the Daily Summary on
2026-07-01 — one Telegram report now answers both "did the bot behave?" (ops
health) and "did the trades work?" (PnL / per-pair). This module provides the
ops-health half via build_ops_health(); the summary renders it.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from hvf_trader.database.models import (
    EventLog,
    PatternCircuitBreakerState,
    TradeRecord,
)

logger = logging.getLogger(__name__)


def _as_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _classify_rejection(details: str) -> str:
    if not details:
        return "other"
    d = details.lower()
    if "news_filter" in d or "calendar cache" in d or "high-impact news" in d:
        return "news"
    if "same_instrument" in d:
        return "same_instrument"
    if "rrr" in d:
        return "rrr"
    if "spread" in d:
        return "spread"
    if "sl too close" in d or "sl_too_close" in d or "min_dist" in d:
        return "sl_too_close"
    if "circuit" in d or "paused" in d:
        return "circuit_breaker"
    if "lot" in d:
        return "lot_size"
    return "other"


def build_ops_health(trade_logger, since_hours: int = 24) -> dict:
    """Operational-health signals for the last `since_hours` — the "did the bot
    behave correctly" half of the old standalone daily review, now folded into
    the daily summary (2026-07-01). Returns a dict the summary renders compactly.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=since_hours)
    session = trade_logger._session

    events = session.query(EventLog).filter(EventLog.timestamp >= since).all()
    reconnects = [e for e in events if e.event_type == "RECONNECT"]
    errors = [e for e in events if (e.severity or "").upper() in ("ERROR", "CRITICAL")]
    rejections = [e for e in events if e.event_type == "TRADE_REJECTED"]
    cb_events = [e for e in events if e.event_type == "CIRCUIT_BREAKER"]

    reject_reasons: Counter = Counter()
    for e in rejections:
        reject_reasons[_classify_rejection(e.details or "")] += 1

    pnl_estimated = (
        session.query(TradeRecord)
        .filter(TradeRecord.closed_at >= since)
        .filter(TradeRecord.pnl_estimated.is_(True))
        .count()
    )

    paused_rows = session.query(PatternCircuitBreakerState).all()
    paused = [
        r for r in paused_rows
        if r.paused_until is not None and _as_utc(r.paused_until) > now
    ]

    # Headline triage — only flag what's genuinely noteworthy.
    issues: list[str] = []
    if errors:
        issues.append(f"{len(errors)} error(s)")
    if len(reconnects) > 1:  # one reconnect is routine
        issues.append(f"{len(reconnects)} reconnects")
    if pnl_estimated:
        issues.append(f"{pnl_estimated} pnl-estimated")
    if cb_events:
        issues.append(f"{len(cb_events)} CB event(s)")
    if paused:
        issues.append(f"{len(paused)} paused")
    headline = "✅ ALL GREEN" if not issues else "⚠️ " + ", ".join(issues)

    return {
        "headline": headline,
        "errors": len(errors),
        "reconnects": len(reconnects),
        "cb_events": len(cb_events),
        "rejections": len(rejections),
        "reject_reasons": reject_reasons,
        "pnl_estimated": pnl_estimated,
        "paused": paused,
        "since_hours": since_hours,
    }
