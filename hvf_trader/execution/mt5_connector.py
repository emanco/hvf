"""
MetaTrader 5 connection, reconnection with exponential backoff, heartbeat.
"""
import time
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# MT5 may not be available in dev/test environments
try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from hvf_trader import config


class MT5Connector:
    def __init__(self):
        self.connected = False
        self.last_heartbeat: Optional[datetime] = None
        self._reconnect_attempts = 0
        self._disconnect_since: Optional[datetime] = None

    def connect(self) -> bool:
        """
        Initialize MT5 connection using credentials from config.

        Returns True on success, False on failure.
        """
        if not MT5_AVAILABLE:
            logger.error("MetaTrader5 package not available")
            return False

        if not mt5.initialize(path=config.MT5_PATH):
            error = mt5.last_error()
            logger.error("MT5 initialize failed: %s", error)
            mt5.shutdown()
            return False

        authorized = mt5.login(
            config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        if not authorized:
            error = mt5.last_error()
            logger.error("MT5 login failed: %s", error)
            mt5.shutdown()
            return False

        account = mt5.account_info()
        if account is None:
            error = mt5.last_error()
            logger.error("MT5 account_info failed: %s", error)
            mt5.shutdown()
            return False

        self.connected = True
        self.last_heartbeat = datetime.now(timezone.utc)
        self._reconnect_attempts = 0
        self._disconnect_since = None
        logger.info(
            "MT5 connected: login=%s server=%s balance=%.2f %s",
            account.login,
            account.server,
            account.balance,
            account.currency,
        )
        return True

    def disconnect(self):
        """Shutdown MT5 connection cleanly."""
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 disconnected")

    def heartbeat(self) -> bool:
        """
        Check if MT5 is still responsive.

        Calls mt5.symbol_info on a liquid symbol. If it returns None with an
        error, the connection is considered lost.

        Returns True if connection is alive.
        """
        if not MT5_AVAILABLE or not self.connected:
            return False

        info = mt5.symbol_info("EURUSD")
        if info is None:
            error = mt5.last_error()
            logger.warning("MT5 heartbeat failed: %s", error)
            self.connected = False
            if self._disconnect_since is None:
                self._disconnect_since = datetime.now(timezone.utc)
            return False

        self.last_heartbeat = datetime.now(timezone.utc)
        return True

    def reconnect(self) -> bool:
        """
        Reconnect with exponential backoff.

        Returns True when reconnected, False after max attempts exhausted.
        """
        if self._disconnect_since is None:
            self._disconnect_since = datetime.now(timezone.utc)

        delay = config.RECONNECT_BASE_DELAY_SEC

        for attempt in range(1, config.RECONNECT_MAX_ATTEMPTS + 1):
            self._reconnect_attempts = attempt
            logger.info(
                "MT5 reconnect attempt %d/%d (delay=%.1fs)",
                attempt,
                config.RECONNECT_MAX_ATTEMPTS,
                delay,
            )

            # Ensure clean state before retry
            try:
                mt5.shutdown()
            except Exception:
                pass

            if self.connect():
                elapsed = (
                    datetime.now(timezone.utc) - self._disconnect_since
                ).total_seconds()
                logger.info(
                    "MT5 reconnected after %d attempts (%.0fs total downtime)",
                    attempt,
                    elapsed,
                )
                return True

            if attempt < config.RECONNECT_MAX_ATTEMPTS:
                time.sleep(delay)
                delay = min(delay * 2, config.RECONNECT_MAX_DELAY_SEC)

        logger.error(
            "MT5 reconnect failed after %d attempts", config.RECONNECT_MAX_ATTEMPTS
        )
        return False

    def was_extended_disconnect(self) -> bool:
        """
        Returns True if the disconnect duration exceeded DISCONNECT_CLOSE_THRESHOLD_SEC.
        Used by trade monitor to decide whether to close all positions.
        """
        if self._disconnect_since is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._disconnect_since).total_seconds()
        return elapsed > config.DISCONNECT_CLOSE_THRESHOLD_SEC

    def get_account_info(self) -> Optional[dict]:
        """
        Get account info as dict with keys:
        balance, equity, free_margin, margin, margin_level, profit.

        Returns None if not connected.
        """
        if not MT5_AVAILABLE or not self.connected:
            return None

        account = mt5.account_info()
        if account is None:
            logger.warning("Failed to retrieve account info: %s", mt5.last_error())
            return None

        return {
            "balance": account.balance,
            "equity": account.equity,
            "free_margin": account.margin_free,
            "margin": account.margin,
            "margin_level": account.margin_level,
            "profit": account.profit,
        }

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Get symbol info as dict with keys:
        bid, ask, spread, point, trade_contract_size, volume_min, volume_max, volume_step.

        Returns None if not connected or symbol not found.
        """
        if not MT5_AVAILABLE or not self.connected:
            return None

        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning(
                "Symbol '%s' not found: %s", symbol, mt5.last_error()
            )
            return None

        return {
            "bid": info.bid,
            "ask": info.ask,
            "spread": info.spread,
            "point": info.point,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
        }
