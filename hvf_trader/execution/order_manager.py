"""
Market orders with SL, modify SL, partial close, full close.
All MT5 order operations.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from hvf_trader import config


class OrderManager:
    def __init__(self, connector=None):
        """
        Args:
            connector: MT5Connector instance for connection state checks
        """
        self.connector = connector

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        stop_loss: float,
        take_profit: float = 0.0,
        comment: str = "AUTO",
        magic: int = 20250305,
    ) -> Optional[dict]:
        """
        Place a market order with stop loss.

        Args:
            symbol: e.g. "EURUSD"
            direction: 'LONG' or 'SHORT'
            lot_size: position size
            stop_loss: SL price
            take_profit: TP price (0 = no TP, managed by trade monitor)
            comment: order comment
            magic: magic number for identification

        Returns:
            Dict with 'ticket' and 'fill_price' on success, None on failure.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 not available")
            return None

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.error(f"Symbol {symbol} not found")
            return None

        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                logger.error(f"Failed to select symbol {symbol}")
                return None

        order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if direction == "LONG" else tick.bid
        digits = symbol_info.digits

        # Round prices to symbol precision — unrounded SLs can cause "Invalid stops"
        price = round(price, digits)
        stop_loss = round(stop_loss, digits)
        take_profit = round(take_profit, digits) if take_profit > 0 else 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            logger.error(f"Order send failed: {error}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Order failed: retcode={result.retcode}, comment={result.comment}"
            )
            return None

        logger.info(
            f"Order placed: ticket={result.order}, {direction} {lot_size} {symbol} "
            f"@ {result.price}, SL={stop_loss}"
        )
        return {"ticket": result.order, "fill_price": result.price}

    def modify_stop_loss(self, ticket: int, symbol: str, new_sl: float) -> bool:
        """
        Modify the stop loss of an open position.

        Args:
            ticket: MT5 position ticket
            symbol: instrument symbol
            new_sl: new stop loss price

        Returns:
            True on success, False on failure.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 not available")
            return False

        position = mt5.positions_get(ticket=ticket)
        if not position:
            logger.error(f"Position {ticket} not found")
            return False

        pos = position[0]
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info:
            new_sl = round(new_sl, symbol_info.digits)

        # Skip if SL is already at the requested level
        if abs(new_sl - pos.sl) < (10 ** -symbol_info.digits if symbol_info else 1e-5):
            return True

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": new_sl,
            "tp": pos.tp,
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            logger.error(f"Modify SL failed: {error}")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Modify SL failed: {symbol} ticket={ticket} new_sl={new_sl:.5f} "
                f"retcode={result.retcode}, comment={result.comment}"
            )
            return False

        logger.info(f"SL modified: ticket={ticket}, new_sl={new_sl}")
        return True

    def partial_close(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        close_pct: float = 0.5,
        comment: str = "partial",
    ) -> Optional[int]:
        """
        Partially close a position by percentage.

        Args:
            ticket: MT5 position ticket
            symbol: instrument symbol
            direction: 'LONG' or 'SHORT'
            close_pct: fraction to close (0.5 = 50%)
            comment: order comment

        Returns:
            New ticket for the closing trade on success, None on failure.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 not available")
            return None

        position = mt5.positions_get(ticket=ticket)
        if not position:
            logger.error(f"Position {ticket} not found for partial close")
            return None

        pos = position[0]
        close_volume = round(pos.volume * close_pct, 2)

        # Ensure minimum lot
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info and close_volume < symbol_info.volume_min:
            logger.warning(
                f"Partial close volume {close_volume} below minimum "
                f"{symbol_info.volume_min}, closing full position"
            )
            close_volume = pos.volume

        close_type = (
            mt5.ORDER_TYPE_SELL if direction == "LONG" else mt5.ORDER_TYPE_BUY
        )
        price = (
            mt5.symbol_info_tick(symbol).bid
            if direction == "LONG"
            else mt5.symbol_info_tick(symbol).ask
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": close_volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 20250305,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            logger.error(f"Partial close failed: {error}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Partial close failed: retcode={result.retcode}, "
                f"comment={result.comment}"
            )
            return None

        logger.info(
            f"Partial close: ticket={ticket}, closed {close_volume} lots "
            f"({close_pct*100}%) @ {result.price}"
        )
        return {"ticket": result.order, "fill_price": result.price, "volume": close_volume}

    def close_position(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        comment: str = "close",
    ) -> bool:
        """
        Fully close an open position.

        Args:
            ticket: MT5 position ticket
            symbol: instrument symbol
            direction: 'LONG' or 'SHORT'
            comment: order comment

        Returns:
            True on success, False on failure.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 not available")
            return False

        position = mt5.positions_get(ticket=ticket)
        if not position:
            logger.error(f"Position {ticket} not found for close")
            return False

        pos = position[0]
        close_type = (
            mt5.ORDER_TYPE_SELL if direction == "LONG" else mt5.ORDER_TYPE_BUY
        )
        price = (
            mt5.symbol_info_tick(symbol).bid
            if direction == "LONG"
            else mt5.symbol_info_tick(symbol).ask
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 20250305,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            logger.error(f"Close position failed: {error}")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Close position failed: retcode={result.retcode}, "
                f"comment={result.comment}"
            )
            return False

        logger.info(
            f"Position closed: ticket={ticket}, {pos.volume} lots @ {result.price}"
        )
        return {"success": True, "fill_price": result.price, "volume": pos.volume}

    def close_all_positions(self, comment: str = "emergency close") -> int:
        """
        Close all open positions (emergency use — extended disconnect).

        Returns:
            Number of positions successfully closed.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 not available")
            return 0

        positions = mt5.positions_get()
        if not positions:
            return 0

        closed = 0
        for pos in positions:
            direction = "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT"
            if self.close_position(pos.ticket, pos.symbol, direction, comment):  # truthy dict
                closed += 1

        logger.info(f"Emergency close: {closed}/{len(positions)} positions closed")
        return closed

    def get_open_positions(self) -> list[dict]:
        """
        Get all open positions as list of dicts.

        Returns:
            List of position dicts with keys:
            ticket, symbol, type, volume, price_open, sl, tp, profit, time, magic, comment
        """
        if not MT5_AVAILABLE:
            return []

        positions = mt5.positions_get()
        if not positions:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "time": datetime.fromtimestamp(pos.time, tz=timezone.utc),
                "magic": pos.magic,
                "comment": pos.comment,
            })

        return result

    def get_position_by_ticket(self, ticket: int) -> Optional[dict]:
        """Get a specific position by ticket number."""
        if not MT5_AVAILABLE:
            return None

        position = mt5.positions_get(ticket=ticket)
        if not position:
            return None

        pos = position[0]
        return {
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "type": "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT",
            "volume": pos.volume,
            "price_open": pos.price_open,
            "sl": pos.sl,
            "tp": pos.tp,
            "profit": pos.profit,
            "time": datetime.fromtimestamp(pos.time, tz=timezone.utc),
            "magic": pos.magic,
            "comment": pos.comment,
            "price_current": pos.price_current,
        }

    def get_all_positions(self) -> list[dict]:
        """Get all open MT5 positions."""
        if not MT5_AVAILABLE:
            return []
        positions = mt5.positions_get()
        if not positions:
            return []
        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "profit": pos.profit,
                "price_current": pos.price_current,
            })
        return result
