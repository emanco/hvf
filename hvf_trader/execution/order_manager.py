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

    def is_mt5_healthy(self) -> bool:
        """Sanity-check that MT5 IPC is responsive.

        Used as a gate before destructive recon actions — an empty
        positions_get() on a transient IPC failure looks identical to
        "no open positions" and would otherwise trigger wrongful closes.
        """
        if not MT5_AVAILABLE:
            return False
        info = mt5.account_info()
        if info is None:
            err = mt5.last_error()
            logger.warning(
                "[MT5_HEALTH] account_info() returned None, last_error=%s",
                err,
            )
            return False
        return True

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        stop_loss: float,
        take_profit: float = 0.0,
        comment: str = "AUTO",
        magic: int = 20250305,
        limit_price: float = 0.0,
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
            limit_price: optional limit price. If > 0, uses TRADE_ACTION_DEAL
                with this price + zero deviation — MT5 fills at this price or
                better, otherwise rejects (TRADE_RETCODE_REQUOTE). For LONG
                this should be max acceptable ask; for SHORT, min acceptable
                bid. Caps adverse slippage at the limit boundary.

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
        digits = symbol_info.digits

        # Symbol-specific deviation tolerance. Previously hardcoded to 20 points,
        # which is ~2p on 5-digit pairs but only 0.2p on JPY (3-digit). Now we
        # convert a target pip tolerance into points for each symbol so the
        # broker rejects fills > MAX_DEVIATION_PIPS away.
        pip_size = symbol_info.point * (10 if digits in (3, 5) else 1)

        # Limit-style entry: if limit_price provided, use it as the request
        # price with zero deviation. MT5 only fills at limit-or-better; any
        # adverse drift larger than 0 returns TRADE_RETCODE_REQUOTE.
        if limit_price and limit_price > 0:
            price = limit_price
            deviation_points = 0
        else:
            price = tick.ask if direction == "LONG" else tick.bid
            max_dev_pips = config.MAX_DEVIATION_PIPS
            deviation_points = max(1, int(max_dev_pips * pip_size / symbol_info.point))

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
            "deviation": deviation_points,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Snapshot matching open positions BEFORE sending. If the placement
        # then reports a failure, we check whether the order actually executed
        # (response lost / TIMEOUT / ambiguous retcode) and adopt the position
        # rather than orphaning it — what happened to LONDON_BO on 2026-06-29.
        pre_tickets = {
            p.ticket for p in (mt5.positions_get(symbol=symbol) or [])
            if p.magic == magic
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            logger.error(f"Order send failed: {error}")
            return self._recover_orphan_fill(
                symbol, direction, magic, pre_tickets, f"order_send=None {error}")

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            # Limit-style fills surface as REQUOTE/REJECT when price drifted
            # past the cap — that's the intended behavior, not an error, and
            # genuinely means no fill (don't run orphan recovery).
            if limit_price and result.retcode in (
                mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_REJECT,
                mt5.TRADE_RETCODE_PRICE_OFF,
            ):
                logger.info(
                    f"Limit-style entry skipped: price drifted past cap "
                    f"{limit_price} (retcode={result.retcode})"
                )
                return None
            logger.error(
                f"Order failed: retcode={result.retcode}, comment={result.comment}"
            )
            return self._recover_orphan_fill(
                symbol, direction, magic, pre_tickets, f"retcode={result.retcode}")

        logger.info(
            f"Order placed: ticket={result.order}, {direction} {lot_size} {symbol} "
            f"@ {result.price}, SL={stop_loss}"
        )
        return {"ticket": result.order, "fill_price": result.price}

    def _recover_orphan_fill(self, symbol, direction, magic, pre_tickets, context=""):
        """After a reported placement failure, detect whether MT5 actually
        opened a matching position (the order went through but the response was
        lost/timed out) and adopt it so the caller can track it.

        Returns a success-style dict (ticket + fill_price) if a NEW matching
        position appeared, else None. Polls briefly because the position can
        take a moment to register after an ambiguous send.
        """
        if not MT5_AVAILABLE:
            return None
        import time
        want_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        for _ in range(3):
            time.sleep(0.5)
            for p in (mt5.positions_get(symbol=symbol) or []):
                if (p.magic == magic and p.type == want_type
                        and p.ticket not in pre_tickets):
                    logger.warning(
                        "[ORDER] Recovered orphan fill: %s %s ticket=%s @ %.5f — "
                        "placement reported failure (%s) but the order executed; "
                        "adopting so it gets tracked.",
                        direction, symbol, p.ticket, p.price_open, context,
                    )
                    return {"ticket": p.ticket, "fill_price": p.price_open,
                            "recovered": True}
        return None

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

        # Skip if new SL violates broker minimum stop distance
        if symbol_info:
            stops_level = getattr(symbol_info, "trade_stops_level", 0) or 0
            freeze_level = getattr(symbol_info, "trade_freeze_level", 0) or 0
            min_distance = max(stops_level, freeze_level) * symbol_info.point
            if min_distance > 0:
                current_price = pos.price_current
                if pos.type == 0:  # BUY/LONG
                    distance = current_price - new_sl
                else:  # SELL/SHORT
                    distance = new_sl - current_price
                if distance < min_distance:
                    logger.debug(
                        f"SL too close to price: {symbol} ticket={ticket} "
                        f"distance={distance:.5f} min={min_distance:.5f}, skipping"
                    )
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
            # Cheap per-position symbol_info lookup so reconciliation can use
            # broker-actual tick size for SL-mismatch tolerance instead of a
            # PIP_VALUES guess that's wrong for crypto/indices/metals.
            sinfo = mt5.symbol_info(pos.symbol)
            point = sinfo.point if sinfo else 0.0
            digits = sinfo.digits if sinfo else 5
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
                "point": point,
                "digits": digits,
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

    def place_pending_limit_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        limit_price: float,
        stop_loss: float,
        take_profit: float = 0.0,
        comment: str = "AUTO",
        magic: int = 20250305,
    ) -> Optional[dict]:
        """
        Place a pending LIMIT order. Broker fills only when bid (SHORT) /
        ask (LONG) reaches limit_price, at limit-or-better. Used by
        Quantum London to guarantee entry geometry (TP/SL anchored to a
        known fill price, not a hoped-for one).

        Returns:
            Dict with 'order_ticket' on success, None on failure.
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

        order_type = (
            mt5.ORDER_TYPE_BUY_LIMIT if direction == "LONG"
            else mt5.ORDER_TYPE_SELL_LIMIT
        )
        digits = symbol_info.digits
        limit_price = round(limit_price, digits)
        stop_loss = round(stop_loss, digits)
        take_profit = round(take_profit, digits) if take_profit > 0 else 0.0

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": limit_price,
            "sl": stop_loss,
            "tp": take_profit,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            logger.error(f"Pending order send failed: {error}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Pending order failed: retcode={result.retcode}, "
                f"comment={result.comment}"
            )
            return None

        logger.info(
            f"Pending limit placed: ticket={result.order}, "
            f"{direction}_LIMIT {lot_size} {symbol} @ {limit_price}, "
            f"SL={stop_loss}, TP={take_profit}"
        )
        return {"order_ticket": result.order, "limit_price": limit_price}

    def place_pending_stop_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        stop_price: float,
        stop_loss: float,
        take_profit: float = 0.0,
        comment: str = "AUTO",
        magic: int = 20250305,
        expiration_utc: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Place a pending STOP order for breakout entries.

        BUY_STOP triggers when the ASK reaches stop_price (placed ABOVE
        current price). SELL_STOP triggers when the BID reaches stop_price
        (placed BELOW current price).

        expiration_utc: if given, the order is placed ORDER_TIME_SPECIFIED
        so it self-destructs broker-side at that UTC time even if the bot
        dies — closes the orphaned-GTC-pending hole (2026-07-02 audit).
        Falls back to GTC when the symbol doesn't support SPECIFIED or the
        broker rejects the expiration.

        Returns dict with 'order_ticket' on success, None on failure.
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

        order_type = (
            mt5.ORDER_TYPE_BUY_STOP if direction == "LONG"
            else mt5.ORDER_TYPE_SELL_STOP
        )
        digits = symbol_info.digits
        stop_price = round(stop_price, digits)
        stop_loss = round(stop_loss, digits)
        take_profit = round(take_profit, digits) if take_profit > 0 else 0.0

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": stop_price,
            "sl": stop_loss,
            "tp": take_profit,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        # Broker-side expiry. MT5 expiration is in SERVER (broker) time —
        # derive the broker-vs-UTC offset from a live tick rather than
        # assuming a fixed timezone (IC is UTC+2/+3 by DST).
        if expiration_utc is not None:
            supports_specified = bool(
                getattr(symbol_info, "expiration_mode", 0)
                & mt5.SYMBOL_EXPIRATION_SPECIFIED
            )
            tick = mt5.symbol_info_tick(symbol)
            if supports_specified and tick and tick.time:
                import time as _time
                broker_offset = tick.time - _time.time()
                request["type_time"] = mt5.ORDER_TIME_SPECIFIED
                request["expiration"] = int(
                    expiration_utc.timestamp() + broker_offset
                )
            else:
                logger.warning(
                    f"{symbol}: SPECIFIED expiration unsupported/no tick — "
                    f"placing GTC instead"
                )

        result = mt5.order_send(request)
        # Some servers reject SPECIFIED expirations (retcode 10022) — retry
        # once as GTC rather than losing the day's setup.
        if (result is not None
                and result.retcode == mt5.TRADE_RETCODE_INVALID_EXPIRATION
                and request.get("type_time") == mt5.ORDER_TIME_SPECIFIED):
            logger.warning(
                f"{symbol}: broker rejected expiration "
                f"(retcode {result.retcode}); retrying GTC"
            )
            request["type_time"] = mt5.ORDER_TIME_GTC
            request.pop("expiration", None)
            result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            logger.error(f"Pending stop send failed: {err}")
            return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            # 10015 = TRADE_RETCODE_INVALID_PRICE — for breakout STOP orders
            # this almost always means price has already moved through the
            # level we're trying to set, so the order can't be a "stop". Not
            # an error condition; the strategy just missed this entry. Log at
            # INFO so it doesn't flood errors.log.
            if result.retcode == 10015:
                logger.info(
                    f"Pending stop skipped: {direction}_STOP {symbol} @ {stop_price} — "
                    f"price already through level (retcode 10015 invalid price)"
                )
            else:
                logger.error(
                    f"Pending stop failed: retcode={result.retcode}, "
                    f"comment={result.comment}"
                )
            return None

        logger.info(
            f"Pending stop placed: ticket={result.order}, "
            f"{direction}_STOP {lot_size} {symbol} @ {stop_price}, "
            f"SL={stop_loss}, TP={take_profit}"
        )
        return {"order_ticket": result.order, "stop_price": stop_price}

    def cancel_pending_order(self, ticket: int) -> bool:
        """Cancel a still-pending limit/stop order by ticket."""
        if not MT5_AVAILABLE:
            return False
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            rc = result.retcode if result is not None else "None"
            logger.error(f"Cancel pending order {ticket} failed: retcode={rc}")
            return False
        logger.info(f"Pending order {ticket} cancelled")
        return True

    def get_pending_order(self, ticket: int) -> Optional[dict]:
        """Return pending order details, or None if not found (filled/cancelled)."""
        if not MT5_AVAILABLE:
            return None
        orders = mt5.orders_get(ticket=ticket)
        if not orders:
            return None
        o = orders[0]
        return {
            "ticket": o.ticket, "symbol": o.symbol, "type": o.type,
            "volume": o.volume_current, "price_open": o.price_open,
            "sl": o.sl, "tp": o.tp, "magic": o.magic, "comment": o.comment,
        }
