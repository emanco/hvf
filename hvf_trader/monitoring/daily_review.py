"""Daily execution review — operational health + performance in one message.

Sent automatically at 21:30 UTC weekdays, or on demand via /review command.
Answers two questions: did the bot behave correctly, and did the trades work?
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from hvf_trader.database.models import (
    EquitySnapshot,
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


def build_execution_report(trade_logger, connector, since_hours: int = 24) -> str:
    """Return a Telegram-formatted execution review for the last `since_hours`."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=since_hours)
    session = trade_logger._session

    # ─── Operational metrics ──────────────────────────────────────────────
    events = (
        session.query(EventLog)
        .filter(EventLog.timestamp >= since)
        .all()
    )
    reconnects = [e for e in events if e.event_type == "RECONNECT"]
    errors = [e for e in events if (e.severity or "").upper() in ("ERROR", "CRITICAL")]
    trade_rejections = [e for e in events if e.event_type == "TRADE_REJECTED"]
    circuit_events = [e for e in events if e.event_type == "CIRCUIT_BREAKER"]

    reject_reasons: Counter = Counter()
    for e in trade_rejections:
        reject_reasons[_classify_rejection(e.details or "")] += 1

    pnl_estimated_count = (
        session.query(TradeRecord)
        .filter(TradeRecord.closed_at >= since)
        .filter(TradeRecord.pnl_estimated.is_(True))
        .count()
    )

    # ─── Performance metrics ──────────────────────────────────────────────
    bal_now_row = (
        session.query(EquitySnapshot)
        .order_by(EquitySnapshot.timestamp.desc())
        .first()
    )
    bal_prev_row = (
        session.query(EquitySnapshot)
        .filter(EquitySnapshot.timestamp <= since)
        .order_by(EquitySnapshot.timestamp.desc())
        .first()
    )
    bal_now = bal_now_row.balance if bal_now_row else None
    bal_prev = bal_prev_row.balance if bal_prev_row else None
    balance_delta_24h = (bal_now - bal_prev) if (bal_now is not None and bal_prev is not None) else None

    bal_7d_row = (
        session.query(EquitySnapshot)
        .filter(EquitySnapshot.timestamp <= now - timedelta(days=7))
        .order_by(EquitySnapshot.timestamp.desc())
        .first()
    )
    balance_delta_7d = (
        (bal_now - bal_7d_row.balance)
        if (bal_now is not None and bal_7d_row is not None)
        else None
    )

    closed = (
        session.query(TradeRecord)
        .filter(TradeRecord.closed_at >= since)
        .filter(TradeRecord.status == "CLOSED")
        .all()
    )

    by_pattern: dict[str, dict] = {}
    for t in closed:
        pt = t.pattern_type or "UNKNOWN"
        d = by_pattern.setdefault(
            pt, {"n": 0, "w": 0, "l": 0, "gross_win": 0.0, "gross_loss": 0.0}
        )
        d["n"] += 1
        pips = t.pnl_pips or 0
        pnl = t.pnl or 0
        if pips > 0:
            d["w"] += 1
            d["gross_win"] += pnl
        elif pips < 0:
            d["l"] += 1
            d["gross_loss"] += abs(pnl)

    open_trades = trade_logger.get_open_trades()

    paused_rows = session.query(PatternCircuitBreakerState).all()
    paused = [
        r for r in paused_rows
        if r.paused_until is not None and _as_utc(r.paused_until) > now
    ]

    # ─── Headline triage ──────────────────────────────────────────────────
    issues: list[str] = []
    if errors:
        issues.append(f"{len(errors)} error(s)")
    if len(reconnects) > 1:  # one reconnect is routine, multiple is noteworthy
        issues.append(f"{len(reconnects)} reconnects")
    if pnl_estimated_count:
        issues.append(f"{pnl_estimated_count} pnl-estimated")
    if paused:
        issues.append(f"{len(paused)} paused pair(s)")

    headline = "\u2705 ALL GREEN" if not issues else "\u26a0\ufe0f " + ", ".join(issues)

    # ─── Format ───────────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append(f"<b>\U0001f4cb Daily Review — {now.strftime('%Y-%m-%d %H:%M UTC')}</b>")
    lines.append(f"<b>{headline}</b>")
    lines.append(f"<i>Window: last {since_hours}h</i>")
    lines.append("")

    lines.append("<b>\U0001f527 Operational</b>")
    lines.append(f"• Errors: {len(errors)}")
    lines.append(f"• Reconnects: {len(reconnects)}")
    lines.append(f"• CB events: {len(circuit_events)}")
    lines.append(f"• PnL-estimated closes: {pnl_estimated_count}")
    if trade_rejections:
        breakdown = ", ".join(f"{k}={v}" for k, v in reject_reasons.most_common())
        lines.append(f"• Trade rejections ({len(trade_rejections)}): {breakdown}")
    else:
        lines.append("• Trade rejections: 0")
    lines.append("")

    lines.append("<b>\U0001f4c8 Performance</b>")
    if bal_now is not None:
        lines.append(f"• Balance: ${bal_now:,.2f}")
    if balance_delta_24h is not None:
        sign = "+" if balance_delta_24h >= 0 else ""
        lines.append(f"• 24h Δ: {sign}${balance_delta_24h:,.2f}")
    if balance_delta_7d is not None:
        sign = "+" if balance_delta_7d >= 0 else ""
        lines.append(f"• 7d Δ: {sign}${balance_delta_7d:,.2f}")

    if by_pattern:
        for pt, d in sorted(by_pattern.items()):
            settled = d["w"] + d["l"]
            wr = (100 * d["w"] / settled) if settled else 0
            if d["gross_loss"] > 0:
                pf_str = f"{d['gross_win'] / d['gross_loss']:.2f}"
            elif d["gross_win"] > 0:
                pf_str = "∞"
            else:
                pf_str = "—"
            lines.append(
                f"• {pt}: {d['n']} trades (W{d['w']}/L{d['l']}) "
                f"WR={wr:.0f}% PF={pf_str}"
            )
    else:
        lines.append("• No closed trades in window")

    lines.append(f"• Open positions: {len(open_trades)}")
    if paused:
        paused_list = ", ".join(
            f"{r.pattern_type}/{r.symbol}({r.consecutive_losses}L)" for r in paused
        )
        lines.append(f"• Paused: {paused_list}")

    return "\n".join(lines)
