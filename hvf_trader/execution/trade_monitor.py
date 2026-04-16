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
from hvf_trader.execution.deal_utils import (
    search_deal_history,
    find_close_deal,
    estimate_fallback_pnl,
)


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
        self._bar_cache = {}  # symbol -> (wall_ts, bar_time, bar_close) — completed H1 bar
        self._last_invalidation_bar = {}  # trade_id -> bar_time last checked
        self._recent_errors = []  # timestamps of recent errors for burst detection
        self._last_error_alert = None  # throttle error burst alerts

    def _track_error(self, error_msg: str):
        """Track errors and alert on bursts (3+ in 5 minutes)."""
        now = datetime.now(timezone.utc)
        self._recent_errors.append(now)
        # Prune entries older than 5 minutes
        cutoff = now - timedelta(minutes=5)
        self._recent_errors = [t for t in self._recent_errors if t > cutoff]
        # Alert if 3+ errors in window and not alerted in last 30 min
        if len(self._recent_errors) >= 3 and self.alerter:
            if (self._last_error_alert is None
                    or now - self._last_error_alert > timedelta(minutes=30)):
                self._last_error_alert = now
                self.alerter.alert_error(
                    f"Error burst: {len(self._recent_errors)} errors in 5 min\n"
                    f"Latest: {error_msg[:200]}"
                )

    def start(self):
        """Start the trade monitoring loop."""
        self._running = True
        logger.info("Trade monitor started")
        while self._running:
            try:
                self._monitor_cycle()
            except Exception as e:
                logger.error(f"Trade monitor error: {e}", exc_info=True)
                self._track_error(str(e))
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
                self._track_error(f"trade {trade_record.id}: {e}")

    def _check_trade(self, trade_record):
        """
        Check a single open trade. Asian Gravity trades are managed by their
        own scanner thread (TP/SL broker-side, time exit at 06:00), so we
        skip them here to avoid interference.
        """
        # Asian Gravity and London Breakout trades have broker-side TP/SL
        # and time-based exit managed by their own scanners
        if trade_record.pattern_type in ("ASIAN_GRAVITY", "LONDON_BO", "QUANTUM_LONDON"):
            return
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

        # ─── Split-order T1 detection ────────────────────────────────────
        # If this trade has a split partial position (60% with TP=T1),
        # check if MT5 closed it (T1 hit at tick level).
        if not trade_record.partial_closed and getattr(trade_record, 'mt5_ticket_partial', None):
            partial_pos = self.order_manager.get_position_by_ticket(
                trade_record.mt5_ticket_partial
            )
            if partial_pos is None:
                # Partial position closed — MT5 TP hit T1
                logger.info(
                    f"Trade {trade_record.id}: T1 hit by MT5 TP "
                    f"(partial ticket {trade_record.mt5_ticket_partial} closed)"
                )
                self._handle_split_t1_hit(trade_record, ticket, position)
                # Continue to trailing check below (don't return)

        # Get associated pattern for invalidation check
        pattern = None
        if trade_record.pattern_id:
            from hvf_trader.database.models import PatternRecord
            pattern = self.trade_logger.session.get(PatternRecord, trade_record.pattern_id)

        # ─── Check invalidation ──────────────────────────────────────────
        # Uses completed H1 bar close (not current tick) to match backtest
        # behavior.  Only re-evaluates when a new bar completes.
        # Grace period: skip for first 2 H1 bars (2 hours).
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
                bar_time, bar_close = self._get_completed_bar(trade_record.symbol)
                if bar_time is not None:
                    last_checked = self._last_invalidation_bar.get(trade_record.id)
                    if last_checked != bar_time:
                        self._last_invalidation_bar[trade_record.id] = bar_time
                        invalidated = False
                        if direction == "LONG" and bar_close <= pattern.l3_price:
                            invalidated = True
                        elif direction == "SHORT" and bar_close >= pattern.h3_price:
                            invalidated = True

                        if invalidated:
                            logger.warning(
                                f"Trade {ticket} invalidated: H1 bar close "
                                f"{bar_close:.5f} revisited "
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
        # Legacy path: only for trades without split orders (small lot fallback)
        if not trade_record.partial_closed and trade_record.target_1:
            if not getattr(trade_record, 'mt5_ticket_partial', None):
                # No split order — use snapshot-based T1 detection
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

    def _handle_split_t1_hit(self, trade_record, ticket, position):
        """Handle T1 hit detected via MT5 TP on the split partial position.

        The 60% partial position was closed by MT5 at T1 (tick-level precision).
        Now move the remaining 40% position's SL to breakeven and start trailing.
        """
        direction = trade_record.direction
        t1_price = trade_record.target_1

        # Mark partial close in DB
        self.trade_logger.log_partial_close(trade_record.id, t1_price)

        # Move remaining position SL to breakeven (entry price)
        breakeven_sl = trade_record.entry_price
        self.order_manager.modify_stop_loss(
            ticket, trade_record.symbol, breakeven_sl
        )
        self.trade_logger.log_trade_update(
            trade_record.id, trailing_sl=breakeven_sl
        )

        # Initialize tracking for trailing stop
        if direction == "LONG":
            self._highest_since_partial[ticket] = position["price_current"]
        else:
            self._lowest_since_partial[ticket] = position["price_current"]

        self.trade_logger.log_event(
            "PARTIAL_CLOSE",
            symbol=trade_record.symbol,
            trade_id=trade_record.id,
            details=f"T1 hit by MT5 TP @ {t1_price}, "
                    f"SL moved to breakeven {breakeven_sl}",
        )
        logger.info(
            f"Split T1 hit: trade {trade_record.id}, "
            f"partial ticket {trade_record.mt5_ticket_partial} closed @ T1={t1_price}, "
            f"remaining ticket {ticket} SL→breakeven={breakeven_sl}"
        )
        if self.alerter:
            pip_size = 0.01 if "JPY" in trade_record.symbol else 0.0001
            pnl_pips = (t1_price - trade_record.entry_price) / pip_size
            if direction == "SHORT":
                pnl_pips = -pnl_pips
            self.alerter.alert_partial_close(
                trade_record.symbol, direction, t1_price, pnl_pips,
            )

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

    def _get_completed_bar(self, symbol):
        """Return (bar_time, bar_close) for the latest completed H1 bar.

        Cached per symbol, refreshed every 120s.  The forming bar
        (iloc[-1]) is excluded — only the most recent closed bar is used.
        Returns (None, None) on failure.
        """
        now = time.time()
        cached = self._bar_cache.get(symbol)
        if cached and (now - cached[0]) < 120:
            return cached[1], cached[2]

        from hvf_trader.data.data_fetcher import fetch_and_prepare
        df = fetch_and_prepare(symbol, config.PRIMARY_TIMEFRAME, bars=5)
        if df is None or len(df) < 2:
            return None, None

        # iloc[-1] is the forming bar; iloc[-2] is the last completed bar
        completed = df.iloc[-2]
        bar_time = completed["time"]
        bar_close = float(completed["close"])
        self._bar_cache[symbol] = (now, bar_time, bar_close)
        return bar_time, bar_close

    def _close_trade(self, trade_record, ticket, position, reason):
        """Close a trade fully and update records."""
        direction = trade_record.direction

        # If split order, also close the partial position if still open
        partial_ticket = getattr(trade_record, 'mt5_ticket_partial', None)
        if partial_ticket:
            partial_pos = self.order_manager.get_position_by_ticket(partial_ticket)
            if partial_pos:
                logger.info(
                    f"Closing partial position {partial_ticket} "
                    f"(trade {trade_record.id} closing: {reason})"
                )
                self.order_manager.close_position(
                    partial_ticket, trade_record.symbol, direction,
                    f"{trade_record.pattern_type or 'AUTO'} {reason} partial"
                )

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
            if self.alerter:
                self.alerter.alert_trade_closed(
                    trade_record.symbol, direction, close_price, pnl, pnl_pips, reason
                )

            # Clean up tracking dicts
            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)
            self._last_invalidation_bar.pop(trade_record.id, None)

    def _estimate_fallback_pnl(self, trade_record, close_price):
        """Estimate PnL when no deal history available. Delegates to shared utility."""
        return estimate_fallback_pnl(trade_record, close_price)

    def _handle_server_close(self, trade_record):
        """
        Handle case where position was closed server-side (SL/TP hit).
        Check MT5 deal history to get close details.
        """
        if not MT5_AVAILABLE:
            return

        # If split order, close the partial position too (if still open)
        partial_ticket = getattr(trade_record, 'mt5_ticket_partial', None)
        if partial_ticket:
            partial_pos = self.order_manager.get_position_by_ticket(partial_ticket)
            if partial_pos:
                logger.info(
                    f"Closing partial position {partial_ticket} "
                    f"(remaining position {trade_record.mt5_ticket} server-closed)"
                )
                self.order_manager.close_position(
                    partial_ticket, trade_record.symbol, trade_record.direction,
                    f"{trade_record.pattern_type or 'AUTO'} server_close partial"
                )

        ticket = trade_record.mt5_ticket

        # Search deal history using shared utility (handles IC Markets broad fallback)
        deals = search_deal_history(ticket, trade_record.symbol)

        if not deals:
            # IC Markets deals can take seconds to appear. Defer to next cycle
            # instead of blocking the entire monitor thread with sleep.
            retry_key = f"deal_retry_{ticket}"
            retry_count = self._missing_position_counts.get(retry_key, 0)
            if retry_count < 2:
                self._missing_position_counts[retry_key] = retry_count + 1
                logger.info(
                    f"[TRADE_MONITOR] No deals for {trade_record.symbol} ticket={ticket}, "
                    f"deferring to next cycle (attempt {retry_count + 1}/2)"
                )
                return
            # Exhausted retries, clean up and proceed with fallback
            self._missing_position_counts.pop(retry_key, None)

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

            pnl, pnl_pips = self._estimate_fallback_pnl(trade_record, close_price)

            reason = "BREAKEVEN_SL" if trade_record.partial_closed else "STOP_LOSS"
            logger.warning(
                f"Position {ticket} disappeared, no deals found. "
                f"Estimated close at {source}: {pnl_pips:+.1f} pips, ~${pnl:+.2f}"
                f"{' (includes partial profit)' if trade_record.partial_closed else ''}"
            )
            self.trade_logger.log_trade_close(
                trade_record.id, close_price, pnl, pnl_pips, reason,
                pnl_estimated=True,
            )
            self.trade_logger.log_event(
                "TRADE_CLOSED",
                symbol=trade_record.symbol,
                trade_id=trade_record.id,
                details=f"Server-side close (no deals): {reason} at {source}, ~{pnl_pips:+.1f}p (estimated)",
            )
            if self.alerter:
                self.alerter.alert_trade_closed(
                    trade_record.symbol, trade_record.direction, close_price,
                    pnl, pnl_pips, reason, estimated=True
                )
            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)
            self._last_invalidation_bar.pop(trade_record.id, None)
            return

        # Log raw deals for diagnostics (IC Markets deal format debugging)
        expected_deal_type = 1 if trade_record.direction == "LONG" else 0
        logger.info(
            f"[DEAL_SEARCH] {trade_record.symbol} ticket={ticket}: "
            f"{len(deals)} deals found. Looking for type={expected_deal_type}, "
            f"after={trade_record.opened_at}"
        )
        for d in deals[:10]:
            deal_time = datetime.fromtimestamp(d.time, tz=timezone.utc)
            logger.debug(
                f"[DEAL_RAW] ticket={d.ticket} pos={d.position_id} symbol={d.symbol} "
                f"entry={d.entry} type={d.type} price={d.price} profit={d.profit} "
                f"time={deal_time}"
            )

        # Two-pass matching using shared utility
        close_deal = find_close_deal(
            deals, ticket, trade_record.symbol,
            trade_record.direction, trade_record.opened_at,
        )

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
            if self.alerter:
                self.alerter.alert_trade_closed(
                    trade_record.symbol, trade_record.direction, close_price,
                    pnl, pnl_pips, reason
                )

            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)
            self._last_invalidation_bar.pop(trade_record.id, None)
        else:
            # No matching close deal — estimate from best available price.
            # Server-side closes are almost always SL hits on IC Markets.
            if trade_record.trailing_sl:
                close_price = trade_record.trailing_sl
                source = "trailing SL"
                reason = "TRAILING_STOP"
            elif trade_record.stop_loss and not trade_record.partial_closed:
                close_price = trade_record.stop_loss
                source = "stop loss"
                reason = "STOP_LOSS"
            elif trade_record.partial_closed:
                close_price = trade_record.entry_price
                source = "entry (breakeven)"
                reason = "BREAKEVEN_SL"
            else:
                close_price = trade_record.entry_price
                source = "entry (no SL)"
                reason = "UNKNOWN"

            estimated_pnl, pnl_pips = self._estimate_fallback_pnl(trade_record, close_price)
            logger.warning(
                f"Position {ticket} closed but no matching deal for {trade_record.symbol}. "
                f"Estimating close at {source} {close_price:.5f} ({pnl_pips:+.1f} pips, "
                f"~{estimated_pnl:+.2f})"
                f"{' (includes partial profit)' if trade_record.partial_closed else ''}."
            )
            self.trade_logger.log_trade_close(
                trade_record.id, close_price, estimated_pnl, pnl_pips, reason,
                pnl_estimated=True,
            )
            if self.alerter:
                self.alerter.alert_trade_closed(
                    trade_record.symbol, trade_record.direction, close_price,
                    estimated_pnl, pnl_pips, reason, estimated=True
                )
            self._highest_since_partial.pop(ticket, None)
            self._lowest_since_partial.pop(ticket, None)
            self._last_invalidation_bar.pop(trade_record.id, None)
