"""
30-second loop: partials, trailing stops, invalidation, target monitoring.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from hvf_trader import config


class TradeMonitor:
    def __init__(self, order_manager, trade_logger, connector=None, alerter=None):
        """
        Args:
            order_manager: OrderManager instance
            trade_logger: TradeLogger instance
            connector: MT5Connector instance
            alerter: TelegramAlerter instance (optional)
        """
        self.order_manager = order_manager
        self.alerter = alerter
        self.trade_logger = trade_logger
        self.connector = connector
        self._running = False
        self._highest_since_partial = {}  # ticket -> highest price since partial close
        self._lowest_since_partial = {}   # ticket -> lowest price since partial (for shorts)
        self._missing_position_counts = {}  # ticket -> consecutive miss count
        self._atr_cache = {}  # symbol -> (timestamp, atr_value)

    def start(self):
        """Start the trade monitoring loop."""
        self._running = True
        logger.info("Trade monitor started")
        while self._running:
            try:
                self._monitor_cycle()
            except Exception as e:
                logger.error(f"Trade monitor error: {e}", exc_info=True)
                try:
                    self.trade_logger._session.rollback()
                except Exception:
                    pass
                self.trade_logger.log_event(
                    "ERROR", details=f"Trade monitor: {e}", severity="ERROR"
                )
            time.sleep(config.TRADE_MONITOR_INTERVAL_SEC)

    def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        logger.info("Trade monitor stopped")

    def _monitor_cycle(self):
        """Single monitoring cycle: check all open trades."""
        try:
            self.trade_logger._session.rollback()  # Clear any stale state
        except Exception:
            pass
        open_trades = self.trade_logger.get_open_trades()
        if not open_trades:
            return

        for trade_record in open_trades:
            try:
                self._check_trade(trade_record)
            except Exception as e:
                logger.error(
                    f"Error monitoring trade {trade_record.id}: {e}",
                    exc_info=True,
                )

    def _check_trade(self, trade_record):
        """
        Check a single open trade for:
        1. Invalidation (price revisits below 3L for longs / above 3H for shorts)
        2. Target 1 hit (partial close + move SL to breakeven)
        3. Trailing stop update (after partial)
        4. Target 2 hit (full close)
        """
        ticket = trade_record.mt5_ticket
        if ticket is None:
            return

        position = self.order_manager.get_position_by_ticket(ticket)
        if position is None:
            # Retry once after brief pause (MT5 query can be transiently empty)
            time.sleep(1)
            position = self.order_manager.get_position_by_ticket(ticket)
        if position is None:
            # Try full symbol scan as fallback
            position = self._find_position_for_trade(trade_record)
        if position is None:
            # Require 2 consecutive misses before declaring closed
            count = self._missing_position_counts.get(ticket, 0) + 1
            self._missing_position_counts[ticket] = count
            if count < 2:
                logger.warning(
                    f"Position {ticket} ({trade_record.symbol}) not found "
                    f"(attempt {count}/2), will recheck next cycle"
                )
                return
            self._missing_position_counts.pop(ticket, None)
            self._handle_server_close(trade_record)
            return
        # Position found — reset miss counter
        self._missing_position_counts.pop(ticket, None)

        current_price = position["price_current"]
        direction = trade_record.direction

        # Get associated pattern for invalidation check
        pattern = None
        if trade_record.pattern_id:
            from hvf_trader.database.models import PatternRecord
            pattern = self.trade_logger.session.get(PatternRecord, trade_record.pattern_id)

        # ─── Check invalidation ──────────────────────────────────────────
        # Grace period: skip invalidation check for first 2 H1 bars (2 hours)
        # to avoid premature exits from normal entry-zone noise.
        if pattern and not trade_record.partial_closed:
            hours_since_open = 0
            if trade_record.opened_at:
                opened = trade_record.opened_at
                if opened.tzinfo is None:
                    opened = opened.replace(tzinfo=timezone.utc)
                hours_since_open = (
                    datetime.now(timezone.utc) - opened
                ).total_seconds() / 3600

            if hours_since_open >= 2:
                invalidated = False
                if direction == "LONG" and current_price <= pattern.l3_price:
                    invalidated = True
                elif direction == "SHORT" and current_price >= pattern.h3_price:
                    invalidated = True

                if invalidated:
                    logger.warning(
                        f"Trade {ticket} invalidated: price revisited "
                        f"{'3L' if direction == 'LONG' else '3H'}"
                    )
                    self._close_trade(
                        trade_record, ticket, position, "INVALIDATION"
                    )
                    return

        # ─── Check target 2 (full close) ─────────────────────────────────
        target_2_hit = False
        if direction == "LONG" and current_price >= trade_record.target_2:
            target_2_hit = True
        elif direction == "SHORT" and current_price <= trade_record.target_2:
            target_2_hit = True

        if target_2_hit:
            logger.info(f"Trade {ticket} hit target 2 @ {current_price}")
            self._close_trade(trade_record, ticket, position, "TARGET_2")
            return

        # ─── Check target 1 (partial close) ──────────────────────────────
        if not trade_record.partial_closed and trade_record.target_1:
            target_1_hit = False
            if direction == "LONG" and current_price >= trade_record.target_1:
                target_1_hit = True
            elif direction == "SHORT" and current_price <= trade_record.target_1:
                target_1_hit = True

            if target_1_hit:
                logger.info(f"Trade {ticket} hit target 1 @ {current_price}")
                self._handle_partial_close(trade_record, ticket, position)
                return

        # ─── Trailing stop (after partial close) ─────────────────────────
        if trade_record.partial_closed:
            self._update_trailing_stop(trade_record, ticket, position, current_price)

    def _handle_partial_close(self, trade_record, ticket, position):
        """Close 50% of position and move SL to breakeven."""
        direction = trade_record.direction

        # Partial close
        ptype = trade_record.pattern_type or "AUTO"
        partial_result = self.order_manager.partial_close(
            ticket, trade_record.symbol, direction, config.PARTIAL_CLOSE_PCT,
            comment=f"{ptype} partial",
        )

        if partial_result is not None:
            # Use actual fill price from partial close, not pre-close snapshot
            close_price = partial_result["fill_price"] if isinstance(partial_result, dict) else position["price_current"]
            new_ticket = partial_result["ticket"] if isinstance(partial_result, dict) else partial_result

            # Update trade record
            self.trade_logger.log_partial_close(trade_record.id, close_price)

            # MT5 may assign a new ticket to the remaining position after
            # partial close. Detect and update DB so we can track it.
            remaining_pos = self.order_manager.get_position_by_ticket(ticket)
            if remaining_pos is None:
                # Old ticket gone — find the new position for this symbol+direction
                new_positions = self._find_position_for_trade(trade_record)
                if new_positions:
                    new_mt5_ticket = new_positions["ticket"]
                    logger.info(
                        f"Ticket changed after partial close: "
                        f"{ticket} -> {new_mt5_ticket}"
                    )
                    self.trade_logger.log_trade_update(
                        trade_record.id, mt5_ticket=new_mt5_ticket
                    )
                    ticket = new_mt5_ticket

            # Move SL to breakeven (entry price)
            breakeven_sl = trade_record.entry_price
            self.order_manager.modify_stop_loss(
                ticket, trade_record.symbol, breakeven_sl
            )
            self.trade_logger.log_trade_update(
                trade_record.id, trailing_sl=breakeven_sl
            )

            # Initialize tracking for trailing stop
            if direction == "LONG":
                self._highest_since_partial[ticket] = close_price
            else:
                self._lowest_since_partial[ticket] = close_price

            self.trade_logger.log_event(
                "PARTIAL_CLOSE",
                symbol=trade_record.symbol,
                trade_id=trade_record.id,
                details=f"Closed {config.PARTIAL_CLOSE_PCT*100}% @ {close_price}, "
                        f"SL moved to breakeven {breakeven_sl}",
            )
            logger.info(
                f"Partial close complete: ticket={ticket}, "
                f"SL→breakeven={breakeven_sl}"
            )
            if self.alerter:
                # Approximate pips (works for 4/5 digit pairs)
                pip_size = 0.01 if "JPY" in trade_record.symbol else 0.0001
                pnl_pips = (close_price - trade_record.entry_price) / pip_size
                if direction == "SHORT":
                    pnl_pips = -pnl_pips
                self.alerter.alert_partial_close(
                    trade_record.symbol, direction, close_price, pnl_pips,
                )

    def _update_trailing_stop(self, trade_record, ticket, position, current_price):
        """
        Trail SL at 1.5x ATR below highest price since partial (LONG)
        or above lowest price since partial (SHORT).
        Trailing SL only moves in trade's favour — never backwards.
        """
        direction = trade_record.direction

        # Get current ATR — cached per symbol, refreshed every 120s (2 monitor cycles)
        now = time.time()
        cached = self._atr_cache.get(trade_record.symbol)
        if cached and (now - cached[0]) < 120:
            current_atr = cached[1]
        else:
            from hvf_trader.data.data_fetcher import fetch_and_prepare
            df = fetch_and_prepare(trade_record.symbol, config.PRIMARY_TIMEFRAME, bars=20)
            if df is None or df.empty:
                return
            current_atr = df["atr"].iloc[-1]
            self._atr_cache[trade_record.symbol] = (now, current_atr)
        trail_mult = config.TRAILING_STOP_ATR_MULT_BY_PATTERN.get(
            trade_record.pattern_type, config.TRAILING_STOP_ATR_MULT
        )
        trail_distance = trail_mult * current_atr

        if direction == "LONG":
            # Track highest price
            prev_highest = self._highest_since_partial.get(ticket, current_price)
            highest = max(prev_highest, current_price)
            self._highest_since_partial[ticket] = highest

            new_sl = highest - trail_distance
            current_sl = trade_record.trailing_sl or trade_record.entry_price

            logger.debug(
                f"[TRAIL_DEBUG] {trade_record.symbol} dir=LONG "
                f"price={current_price:.5f} highest={highest:.5f} "
                f"trail_dist={trail_distance:.5f} new_sl={new_sl:.5f} "
                f"current_sl={current_sl:.5f} would_modify={new_sl > current_sl}"
            )

            # Only move SL up, never down
            if new_sl > current_sl:
                if self.order_manager.modify_stop_loss(
                    ticket, trade_record.symbol, new_sl
                ):
                    self.trade_logger.log_trade_update(
                        trade_record.id, trailing_sl=new_sl
                    )
                    self.trade_logger.log_event(
                        "SL_MODIFIED",
                        symbol=trade_record.symbol,
                        trade_id=trade_record.id,
                        details=f"Trailing SL: {current_sl:.5f} → {new_sl:.5f}",
                    )
        else:  # SHORT
            # Track lowest price
            prev_lowest = self._lowest_since_partial.get(ticket, current_price)
            lowest = min(prev_lowest, current_price)
            self._lowest_since_partial[ticket] = lowest

            new_sl = lowest + trail_distance
            current_sl = trade_record.trailing_sl or trade_record.entry_price

            logger.debug(
                f"[TRAIL_DEBUG] {trade_record.symbol} dir=SHORT "
                f"price={current_price:.5f} lowest={lowest:.5f} "
                f"trail_dist={trail_distance:.5f} new_sl={new_sl:.5f} "
                f"current_sl={current_sl:.5f} would_modify={new_sl < current_sl}"
            )

            # Only move SL down, never up
            if new_sl < current_sl:
                if self.order_manager.modify_stop_loss(
                    ticket, trade_record.symbol, new_sl
                ):
                    self.trade_logger.log_trade_update(
                        trade_record.id, trailing_sl=new_sl
                    )
                    self.trade_logger.log_event(
                        "SL_MODIFIED",
                        symbol=trade_record.symbol,
                        trade_id=trade_record.id,
                        details=f"Trailing SL: {current_sl:.5f} → {new_sl:.5f}",
                    )

    def _find_position_for_trade(self, trade_record):
        """Find an MT5 position matching this trade's symbol, direction, and magic number."""
        if not MT5_AVAILABLE:
            return None
        positions = mt5.positions_get(symbol=trade_record.symbol)
        if not positions:
            return None
        expected_type = 0 if trade_record.direction == "LONG" else 1  # BUY=0, SELL=1
        for pos in positions:
            if pos.type != expected_type:
                continue
            # Verify magic number to avoid matching manual positions
            if pos.magic != 20250305:
                continue
            return {
                "ticket": pos.ticket,
                "price_current": pos.price_current,
                "profit": pos.profit,
                "volume": pos.volume,
            }
        return None

    def _close_trade(self, trade_record, ticket, position, reason):
        """Close a trade fully and update records."""
        direction = trade_record.direction

        ptype = trade_record.pattern_type or "AUTO"
        result = self.order_manager.close_position(
            ticket, trade_record.symbol, direction, f"{ptype} {reason}"
        )

        if result:
            # Use actual fill price from close order, not pre-close snapshot
            close_price = result["fill_price"] if isinstance(result, dict) else position["price_current"]
            pnl = position["profit"]
            pip_value = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
            if direction == "LONG":
                pnl_pips = (close_price - trade_record.entry_price) / pip_value
            else:
                pnl_pips = (trade_record.entry_price - close_price) / pip_value

            self.trade_logger.log_trade_close(
                trade_record.id, close_price, pnl, pnl_pips, reason
            )
            self.trade_logger.log_event(
                "TRADE_CLOSED",
                symbol=trade_record.symbol,
                trade_id=trade_record.id,
                details=f"Reason={reason}, PnL={pnl:.2f}, Pips={pnl_pips:.1f}",
            )

            # Clean up tracking dicts
            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)

    def _handle_server_close(self, trade_record):
        """
        Handle case where position was closed server-side (SL/TP hit).
        Check MT5 deal history to get close details.
        """
        if not MT5_AVAILABLE:
            return

        ticket = trade_record.mt5_ticket

        # Search deal history (7 days to catch weekend gaps and delayed reporting)
        now = datetime.now(timezone.utc)
        from_date = now - timedelta(days=7)
        deals = mt5.history_deals_get(from_date, now, position=ticket)

        # IC Markets often returns nothing for position=ticket filter.
        # Fall back to broad search filtered by symbol.
        if not deals:
            logger.info(
                f"[TRADE_MONITOR] No deals for position={ticket}, "
                f"trying broad search for {trade_record.symbol}"
            )
            all_deals = mt5.history_deals_get(from_date, now)
            if all_deals:
                deals = [d for d in all_deals if d.symbol == trade_record.symbol]

        if not deals:
            # Final safety check: is the position actually still alive in MT5?
            still_alive = self._find_position_for_trade(trade_record)
            if still_alive:
                logger.error(
                    f"Position {ticket} ({trade_record.symbol}) has no deals but "
                    f"a matching position still exists in MT5 — skipping close. "
                    f"Likely transient MT5 query issue."
                )
                return

            # Truly gone with no deal history — estimate from SL
            if trade_record.trailing_sl:
                close_price = trade_record.trailing_sl
                source = "trailing SL"
            elif trade_record.stop_loss:
                close_price = trade_record.stop_loss
                source = "stop loss"
            else:
                close_price = trade_record.entry_price
                source = "entry (no SL)"

            pip_value = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
            if trade_record.direction == "LONG":
                pnl_pips = (close_price - trade_record.entry_price) / pip_value
            else:
                pnl_pips = (trade_record.entry_price - close_price) / pip_value

            lot_size = trade_record.lot_size or 0.01
            pnl = pnl_pips * 10.0 * lot_size  # approximate $10/pip/lot

            reason = "BREAKEVEN_SL" if trade_record.partial_closed else "STOP_LOSS"
            logger.warning(
                f"Position {ticket} disappeared, no deals found. "
                f"Estimated close at {source}: {pnl_pips:+.1f} pips"
            )
            self.trade_logger.log_trade_close(
                trade_record.id, close_price, pnl, pnl_pips, reason
            )
            self.trade_logger.log_event(
                "TRADE_CLOSED",
                symbol=trade_record.symbol,
                trade_id=trade_record.id,
                details=f"Server-side close (no deals): {reason} at {source}, ~{pnl_pips:+.1f}p",
            )
            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)
            return

        # Find the closing deal — must match symbol, direction, and timing
        close_deal = None
        # Expected close deal type: LONG closes with SELL (1), SHORT with BUY (0)
        expected_deal_type = 1 if trade_record.direction == "LONG" else 0
        trade_open_time = trade_record.opened_at
        if trade_open_time and trade_open_time.tzinfo is None:
            trade_open_time = trade_open_time.replace(tzinfo=timezone.utc)

        # Log raw deals for diagnostics (IC Markets deal format debugging)
        logger.info(
            f"[DEAL_SEARCH] {trade_record.symbol} ticket={ticket}: "
            f"{len(deals)} deals found. Looking for type={expected_deal_type}, "
            f"after={trade_open_time}"
        )
        for d in deals[:10]:
            deal_time = datetime.fromtimestamp(d.time, tz=timezone.utc)
            logger.debug(
                f"[DEAL_RAW] ticket={d.ticket} pos={d.position_id} symbol={d.symbol} "
                f"entry={d.entry} type={d.type} price={d.price} profit={d.profit} "
                f"time={deal_time}"
            )

        # Two-pass matching:
        # Pass 1: exact position ticket match (most reliable when available)
        for deal in deals:
            if deal.position_id != ticket or deal.symbol != trade_record.symbol:
                continue
            if deal.type != expected_deal_type:
                continue
            if trade_open_time:
                deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
                if deal_time < (trade_open_time - timedelta(seconds=60)):
                    continue
            close_deal = deal

        # Pass 2: fallback to entry-based matching (broader, for IC Markets quirks)
        if not close_deal:
            for deal in deals:
                if deal.symbol != trade_record.symbol:
                    continue
                if deal.type != expected_deal_type:
                    continue
                # Accept entry=1 (standard exit) or entry=0 (some brokers use for SL fills)
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
            pip_value = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
            direction = trade_record.direction

            if direction == "LONG":
                pnl_pips = (close_price - trade_record.entry_price) / pip_value
            else:
                pnl_pips = (trade_record.entry_price - close_price) / pip_value

            reason = "STOP_LOSS" if pnl < 0 else "TAKE_PROFIT"
            self.trade_logger.log_trade_close(
                trade_record.id, close_price, pnl, pnl_pips, reason
            )
            self.trade_logger.log_event(
                "TRADE_CLOSED",
                symbol=trade_record.symbol,
                trade_id=trade_record.id,
                details=f"Server-side close: {reason}, PnL={pnl:.2f}",
            )

            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)
        else:
            # No matching close deal — estimate from trailing SL or entry price
            close_price = trade_record.trailing_sl or trade_record.entry_price
            pip_value = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
            direction = trade_record.direction
            if direction == "LONG":
                pnl_pips = (close_price - trade_record.entry_price) / pip_value
            else:
                pnl_pips = (trade_record.entry_price - close_price) / pip_value

            source = "trailing SL" if trade_record.trailing_sl else "entry (breakeven)"
            reason = "TRAILING_STOP" if trade_record.trailing_sl else (
                "BREAKEVEN_SL" if trade_record.partial_closed else "UNKNOWN"
            )
            lot_size = trade_record.lot_size or 0.01
            estimated_pnl = pnl_pips * 10.0 * lot_size
            logger.warning(
                f"Position {ticket} closed but no matching deal for {trade_record.symbol}. "
                f"Estimating close at {source} {close_price:.5f} ({pnl_pips:+.1f} pips, "
                f"~{estimated_pnl:+.2f})."
            )
            self.trade_logger.log_trade_close(
                trade_record.id, close_price, estimated_pnl, pnl_pips, reason
            )
