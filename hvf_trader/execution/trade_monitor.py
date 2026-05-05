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
    combine_split_pnl,
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
        poll = config.TRADE_MONITOR_INTERVAL_SEC
        hb_every = max(1, int(60 / poll))
        logger.info(
            "Trade monitor started (poll=%ds, heartbeat every %d iters)",
            poll, hb_every,
        )
        iter_count = 0
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
            iter_count += 1
            if iter_count % hb_every == 0:
                try:
                    open_count = len(self.trade_logger.get_open_trades())
                except Exception:
                    open_count = -1
                logger.info(
                    "Trade monitor heartbeat: iter=%d open_trades=%d",
                    iter_count, open_count,
                )
            time.sleep(poll)

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
        # Asian Gravity, London Breakout, Quantum London, and Night Tide trades
        # have broker-side TP/SL and time-based exit managed by their own scanners
        if trade_record.pattern_type in (
            "ASIAN_GRAVITY", "LONDON_BO", "QUANTUM_LONDON", "NIGHT_TIDE",
        ):
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
            # Split-order safety: if the partial ticket is still alive on MT5,
            # defer server-close. Otherwise we'd record the trade as CLOSED
            # while the partial keeps running — orphaned, untracked, and the
            # actual loss appears only in account balance not the DB.
            partial_ticket = getattr(trade_record, "mt5_ticket_partial", None)
            if partial_ticket:
                partial_pos = self.order_manager.get_position_by_ticket(partial_ticket)
                if partial_pos is not None:
                    if count < 32:  # 30-min defer cap (1s polling)
                        logger.info(
                            f"Trade {trade_record.id} main ticket {ticket} gone "
                            f"but partial {partial_ticket} still alive — "
                            f"deferring server-close ({count}/30)"
                        )
                        return
                    logger.warning(
                        f"Trade {trade_record.id} partial {partial_ticket} "
                        f"orphaned for 30+ min — force-closing"
                    )
                    self.order_manager.close_position(
                        partial_ticket, trade_record.symbol, trade_record.direction,
                        f"{trade_record.pattern_type or 'AUTO'} partial_orphan_force_close",
                    )
            self._missing_position_counts.pop(ticket, None)
            self._handle_server_close(trade_record)
            return
        # Position found — reset miss counter
        self._missing_position_counts.pop(ticket, None)

        current_price = position["price_current"]
        direction = trade_record.direction

        # ─── Split-order T1 detection + failsafe ─────────────────────────
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
            elif trade_record.target_1 and MT5_AVAILABLE:
                # Failsafe: partial still open but price may have moved past T1.
                # On IC Markets we've seen broker-side TPs fail to trigger even
                # when bid/ask crosses the level. Force-close manually to lock
                # in the profit the strategy expected.
                import MetaTrader5 as _mt5
                tick = _mt5.symbol_info_tick(trade_record.symbol)
                if tick is not None:
                    pip = config.PIP_VALUES.get(trade_record.symbol, 0.0001)
                    buffer = 0.5 * pip  # avoid thrashing on wicks right at T1
                    trigger_breached = False
                    if direction == "LONG" and tick.bid >= trade_record.target_1 + buffer:
                        # For LONG: close fill is BID ≥ T1 → matches target, guaranteed profit.
                        trigger_breached = True
                    elif direction == "SHORT" and tick.bid <= trade_record.target_1 - buffer:
                        # For SHORT: use BID (chart price) crossing T1, not ASK.
                        # When spread widens during Asian hours, ASK may never reach T1
                        # even though visible chart price does. Fill is at ASK, so the
                        # realized profit will be less than target_pips by the spread —
                        # but only force-close if the fill would still be profitable
                        # relative to entry. Otherwise let SL protect us.
                        if tick.ask < trade_record.entry_price:
                            trigger_breached = True
                    if trigger_breached:
                        logger.warning(
                            f"[T1_FAILSAFE] Trade {trade_record.id}: price past T1 "
                            f"but partial ticket {trade_record.mt5_ticket_partial} "
                            f"still open — forcing manual close "
                            f"(bid={tick.bid} ask={tick.ask} T1={trade_record.target_1})"
                        )
                        close_result = self.order_manager.close_position(
                            trade_record.mt5_ticket_partial,
                            trade_record.symbol, direction,
                            f"{trade_record.pattern_type or 'AUTO'} TP_failsafe"
                        )
                        if close_result:
                            fill_price = (
                                close_result.get("fill_price")
                                if isinstance(close_result, dict)
                                else trade_record.target_1
                            )
                            self.trade_logger.log_partial_close(
                                trade_record.id, fill_price
                            )
                            # Reload so downstream sees partial_closed=True
                            from hvf_trader.database.models import TradeRecord as _TR
                            refreshed = self.trade_logger._session.get(_TR, trade_record.id)
                            if refreshed is not None:
                                trade_record = refreshed
                            # Move main SL to breakeven
                            be_sl = trade_record.entry_price
                            self.order_manager.modify_stop_loss(
                                ticket, trade_record.symbol, be_sl
                            )
                            self.trade_logger.log_trade_update(
                                trade_record.id, trailing_sl=be_sl
                            )
                            # Init trailing trackers
                            if direction == "LONG":
                                self._highest_since_partial[ticket] = tick.bid
                            else:
                                self._lowest_since_partial[ticket] = tick.ask
                            logger.info(
                                f"[T1_FAILSAFE] Trade {trade_record.id}: partial "
                                f"force-closed @ {fill_price}, main SL → breakeven {be_sl}"
                            )
                            if self.alerter:
                                self.alerter.send_message(
                                    f"<b>[T1_FAILSAFE] Broker TP not honored</b>\n"
                                    f"{trade_record.symbol} {direction}: partial ticket "
                                    f"{trade_record.mt5_ticket_partial} force-closed @ "
                                    f"{fill_price:.5f}\n"
                                    f"Main SL moved to breakeven {be_sl:.5f}"
                                )

        # ─── Time stop ───────────────────────────────────────────────────
        # Force-close trades that have aged past the configured threshold.
        # KZ_HUNT: 4 H1 bars. Backstop for slow drifters that haven't hit TP
        # or SL — backtest recovers +85p from the SL bucket on this pattern.
        time_stop_hours = config.TIME_STOP_HOURS_BY_PATTERN.get(
            trade_record.pattern_type, 0,
        )
        if time_stop_hours > 0 and trade_record.opened_at:
            opened = trade_record.opened_at
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            held_hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
            if held_hours >= time_stop_hours:
                logger.info(
                    f"[TIME_STOP] Trade {trade_record.id} held {held_hours:.1f}h "
                    f">= {time_stop_hours}h limit — force-closing"
                )
                self._close_trade(
                    trade_record, ticket, position, "TIME_STOP",
                )
                return

        # ─── Move SL to breakeven at N% progress toward T1 ───────────────
        # Catches trades that get close to T1 but reverse before triggering
        # the partial-close. Live data: 18/19 SL'd trades with MFE>5p had
        # reached 50% of T1 distance. Recovers ~+113p / $1,100 across 109
        # KZ_HUNT trades. Independent of the partial-close path; once partial
        # fires, the existing logic moves SL to BE there.
        be_progress = config.BE_AT_T1_PROGRESS_BY_PATTERN.get(
            trade_record.pattern_type, 0.0,
        )
        if (be_progress > 0 and not trade_record.partial_closed
                and trade_record.target_1 is not None
                and (trade_record.trailing_sl is None
                     or abs(trade_record.trailing_sl - trade_record.entry_price)
                        > config.PIP_VALUES.get(trade_record.symbol, 0.0001) * 0.5)):
            entry = trade_record.entry_price
            t1 = trade_record.target_1
            be_trigger = entry + be_progress * (t1 - entry)
            triggered = (
                (direction == "LONG" and current_price >= be_trigger)
                or (direction == "SHORT" and current_price <= be_trigger)
            )
            if triggered:
                self.order_manager.modify_stop_loss(
                    ticket, trade_record.symbol, entry,
                )
                self.trade_logger.log_trade_update(
                    trade_record.id, trailing_sl=entry,
                )
                logger.info(
                    f"[BE_PROGRESS] Trade {trade_record.id}: "
                    f"price reached {be_progress*100:.0f}% of T1 — SL → breakeven {entry:.5f}"
                )
                trade_record.trailing_sl = entry

        # ─── Pre-partial ATR trail ───────────────────────────────────────
        # Once MFE crosses N×ATR_H1, start trailing SL at N×ATR from the
        # peak favorable price — independent of partial-close. Combined with
        # BE@50%T1 above, recovers +94p net / +160p SL-bucket across 109
        # KZ_HUNT trades. Pattern-gated; 0.0 disables.
        pre_partial_trail_atr = config.PRE_PARTIAL_TRAIL_ATR_BY_PATTERN.get(
            trade_record.pattern_type, 0.0,
        )
        if (pre_partial_trail_atr > 0 and not trade_record.partial_closed):
            cached = self._atr_cache.get(trade_record.symbol)
            current_atr = None
            if cached and (time.time() - cached[0]) < 120:
                current_atr = cached[1]
            else:
                from hvf_trader.data.data_fetcher import fetch_and_prepare
                df_atr = fetch_and_prepare(
                    trade_record.symbol, config.PRIMARY_TIMEFRAME, bars=20,
                )
                if df_atr is not None and not df_atr.empty:
                    current_atr = df_atr["atr"].iloc[-1]
                    self._atr_cache[trade_record.symbol] = (time.time(), current_atr)

            if current_atr is not None and current_atr > 0:
                entry = trade_record.entry_price
                if direction == "LONG":
                    mfe = current_price - entry
                    if mfe >= pre_partial_trail_atr * current_atr:
                        new_sl = current_price - pre_partial_trail_atr * current_atr
                        current_sl = trade_record.trailing_sl or trade_record.stop_loss
                        if new_sl > current_sl:
                            self.order_manager.modify_stop_loss(
                                ticket, trade_record.symbol, new_sl,
                            )
                            self.trade_logger.log_trade_update(
                                trade_record.id, trailing_sl=new_sl,
                            )
                            logger.info(
                                f"[PRE_PARTIAL_TRAIL] Trade {trade_record.id}: "
                                f"MFE {mfe:.5f} >= {pre_partial_trail_atr}×ATR; "
                                f"SL → {new_sl:.5f}"
                            )
                            trade_record.trailing_sl = new_sl
                else:  # SHORT
                    mfe = entry - current_price
                    if mfe >= pre_partial_trail_atr * current_atr:
                        new_sl = current_price + pre_partial_trail_atr * current_atr
                        current_sl = trade_record.trailing_sl or trade_record.stop_loss
                        if new_sl < current_sl:
                            self.order_manager.modify_stop_loss(
                                ticket, trade_record.symbol, new_sl,
                            )
                            self.trade_logger.log_trade_update(
                                trade_record.id, trailing_sl=new_sl,
                            )
                            logger.info(
                                f"[PRE_PARTIAL_TRAIL] Trade {trade_record.id}: "
                                f"MFE {mfe:.5f} >= {pre_partial_trail_atr}×ATR; "
                                f"SL → {new_sl:.5f}"
                            )
                            trade_record.trailing_sl = new_sl

        # Get associated pattern for invalidation check
        pattern = None
        if trade_record.pattern_id:
            from hvf_trader.database.models import PatternRecord
            pattern = self.trade_logger.session.get(PatternRecord, trade_record.pattern_id)

        # ─── Check invalidation ──────────────────────────────────────────
        # Uses completed H1 bar close (not current tick) to match backtest
        # behavior.  Only re-evaluates when a new bar completes.
        # Grace period: skip for first 2 H1 bars (2 hours).
        # Per-pattern toggle: KZ_HUNT disabled 2026-04-28 (backtest-overfit).
        invalidation_enabled = config.INVALIDATION_ENABLED_BY_PATTERN.get(
            trade_record.pattern_type, True,
        )
        if invalidation_enabled and pattern and not trade_record.partial_closed:
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
        """Handle a partial position that disappeared from MT5.

        The partial COULD have hit T1 (broker TP) — in which case partial_close_price
        should be T1. But it could also have closed for any of:
          - Broker SL hit (rare: partial's SL is wide unless we trailed it)
          - Our own force-close (TIME_STOP, server_close partial, orphan force-close)
          - Manual user close
        Recording T1 in those cases overstates the wins by 30-50p.

        Resolution: query MT5 deal history for the partial ticket and use the
        ACTUAL fill price. Default to T1 only if deal lookup fails (true at-T1
        is the most likely scenario when MT5 broker TP fires cleanly).
        """
        direction = trade_record.direction
        t1_price = trade_record.target_1
        actual_close_price = t1_price

        partial_ticket = getattr(trade_record, "mt5_ticket_partial", None)
        if partial_ticket:
            try:
                partial_deals = search_deal_history(partial_ticket, trade_record.symbol)
                if partial_deals:
                    cd = find_close_deal(
                        partial_deals, partial_ticket, trade_record.symbol,
                        direction, trade_record.opened_at,
                    )
                    if cd:
                        actual_close_price = cd.price
                        if abs(actual_close_price - t1_price) > 0.0005:
                            # Closed substantially off T1 — log it loudly. This is
                            # the case where the partial was force-closed by us or
                            # hit a SL, not a clean T1 fill.
                            logger.warning(
                                f"Trade {trade_record.id} partial {partial_ticket} "
                                f"closed at {actual_close_price:.5f} (T1 was {t1_price:.5f}) — "
                                f"NOT a clean T1 fill. Recording actual price."
                            )
            except Exception as e:
                logger.warning(
                    f"Deal lookup for partial ticket {partial_ticket} failed: {e}"
                )

        # Mark partial close in DB at the actual broker fill price.
        self.trade_logger.log_partial_close(trade_record.id, actual_close_price)

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

        # If split order, also close the partial position if still open.
        # CRITICAL: capture the actual fill price and call log_partial_close with
        # it. Without this, downstream PnL estimation defaults to T1 — which
        # massively overstates wins when we're force-closing a non-T1 partial
        # (e.g. TIME_STOP, server_close).
        partial_ticket = getattr(trade_record, 'mt5_ticket_partial', None)
        if partial_ticket and not trade_record.partial_closed:
            partial_pos = self.order_manager.get_position_by_ticket(partial_ticket)
            if partial_pos:
                logger.info(
                    f"Closing partial position {partial_ticket} "
                    f"(trade {trade_record.id} closing: {reason})"
                )
                partial_result = self.order_manager.close_position(
                    partial_ticket, trade_record.symbol, direction,
                    f"{trade_record.pattern_type or 'AUTO'} {reason} partial"
                )
                if partial_result:
                    partial_fill = (
                        partial_result.get("fill_price")
                        if isinstance(partial_result, dict)
                        else partial_pos.get("price_current")
                    )
                    if partial_fill:
                        self.trade_logger.log_partial_close(
                            trade_record.id, partial_fill
                        )
                        logger.info(
                            f"Trade {trade_record.id}: partial closed @ "
                            f"{partial_fill:.5f} (reason: {reason}, NOT T1)"
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

        # If split order, handle the partial position.
        # Same critical fix as in _close_trade: capture actual fill and log it.
        partial_ticket = getattr(trade_record, 'mt5_ticket_partial', None)
        if partial_ticket:
            partial_pos = self.order_manager.get_position_by_ticket(partial_ticket)
            if partial_pos:
                logger.info(
                    f"Closing partial position {partial_ticket} "
                    f"(remaining position {trade_record.mt5_ticket} server-closed)"
                )
                partial_result = self.order_manager.close_position(
                    partial_ticket, trade_record.symbol, trade_record.direction,
                    f"{trade_record.pattern_type or 'AUTO'} server_close partial"
                )
                if partial_result and not trade_record.partial_closed:
                    partial_fill = (
                        partial_result.get("fill_price")
                        if isinstance(partial_result, dict)
                        else partial_pos.get("price_current")
                    )
                    if partial_fill:
                        self.trade_logger.log_partial_close(
                            trade_record.id, partial_fill
                        )
                        logger.info(
                            f"Trade {trade_record.id}: partial server-close "
                            f"recorded @ {partial_fill:.5f} (NOT T1)"
                        )
            elif not trade_record.partial_closed:
                # Bug-fix: partial position already gone but DB never recorded T1 hit.
                # Happens when both the partial (at T1) and the main (at SL) close
                # between monitor polls, so _handle_split_t1_hit was never called.
                # The broker's TP on the partial ticket is tick-level, so if the
                # position is gone it almost certainly closed at T1.
                partial_close_price = trade_record.target_1
                try:
                    partial_deals = search_deal_history(
                        partial_ticket, trade_record.symbol
                    )
                    if partial_deals:
                        cd = find_close_deal(
                            partial_deals, partial_ticket, trade_record.symbol,
                            trade_record.direction, trade_record.opened_at,
                        )
                        if cd:
                            partial_close_price = cd.price
                except Exception as e:
                    logger.warning(
                        f"Deal lookup for partial ticket {partial_ticket} failed: {e}"
                    )
                logger.warning(
                    f"Detected late partial close for trade {trade_record.id}: "
                    f"partial ticket {partial_ticket} gone, recording close @ "
                    f"{partial_close_price:.5f} (assumed T1)"
                )
                self.trade_logger.log_partial_close(
                    trade_record.id, partial_close_price
                )
                # Reload so downstream PnL estimation sees partial_closed=True
                from hvf_trader.database.models import TradeRecord as _TR
                refreshed = self.trade_logger._session.get(_TR, trade_record.id)
                if refreshed is not None:
                    trade_record = refreshed

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
            # For split orders with a prior partial close, combine both legs.
            pnl, pnl_pips = combine_split_pnl(
                trade_record, close_price, close_deal.profit
            )

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
