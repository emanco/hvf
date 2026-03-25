"""
Internal state vs MT5 positions reconciliation.
Runs every 60s to detect discrepancies.
"""

import logging
from datetime import datetime, timezone

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
                discrepancy = {
                    "type": "MISSING_IN_MT5",
                    "details": (
                        f"Trade {trade.id} (ticket {ticket}) is OPEN in DB "
                        f"but not found in MT5"
                    ),
                    "trade_id": trade.id,
                    "ticket": ticket,
                }
                discrepancies.append(discrepancy)
                logger.warning(discrepancy["details"])

                # Mark as closed (server-side close)
                self.trade_logger.log_trade_update(
                    trade.id, status="CLOSED", close_reason="RECONCILIATION"
                )
                self.trade_logger.log_event(
                    "RECONCILIATION",
                    symbol=trade.symbol,
                    trade_id=trade.id,
                    details=discrepancy["details"],
                    severity="WARNING",
                )

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
