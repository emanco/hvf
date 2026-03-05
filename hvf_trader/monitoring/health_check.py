"""
MT5 heartbeat, resource checks, connection monitoring.
"""

import logging
import time
import threading
from datetime import datetime, timezone

from hvf_trader import config

logger = logging.getLogger(__name__)


class HealthChecker:
    def __init__(self, connector, trade_logger=None, order_manager=None):
        """
        Args:
            connector: MT5Connector instance
            trade_logger: TradeLogger for event logging
            order_manager: OrderManager for emergency close on extended disconnect
        """
        self.connector = connector
        self.trade_logger = trade_logger
        self.order_manager = order_manager
        self._running = False
        self._thread = None

    def start(self):
        """Start health check loop in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(target=self._health_loop, daemon=True)
        self._thread.start()
        logger.info("Health checker started")

    def stop(self):
        """Stop the health check loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Health checker stopped")

    def _health_loop(self):
        """Main health check loop."""
        while self._running:
            try:
                self._check()
            except Exception as e:
                logger.error(f"Health check error: {e}", exc_info=True)
            time.sleep(config.HEARTBEAT_INTERVAL_SEC)

    def _check(self):
        """Single health check cycle."""
        if not self.connector.connected:
            logger.warning("MT5 not connected, attempting reconnect")
            self._handle_disconnect()
            return

        alive = self.connector.heartbeat()
        if not alive:
            logger.warning("MT5 heartbeat failed")
            self._handle_disconnect()

    def _handle_disconnect(self):
        """Handle MT5 disconnection with reconnection logic."""
        if self.trade_logger:
            self.trade_logger.log_event(
                "RECONNECT",
                details="MT5 connection lost, attempting reconnect",
                severity="WARNING",
            )

        success = self.connector.reconnect()

        if success:
            logger.info("MT5 reconnected successfully")
            if self.trade_logger:
                self.trade_logger.log_event(
                    "RECONNECT",
                    details="MT5 reconnected successfully",
                )

            # Check if it was an extended disconnect
            if self.connector.was_extended_disconnect():
                logger.warning(
                    "Extended disconnect detected (>15min), closing all positions"
                )
                if self.order_manager:
                    closed = self.order_manager.close_all_positions(
                        "Emergency: extended disconnect"
                    )
                    if self.trade_logger:
                        self.trade_logger.log_event(
                            "CIRCUIT_BREAKER",
                            details=f"Extended disconnect: closed {closed} positions",
                            severity="WARNING",
                        )
        else:
            logger.error(
                f"MT5 reconnection failed after "
                f"{config.RECONNECT_MAX_ATTEMPTS} attempts"
            )
            if self.trade_logger:
                self.trade_logger.log_event(
                    "ERROR",
                    details="MT5 reconnection failed, max attempts exhausted",
                    severity="CRITICAL",
                )
