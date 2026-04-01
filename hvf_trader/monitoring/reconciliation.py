"""
Internal state vs MT5 positions reconciliation.
Runs every 60s to detect discrepancies.
"""

import logging
from datetime import datetime, timedelta, timezone

from hvf_trader import config
from hvf_trader.database.models import TradeRecord

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


class Reconciliator:
    def __init__(self, trade_logger, order_manager=None):
        """
        Args:
            trade_logger: TradeLogger for DB queries and event logging
            order_manager: OrderManager for position queries
        """
        self.trade_logger = trade_logger
        self.order_manager = order_manager
        self._missing_counts = {}  # ticket -> consecutive miss count

    def reconcile(self) -> list[dict]:
        """
        Compare internal trade records with MT5 live positions.

        Checks:
        1. Internal 'OPEN'/'PARTIAL' trades that no longer exist in MT5
           → Mark as CLOSED (server-side SL/TP hit)
        2. MT5 positions that don't match any internal trade
           → Log as WARNING (manual trade or sync issue)
        3. SL mismatches between internal trailing_sl and MT5 actual SL
           → Log as WARNING

        Returns:
            List of discrepancy dicts with keys: type, details, trade_id, ticket
        """
        discrepancies = []

        # Get internal open trades
        internal_trades = self.trade_logger.get_open_trades()
        internal_tickets = {
            t.mt5_ticket: t for t in internal_trades if t.mt5_ticket is not None
        }

        # Get MT5 live positions
        mt5_positions = {}
        if self.order_manager:
            for pos in self.order_manager.get_open_positions():
                mt5_positions[pos["ticket"]] = pos

        # Check 1: Internal trades missing from MT5
        for ticket, trade in internal_tickets.items():
            if ticket not in mt5_positions:
                # Require 3 consecutive misses before closing — gives trade monitor
                # (which has better deal lookup and runs every 30s) priority.
                count = self._missing_counts.get(ticket, 0) + 1
                self._missing_counts[ticket] = count
                if count < 3:
                    logger.info(
                        f"[RECONCILIATION] Trade {trade.id} (ticket {ticket}, "
                        f"{trade.symbol}) missing from MT5 (attempt {count}/3)"
                    )
                    continue

                self._missing_counts.pop(ticket, None)
                discrepancy = {
                    "type": "MISSING_IN_MT5",
                    "details": (
                        f"Trade {trade.id} (ticket {ticket}) is OPEN in DB "
                        f"but not found in MT5 after 3 checks"
                    ),
                    "trade_id": trade.id,
                    "ticket": ticket,
                }
                discrepancies.append(discrepancy)
                logger.warning(discrepancy["details"])

                # Look up deal history for proper close price and PnL
                self._close_with_deal_history(trade, ticket)

        # Reset miss counters for positions that ARE found in MT5
        for ticket in internal_tickets:
            if ticket in mt5_positions:
                self._missing_counts.pop(ticket, None)

        # Clean up stale miss counters for tickets no longer in our DB
        stale_tickets = [t for t in self._missing_counts if t not in internal_tickets]
        for t in stale_tickets:
            self._missing_counts.pop(t, None)

        # Check 2: MT5 positions not in internal records — try to re-adopt
        for ticket, pos in mt5_positions.items():
            if ticket not in internal_tickets:
                # Only handle positions with our magic number
                if pos.get("magic") != 20250305:
                    continue

                # Check if there's a falsely-closed trade with this ticket
                closed_trade = (
                    self.trade_logger._session.query(TradeRecord)
                    .filter(
                        TradeRecord.mt5_ticket == ticket,
                        TradeRecord.status == "CLOSED",
                    )
                    .first()
                )

                if closed_trade:
                    # Re-adopt: reopen the falsely closed trade
                    prev_status = "PARTIAL" if closed_trade.partial_closed else "OPEN"
                    self.trade_logger.log_trade_update(
                        closed_trade.id,
                        status=prev_status,
                        close_price=None,
                        pnl=None,
                        pnl_pips=None,
                        close_reason=None,
                        closed_at=None,
                    )
                    self.trade_logger._session.commit()
                    discrepancy = {
                        "type": "REOPENED",
                        "details": (
                            f"Trade {closed_trade.id} (ticket {ticket}, "
                            f"{pos['symbol']}) was falsely closed — "
                            f"reopened as {prev_status}"
                        ),
                        "trade_id": closed_trade.id,
                        "ticket": ticket,
                    }
                    discrepancies.append(discrepancy)
                    logger.warning(f"[RECONCILIATION_REOPEN] {discrepancy['details']}")
                    self.trade_logger.log_event(
                        "RECONCILIATION_REOPEN",
                        symbol=pos["symbol"],
                        trade_id=closed_trade.id,
                        details=discrepancy["details"],
                        severity="WARNING",
                    )
                else:
                    discrepancy = {
                        "type": "MISSING_IN_DB",
                        "details": (
                            f"MT5 position {ticket} ({pos['symbol']}) "
                            f"not found in internal records"
                        ),
                        "trade_id": None,
                        "ticket": ticket,
                    }
                    discrepancies.append(discrepancy)
                    logger.warning(discrepancy["details"])
                    self.trade_logger.log_event(
                        "RECONCILIATION",
                        symbol=pos["symbol"],
                        details=discrepancy["details"],
                        severity="WARNING",
                    )

        # Check 3: SL mismatches
        for ticket in set(internal_tickets) & set(mt5_positions):
            trade = internal_tickets[ticket]
            pos = mt5_positions[ticket]
            expected_sl = trade.trailing_sl or trade.stop_loss
            actual_sl = pos.get("sl", 0)

            if expected_sl and actual_sl:
                pip_value = config.PIP_VALUES.get(trade.symbol, 0.0001)
                diff_pips = abs(expected_sl - actual_sl) / pip_value

                if diff_pips > 1:  # More than 1 pip difference
                    discrepancy = {
                        "type": "SL_MISMATCH",
                        "details": (
                            f"Trade {trade.id} SL mismatch: "
                            f"expected={expected_sl:.5f}, actual={actual_sl:.5f} "
                            f"(diff={diff_pips:.1f} pips)"
                        ),
                        "trade_id": trade.id,
                        "ticket": ticket,
                    }
                    discrepancies.append(discrepancy)
                    logger.warning(discrepancy["details"])

        if discrepancies:
            self.trade_logger.log_event(
                "RECONCILIATION",
                details=f"Found {len(discrepancies)} discrepancies",
                severity="WARNING" if discrepancies else "INFO",
            )
        else:
            logger.debug("Reconciliation: no discrepancies")

        return discrepancies

    def _close_with_deal_history(self, trade, ticket):
        """Close a missing trade using MT5 deal history for accurate PnL."""
        if not MT5_AVAILABLE:
            self._close_fallback(trade, ticket)
            return

        # Search deal history (7 days)
        now = datetime.now(timezone.utc)
        from_date = now - timedelta(days=7)

        # Try position-filtered lookup first
        deals = mt5.history_deals_get(from_date, now, position=ticket)

        # IC Markets often returns nothing for position=ticket filter.
        # Fall back to broad search filtered by symbol.
        if not deals:
            logger.info(
                f"[RECONCILIATION] No deals for position={ticket}, "
                f"trying broad search for {trade.symbol}"
            )
            all_deals = mt5.history_deals_get(from_date, now)
            if all_deals:
                deals = [d for d in all_deals if d.symbol == trade.symbol]

        if not deals:
            self._close_fallback(trade, ticket)
            return

        # Find the closing deal — same logic as trade_monitor._handle_server_close
        close_deal = None
        expected_deal_type = 1 if trade.direction == "LONG" else 0
        trade_open_time = trade.opened_at
        if trade_open_time and trade_open_time.tzinfo is None:
            trade_open_time = trade_open_time.replace(tzinfo=timezone.utc)
        ticket = trade.mt5_ticket

        # Two-pass matching (mirrors trade_monitor logic):
        # Pass 1: exact position ticket match
        for deal in deals:
            if deal.position_id != ticket or deal.symbol != trade.symbol:
                continue
            if deal.type != expected_deal_type:
                continue
            if trade_open_time:
                deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
                if deal_time < (trade_open_time - timedelta(seconds=60)):
                    continue
            close_deal = deal

        # Pass 2: broader entry-based matching
        if not close_deal:
            for deal in deals:
                if deal.symbol != trade.symbol:
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

        if close_deal:
            close_price = close_deal.price
            pnl = close_deal.profit
            pip_value = config.PIP_VALUES.get(trade.symbol, 0.0001)
            if trade.direction == "LONG":
                pnl_pips = (close_price - trade.entry_price) / pip_value
            else:
                pnl_pips = (trade.entry_price - close_price) / pip_value

            reason = "STOP_LOSS" if pnl < 0 else "TAKE_PROFIT"
            self.trade_logger.log_trade_close(
                trade.id, close_price, pnl, pnl_pips, reason
            )
            self.trade_logger.log_event(
                "RECONCILIATION",
                symbol=trade.symbol,
                trade_id=trade.id,
                details=(
                    f"Server-side close detected by reconciliation: {reason}, "
                    f"PnL={pnl:.2f}, Pips={pnl_pips:.1f}"
                ),
                severity="WARNING",
            )
            logger.info(
                f"[RECONCILIATION] {trade.symbol} trade {trade.id} closed "
                f"via deal history: {reason}, {pnl_pips:+.1f} pips"
            )
        else:
            self._close_fallback(trade, ticket)

    def _close_fallback(self, trade, ticket):
        """Fallback close when no deal history is available.

        Priority: trailing_sl > stop_loss > entry_price.
        A position that disappeared without deal history most likely hit its SL.
        """
        if trade.trailing_sl:
            close_price = trade.trailing_sl
            source = "trailing SL"
        elif trade.stop_loss:
            close_price = trade.stop_loss
            source = "stop loss"
        else:
            close_price = trade.entry_price
            source = "entry (no SL available)"

        pip_value = config.PIP_VALUES.get(trade.symbol, 0.0001)
        if trade.direction == "LONG":
            pnl_pips = (close_price - trade.entry_price) / pip_value
        else:
            pnl_pips = (trade.entry_price - close_price) / pip_value

        # Estimate dollar PnL: $10 per pip per standard lot (1.0)
        lot_size = trade.lot_size or 0.01
        pnl_dollar = pnl_pips * 10.0 * lot_size

        reason = "RECONCILIATION"
        self.trade_logger.log_trade_close(
            trade.id, close_price, pnl_dollar, pnl_pips, reason
        )
        self.trade_logger.log_event(
            "RECONCILIATION",
            symbol=trade.symbol,
            trade_id=trade.id,
            details=(
                f"No deal history found. Estimated close at {source} "
                f"{close_price:.5f}, ~{pnl_pips:+.1f} pips, ~${pnl_dollar:+.2f}"
            ),
            severity="WARNING",
        )
        logger.warning(
            f"[RECONCILIATION] {trade.symbol} trade {trade.id} closed "
            f"without deal history, estimated at {source}: {pnl_pips:+.1f} pips"
        )
