"""
Shared deal-matching and PnL estimation utilities.

Used by both TradeMonitor and Reconciliator to avoid logic duplication.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from hvf_trader import config

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


def _query_deal_history(ticket: int, symbol: str, lookback_days: int):
    """Single query attempt: by-ticket, then broad symbol-filtered fallback.

    Two IC Markets quirks are handled here:

    1. Clock skew — ``deal.time`` is the broker's server time *labelled* as
       UTC, running ~2-3h ahead of true UTC. A ``date_to`` of ``now(utc)``
       therefore sits *below* the timestamp of any deal closed in the last
       ~3h, silently excluding the freshest deals — exactly the ones a close
       or late-update lookup wants. We pad the upper bound a full day into
       the future (no real deals live there) to swallow the skew. Verified
       2026-07-27: trade 232's close deal was invisible to ``date_to=now``
       but present with ``now + 1d``.

    2. ``position=ticket`` is unreliable: it returns an empty set *or* a
       non-empty set that omits the target position's own deals (it appears
       to ignore the filter and hand back unrelated recent deals). The old
       ``if not deals`` guard only fell back on *empty*, so a wrong-but-
       non-empty result defeated the fallback and the real close deal was
       never found. Fall back to the broad symbol-filtered search whenever
       the by-ticket set lacks the target position.
    """
    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=lookback_days)
    to_date = now + timedelta(days=1)  # pad past broker/UTC clock skew (quirk 1)

    deals = mt5.history_deals_get(from_date, to_date, position=ticket) or ()

    # Broad fallback when position=ticket didn't actually return the target
    # position's deals (quirk 2) — not just when it returned nothing.
    if not any(getattr(d, "position_id", None) == ticket for d in deals):
        all_deals = mt5.history_deals_get(from_date, to_date)
        if all_deals:
            deals = [d for d in all_deals if d.symbol == symbol]

    return list(deals)


def search_deal_history(
    ticket: int,
    symbol: str,
    lookback_days: int = 7,
    retries: int = 3,
    retry_delay: float = 5.0,
):
    """Search MT5 deal history for a position, with retries + IC Markets broad fallback.

    The broker can take several seconds (or longer) to write the exit deal into
    history after the position disappears from positions_get. Retry the lookup
    a few times with a short delay before giving up.

    Args:
        ticket: MT5 position ticket.
        symbol: Instrument symbol.
        lookback_days: How far back to search.
        retries: Total attempts (>=1). Default 3 → max 2 retries.
        retry_delay: Seconds between attempts.

    Returns:
        List of deal objects, or empty list.
    """
    if not MT5_AVAILABLE:
        return []

    for attempt in range(1, retries + 1):
        deals = _query_deal_history(ticket, symbol, lookback_days)
        if deals:
            if attempt > 1:
                logger.info(
                    f"[DEAL_SEARCH] Resolved on attempt {attempt}/{retries} "
                    f"for ticket={ticket} {symbol} ({len(deals)} deals)"
                )
            return deals
        if attempt < retries:
            logger.info(
                f"[DEAL_SEARCH] Empty result on attempt {attempt}/{retries} "
                f"for ticket={ticket} {symbol}, retrying in {retry_delay}s"
            )
            time.sleep(retry_delay)

    logger.info(
        f"[DEAL_SEARCH] No deals found for ticket={ticket} {symbol} "
        f"after {retries} attempts"
    )
    return []


def find_close_deal(deals, ticket: int, symbol: str, direction: str,
                    opened_at: datetime = None):
    """Two-pass matching to find the closing deal for a trade.

    Pass 1: Exact position ticket match (most reliable when available).
    Pass 2: Broader entry-based matching (for IC Markets quirks).

    Args:
        deals: List of MT5 deal objects.
        ticket: MT5 position ticket.
        symbol: Instrument symbol.
        direction: 'LONG' or 'SHORT'.
        opened_at: Trade open time (for filtering out old deals).

    Returns:
        The matching deal object, or None.
    """
    if not deals:
        return None

    expected_deal_type = 1 if direction == "LONG" else 0
    trade_open_time = opened_at
    if trade_open_time and trade_open_time.tzinfo is None:
        trade_open_time = trade_open_time.replace(tzinfo=timezone.utc)

    close_deal = None

    # Pass 1: exact position ticket match
    for deal in deals:
        if deal.position_id != ticket or deal.symbol != symbol:
            continue
        if deal.type != expected_deal_type:
            continue
        if trade_open_time:
            deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
            if deal_time < (trade_open_time - timedelta(seconds=60)):
                continue
        close_deal = deal

    # Pass 2: fallback to entry-based matching
    if not close_deal:
        for deal in deals:
            if deal.symbol != symbol:
                continue
            if deal.type != expected_deal_type:
                continue
            if deal.entry not in (0, 1):
                continue
            if trade_open_time:
                deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
                if deal_time < (trade_open_time - timedelta(seconds=60)):
                    continue
            close_deal = deal

    return close_deal


def _dollar_per_pip_per_lot(symbol: str, pip_value: float) -> float:
    """Account-currency value of one pip for one lot of `symbol`.

    Derived from the broker's own tick specs (trade_tick_value is the
    account-currency value of a trade_tick_size move for 1 lot) — correct
    for forex, crypto CFDs, and index CFDs alike. Falls back to the
    forex-only $10/pip approximation when MT5/specs are unavailable.

    Added 2026-07-02 after trade 207 (US500): the flat $10/pip + default
    0.0001 pip estimated a 26.4-point index loss as -$1,056,000 and
    tripped all three circuit breakers.
    """
    if MT5_AVAILABLE:
        try:
            si = mt5.symbol_info(symbol)
            if si and si.trade_tick_size > 0 and si.trade_tick_value > 0:
                return si.trade_tick_value / si.trade_tick_size * pip_value
        except Exception:
            logger.warning("symbol_info failed for %s; using $10/pip fallback",
                           symbol, exc_info=True)
    return 10.0


def estimate_fallback_pnl(trade_record, close_price: float) -> tuple[float, float]:
    """Estimate PnL when no deal history is available.

    For partial-closed trades, combines the known partial profit
    with the estimated remainder close.

    Args:
        trade_record: TradeRecord or SimpleNamespace with trade fields.
        close_price: Estimated close price.

    Returns:
        Tuple of (pnl_dollars, pnl_pips).
    """
    pip_value = config.PIP_VALUES.get(trade_record.symbol)
    if pip_value is None:
        # Unknown symbol: treat 1.0 price unit as the reporting "pip"
        # (sane for indices/crypto; a forex symbol missing from
        # PIP_VALUES would be a config bug — log it loudly).
        logger.warning("%s missing from config.PIP_VALUES; assuming pip=1.0 "
                       "point for PnL estimate", trade_record.symbol)
        pip_value = 1.0
    direction = trade_record.direction
    original_lots = trade_record.lot_size or 0.01
    dollar_per_pip = _dollar_per_pip_per_lot(trade_record.symbol, pip_value)

    # Remainder pips (close_price vs entry)
    if direction == "LONG":
        remainder_pips = (close_price - trade_record.entry_price) / pip_value
    else:
        remainder_pips = (trade_record.entry_price - close_price) / pip_value

    if trade_record.partial_closed and trade_record.partial_close_price:
        partial_pct = config.PARTIAL_CLOSE_PCT  # 0.60
        remainder_pct = 1.0 - partial_pct       # 0.40

        if direction == "LONG":
            partial_pips = (trade_record.partial_close_price - trade_record.entry_price) / pip_value
        else:
            partial_pips = (trade_record.entry_price - trade_record.partial_close_price) / pip_value

        partial_pnl = partial_pips * dollar_per_pip * original_lots * partial_pct
        remainder_pnl = remainder_pips * dollar_per_pip * original_lots * remainder_pct
        total_pnl = partial_pnl + remainder_pnl
        total_pips = (partial_pips * partial_pct) + (remainder_pips * remainder_pct)
        return total_pnl, total_pips
    else:
        pnl = remainder_pips * dollar_per_pip * original_lots
        return pnl, remainder_pips


def combine_split_pnl(trade_record, main_close_price: float, main_close_profit: float):
    """Combine main (40%) close PnL with the known partial (60%) close for a split order.

    Used when deal history DID resolve for the main ticket but the trade is a
    split order with an earlier partial close. MT5's deal.profit only covers
    the 40% remainder — the 60% partial's profit needs to be added.

    Returns:
        (total_pnl_dollars, total_pips) averaged across the full lot.
        If the trade is not a split order or partial_closed is False, returns
        (main_close_profit, main_pips) unchanged.
    """
    pip_value = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
    direction = trade_record.direction

    if direction == "LONG":
        main_pips = (main_close_price - trade_record.entry_price) / pip_value
    else:
        main_pips = (trade_record.entry_price - main_close_price) / pip_value

    if not (
        trade_record.partial_closed
        and trade_record.partial_close_price
        and getattr(trade_record, 'mt5_ticket_partial', None)
    ):
        # Not a split, or partial not closed — main PnL is the whole story
        return main_close_profit, main_pips

    # Try to find the partial's actual close deal for exact profit
    partial_profit = None
    try:
        partial_deals = search_deal_history(
            trade_record.mt5_ticket_partial, trade_record.symbol
        )
        if partial_deals:
            cd = find_close_deal(
                partial_deals, trade_record.mt5_ticket_partial,
                trade_record.symbol, direction, trade_record.opened_at,
            )
            if cd:
                partial_profit = cd.profit
    except Exception as e:
        logger.warning("Partial deal lookup failed: %s", e)

    if direction == "LONG":
        partial_pips = (trade_record.partial_close_price - trade_record.entry_price) / pip_value
    else:
        partial_pips = (trade_record.entry_price - trade_record.partial_close_price) / pip_value

    if partial_profit is None:
        # Estimate partial profit from pips × 60% of lot_size × $10/pip
        dollar_per_pip = 10.0
        original_lots = trade_record.lot_size or 0.01
        partial_pct = config.PARTIAL_CLOSE_PCT
        partial_profit = partial_pips * dollar_per_pip * original_lots * partial_pct

    total_pnl = main_close_profit + partial_profit
    # Weighted pip outcome (partial 60% + remainder 40%)
    partial_pct = config.PARTIAL_CLOSE_PCT
    remainder_pct = 1.0 - partial_pct
    total_pips = partial_pips * partial_pct + main_pips * remainder_pct
    return total_pnl, total_pips
