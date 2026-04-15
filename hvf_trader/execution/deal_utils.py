"""
Shared deal-matching and PnL estimation utilities.

Used by both TradeMonitor and Reconciliator to avoid logic duplication.
"""

import logging
from datetime import datetime, timedelta, timezone

from hvf_trader import config

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


def search_deal_history(ticket: int, symbol: str, lookback_days: int = 7):
    """Search MT5 deal history for a position, with IC Markets broad fallback.

    Args:
        ticket: MT5 position ticket.
        symbol: Instrument symbol.
        lookback_days: How far back to search.

    Returns:
        List of deal objects, or empty list.
    """
    if not MT5_AVAILABLE:
        return []

    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=lookback_days)

    # Try position-filtered lookup first
    deals = mt5.history_deals_get(from_date, now, position=ticket)

    # IC Markets often returns nothing for position=ticket filter.
    # Fall back to broad search filtered by symbol.
    if not deals:
        logger.info(
            f"[DEAL_SEARCH] No deals for position={ticket}, "
            f"trying broad search for {symbol}"
        )
        all_deals = mt5.history_deals_get(from_date, now)
        if all_deals:
            deals = [d for d in all_deals if d.symbol == symbol]

    return deals or []


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
    pip_value = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
    direction = trade_record.direction
    original_lots = trade_record.lot_size or 0.01
    dollar_per_pip = 10.0  # approximate $10/pip/standard lot

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
