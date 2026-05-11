"""Quantum London scanner thread (FF mean-reversion, thread #743125).

Captures daily open at 22:00 UTC, trades 22:00 UTC capture-day →
21:00 UTC next-day (~22h cycle), wide trigger, narrow TP, no filters.
One trade per session.

Notes:
- Entry uses LIMIT order at the exact trigger price (not market at ask/bid).
  This was the killer bug in the prior grid-EA "Quantum London" attempt:
  entering at broker ask shifted TP further away by the spread, halving
  the win probability.
- No news filter, no spread filter, no range filter — per FF community
  consensus that filters degrade results on this strategy.
- Force-exit at 21:00 UTC fires for any still-open trade.
"""
import json
import logging
import time
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.detector.quantum_london import QLTracker, QLSignal
from hvf_trader.data.data_fetcher import fetch_and_prepare

logger = logging.getLogger("hvf_trader")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


class QuantumLondonScanner:
    """Dedicated scanner thread for the Quantum London strategy."""

    PATTERN_TYPE = "QUANTUM_LONDON"

    def __init__(self, order_manager, trade_logger, risk_manager,
                 circuit_breaker, connector, alerter, cfg=None):
        self._tracker = QLTracker()
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._connector = connector
        self._alerter = alerter
        self._running = False
        self._open_trade_id = None
        # Pending-order state: at capture we place BOTH a BUY_LIMIT and a
        # SELL_LIMIT in the broker book (the canonical FF setup). Whichever
        # gets hit first becomes the trade; the survivor is cancelled. DB
        # write is deferred until the broker actually fills one.
        self._pending_long_ticket: int | None = None
        self._pending_short_ticket: int | None = None
        self._pending_long_signal = None
        self._pending_short_signal = None
        self._pending_lot_size: float | None = None
        self._pending_placed_at: datetime | None = None
        self._cfg = cfg or config.QUANTUM_LONDON
        self._session_stats: dict | None = None
        self._last_telemetry_log_hour: int | None = None

    # ─── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        self._running = True
        poll = self._cfg["poll_interval_sec"]
        hb_every = max(1, int(60 / poll))
        logger.info(
            "[QUANTUM_LONDON] Scanner thread started (poll=%ds, heartbeat every %d iters)",
            poll, hb_every,
        )
        # Clean up any stale QL pending orders left in the broker book from a
        # prior process. Without this, a restart between capture (22:00 UTC)
        # and force-exit (21:00 UTC next day) would leave orders the bot
        # can't see — potentially filling into a ghost position.
        self._cleanup_stale_pendings_on_startup()
        iter_count = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[QUANTUM_LONDON] Scanner error: %s", e, exc_info=True)
            iter_count += 1
            if iter_count % hb_every == 0:
                logger.info(
                    "[QUANTUM_LONDON] heartbeat: iter=%d state=%s "
                    "pending(L/S)=%s/%s open_trade=%s",
                    iter_count, self._tracker.state,
                    self._pending_long_ticket, self._pending_short_ticket,
                    self._open_trade_id,
                )
            time.sleep(poll)
        logger.info("[QUANTUM_LONDON] Scanner thread stopped")

    def stop(self):
        self._running = False

    # ─── Core loop ───────────────────────────────────────────────────

    def _tick(self):
        now = datetime.now(timezone.utc)
        hour = now.hour
        weekday = now.weekday()
        cfg = self._cfg
        sym = cfg["instrument"]
        pip = config.PIP_VALUES.get(sym, 0.0001)

        capture_hour = cfg["capture_utc_hour"]      # 22
        force_exit_hour = cfg["force_exit_utc_hour"]  # 21
        days = cfg["days"]                            # [0,1,2,3,4]

        # ── Pending-order monitoring (limits waiting to fill) ──
        if self._pending_long_ticket is not None or self._pending_short_ticket is not None:
            self._check_pending_status(sym, hour, force_exit_hour, cfg, pip)
            return

        # ── Open-trade monitoring (always runs first if a trade is alive) ──
        if self._open_trade_id is not None:
            self._check_if_closed()
            if self._open_trade_id is None:
                return
            # Force-exit at 21:00 UTC even if broker hasn't fired TP/SL
            if hour == force_exit_hour:
                self._force_exit_open_trade()
                return
            return

        # ── Force-exit + reset window (21:00 UTC) ──
        if hour == force_exit_hour:
            if self._tracker.state == "TRADING":
                # Session ended without firing OR mark_traded already set DONE
                self._emit_session_summary()
            if self._tracker.state != "IDLE":
                self._tracker.reset()
                self._session_stats = None
            return

        # ── Capture daily open at 22:00 UTC ──
        if hour == capture_hour and self._tracker.state == "IDLE":
            if weekday not in days:
                return  # Sat/Sun captures skipped
            df = fetch_and_prepare(sym, cfg["capture_timeframe"], bars=2)
            if df is None or df.empty:
                logger.warning("[QUANTUM_LONDON] Could not fetch capture bar")
                return
            bar = df.iloc[-1]
            session_open = float(bar["open"])
            self._tracker.start_session(session_open, str(now.date()))
            self._session_stats = {
                "session_open": session_open,
                "date": str(now.date()),
                "polls": 0,
                "max_below_pips": 0.0,
                "max_above_pips": 0.0,
                "trigger_crosses_long": 0,
                "trigger_crosses_short": 0,
                "executions_attempted": 0,
                "executions_filled": 0,
                "executions_failed": 0,
            }
            self._last_telemetry_log_hour = None
            logger.info(
                "[QUANTUM_LONDON] Daily open captured: %.5f, date=%s, hold until %02d:00 UTC",
                session_open, now.date(), force_exit_hour,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[QUANTUM_LONDON] Daily open captured</b>\n"
                    f"{sym}: {session_open:.5f}\n"
                    f"Date: {now.date()}\n"
                    f"Trigger: ±{cfg['trigger_pips']:.0f}p\n"
                    f"TP/SL: {cfg['target_pips']:.0f}p / {cfg['stop_pips']:.0f}p\n"
                    f"Force-exit: {force_exit_hour:02d}:00 UTC"
                )
            # Place both pending LIMITs in the broker book — broker fills
            # whichever direction price reaches first; survivor is cancelled
            # on fill or at force-exit.
            self._place_capture_pendings(sym, session_open, cfg, pip)
            return

        # ── Trading phase: poll for trigger ──
        if self._tracker.state != "TRADING":
            return

        if not MT5_AVAILABLE:
            return

        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return

        # Telemetry
        s = self._session_stats
        if s is not None:
            s["polls"] += 1
            so = self._tracker.session_open
            dist_below = (so - tick.bid) / pip
            dist_above = (tick.ask - so) / pip
            if dist_below > s["max_below_pips"]:
                s["max_below_pips"] = dist_below
            if dist_above > s["max_above_pips"]:
                s["max_above_pips"] = dist_above
            trig = cfg["trigger_pips"]
            if tick.bid <= so - trig * pip:
                s["trigger_crosses_long"] += 1
            if tick.ask >= so + trig * pip:
                s["trigger_crosses_short"] += 1
            # Hourly telemetry log
            if hour != self._last_telemetry_log_hour:
                self._last_telemetry_log_hour = hour
                logger.info(
                    "[QUANTUM_LONDON] @%02d:00 UTC polls=%d max_below=%.1fp max_above=%.1fp "
                    "crosses(L/S)=%d/%d",
                    hour, s["polls"], s["max_below_pips"], s["max_above_pips"],
                    s["trigger_crosses_long"], s["trigger_crosses_short"],
                )

        # Execution is now broker-side via the pending LIMIT orders placed at
        # capture; the trading-phase tick loop runs only for telemetry.

    # ─── Execution ───────────────────────────────────────────────────

    def _place_capture_pendings(self, sym, session_open, cfg, pip):
        """Place BUY_LIMIT and SELL_LIMIT in the broker book at capture time.

        Whichever side price reaches first fills; the survivor is cancelled.
        This is the canonical FF Simple Mean Reversion setup (thread #743125)
        and guarantees TP/SL geometry by anchoring to the exact limit price.
        """
        trigger_pips = cfg["trigger_pips"]
        target_pips = cfg["target_pips"]
        stop_pips = cfg["stop_pips"]

        long_limit = session_open - trigger_pips * pip
        short_limit = session_open + trigger_pips * pip

        long_signal = QLSignal(
            symbol=sym, direction="LONG", entry_price=long_limit,
            take_profit=long_limit + target_pips * pip,
            stop_loss=long_limit - stop_pips * pip,
            session_open=session_open, trigger_pips=trigger_pips,
        )
        short_signal = QLSignal(
            symbol=sym, direction="SHORT", entry_price=short_limit,
            take_profit=short_limit - target_pips * pip,
            stop_loss=short_limit + stop_pips * pip,
            session_open=session_open, trigger_pips=trigger_pips,
        )

        if self._session_stats is not None:
            self._session_stats["executions_attempted"] += 1

        if self._circuit_breaker.is_tripped:
            logger.info("[QUANTUM_LONDON] Circuit breaker tripped, skipping pendings")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            return

        account = self._connector.get_account_info()
        if not account:
            logger.error("[QUANTUM_LONDON] Cannot get account info — skipping pendings")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            return

        equity = account["equity"]
        risk_pct = cfg["risk_pct"]
        stop_distance = stop_pips * pip  # symmetric across both directions

        from hvf_trader.risk.position_sizer import calculate_lot_size
        lot_size = calculate_lot_size(
            equity=equity, risk_pct=risk_pct,
            stop_distance_price=stop_distance, symbol=sym,
            account_currency=account.get("currency", "USD"),
        )
        if lot_size <= 0:
            logger.warning("[QUANTUM_LONDON] Lot size zero, skipping pendings")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            return

        long_result = self._order_manager.place_pending_limit_order(
            symbol=sym, direction="LONG", lot_size=lot_size,
            limit_price=long_signal.entry_price,
            stop_loss=long_signal.stop_loss,
            take_profit=long_signal.take_profit,
            comment=self.PATTERN_TYPE,
        )
        short_result = self._order_manager.place_pending_limit_order(
            symbol=sym, direction="SHORT", lot_size=lot_size,
            limit_price=short_signal.entry_price,
            stop_loss=short_signal.stop_loss,
            take_profit=short_signal.take_profit,
            comment=self.PATTERN_TYPE,
        )

        if not long_result or not short_result:
            # Asymmetric failure: clean up the successful side so we don't
            # run a one-sided book that the strategy didn't intend.
            if long_result and not short_result:
                self._order_manager.cancel_pending_order(long_result["order_ticket"])
                logger.error(
                    "[QUANTUM_LONDON] SELL_LIMIT placement failed — "
                    "cancelled BUY_LIMIT %d to keep both-sided invariant",
                    long_result["order_ticket"],
                )
            elif short_result and not long_result:
                self._order_manager.cancel_pending_order(short_result["order_ticket"])
                logger.error(
                    "[QUANTUM_LONDON] BUY_LIMIT placement failed — "
                    "cancelled SELL_LIMIT %d to keep both-sided invariant",
                    short_result["order_ticket"],
                )
            else:
                logger.error("[QUANTUM_LONDON] Both LIMIT placements failed")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            if self._alerter:
                self._alerter.send_message(
                    f"<b>\u26a0\ufe0f [QUANTUM_LONDON] {sym} pendings NOT placed</b>\n"
                    f"Placement failed (long_ok={bool(long_result)}, "
                    f"short_ok={bool(short_result)}). Session skipped."
                )
            return

        self._pending_long_ticket = long_result["order_ticket"]
        self._pending_short_ticket = short_result["order_ticket"]
        self._pending_long_signal = long_signal
        self._pending_short_signal = short_signal
        self._pending_lot_size = lot_size
        self._pending_placed_at = datetime.now(timezone.utc)
        self._tracker.mark_traded()

        logger.info(
            "[QUANTUM_LONDON] %s LIMITs placed: BUY_LIMIT=%d @ %.5f "
            "(TP=%.5f SL=%.5f), SELL_LIMIT=%d @ %.5f (TP=%.5f SL=%.5f) lots=%s",
            sym,
            self._pending_long_ticket, long_signal.entry_price,
            long_signal.take_profit, long_signal.stop_loss,
            self._pending_short_ticket, short_signal.entry_price,
            short_signal.take_profit, short_signal.stop_loss,
            lot_size,
        )
        if self._alerter:
            self._alerter.send_message(
                f"<b>[QUANTUM_LONDON] {sym} LIMITs placed</b>\n"
                f"BUY_LIMIT @ {long_signal.entry_price:.5f}  "
                f"(TP {long_signal.take_profit:.5f} / SL {long_signal.stop_loss:.5f})\n"
                f"SELL_LIMIT @ {short_signal.entry_price:.5f}  "
                f"(TP {short_signal.take_profit:.5f} / SL {short_signal.stop_loss:.5f})\n"
                f"Lots: {lot_size}  Force-exit: {cfg['force_exit_utc_hour']:02d}:00 UTC"
            )

    # ─── Pending-order helpers ───────────────────────────────────────

    def _check_pending_status(self, sym, hour, force_exit_hour, cfg, pip):
        """Poll pending LIMITs for a fill (one direction); cancel the survivor
        on fill or both at force-exit."""
        if not MT5_AVAILABLE:
            return

        placed_at_ts = (
            int(self._pending_placed_at.timestamp())
            if self._pending_placed_at else 0
        )

        # Look for a filled position from either side. Filter strictly by
        # magic + comment + open_time so we never bind to a stale orphan
        # or another strategy's position.
        positions = mt5.positions_get(symbol=sym) or []
        our_position = None
        for pos in positions:
            if pos.magic != 20250305:
                continue
            if pos.comment != self.PATTERN_TYPE:
                continue
            if pos.time < placed_at_ts - 2:
                continue
            our_position = pos
            break

        if our_position is not None:
            # Identify which side filled, cancel the other.
            if our_position.type == mt5.ORDER_TYPE_BUY:
                filled_signal = self._pending_long_signal
                survivor_ticket = self._pending_short_ticket
                survivor_dir = "SHORT"
            else:
                filled_signal = self._pending_short_signal
                survivor_ticket = self._pending_long_ticket
                survivor_dir = "LONG"
            if survivor_ticket is not None:
                cancelled = self._order_manager.cancel_pending_order(survivor_ticket)
                if not cancelled:
                    logger.warning(
                        "[QUANTUM_LONDON] %s survivor %s LIMIT %d cancel failed "
                        "(may already be gone)", sym, survivor_dir, survivor_ticket,
                    )
            self._on_pending_fill(our_position, filled_signal, cfg, pip)
            return

        # No fill yet. Check both tickets — are they still pending?
        long_still = (
            self._pending_long_ticket is not None
            and bool(mt5.orders_get(ticket=self._pending_long_ticket))
        )
        short_still = (
            self._pending_short_ticket is not None
            and bool(mt5.orders_get(ticket=self._pending_short_ticket))
        )

        if not long_still and not short_still:
            # Both orders vanished without a position — rejected/expired.
            logger.warning(
                "[QUANTUM_LONDON] %s both pending orders gone with no position "
                "(L=%s S=%s). Clearing state.",
                sym, self._pending_long_ticket, self._pending_short_ticket,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[QUANTUM_LONDON] {sym} pending orders vanished</b>\n"
                    f"Both LIMITs gone, no position created."
                )
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._clear_pending_state()
            return

        if hour == force_exit_hour:
            logger.info(
                "[QUANTUM_LONDON] %s force-exit with unfilled LIMITs — cancelling both",
                sym,
            )
            self._cancel_all_pending("force_exit")
            self._reset_session_after_pending()

    def _on_pending_fill(self, position, signal, cfg, pip):
        """Limit filled into a position — log to DB and transition to monitoring."""
        lot_size = self._pending_lot_size
        sym = position.symbol
        fill_price = position.price_open
        position_ticket = position.ticket

        if self._session_stats is not None:
            self._session_stats["executions_filled"] += 1

        pattern_metadata = json.dumps({
            "session_open": signal.session_open,
            "trigger_pips": signal.trigger_pips,
            "intended_entry": signal.entry_price,
        })
        pattern_data = {
            "symbol": sym,
            "timeframe": cfg["capture_timeframe"],
            "direction": signal.direction,
            "detected_at": datetime.now(timezone.utc),
            "score": 100,
            "status": "TRIGGERED",
            "entry_price": fill_price,
            "stop_loss": signal.stop_loss,
            "target_1": signal.take_profit,
            "target_2": signal.take_profit,
            "rrr": cfg["target_pips"] / cfg["stop_pips"],
            "pattern_type": self.PATTERN_TYPE,
            "pattern_metadata": pattern_metadata,
            "h1_price": 0, "l1_price": 0, "h2_price": 0, "l2_price": 0,
            "h3_price": 0, "l3_price": 0,
            "h1_index": 0, "l1_index": 0, "h2_index": 0, "l2_index": 0,
            "h3_index": 0, "l3_index": 0,
        }
        pattern_record = self._trade_logger.log_pattern(pattern_data)

        slippage = fill_price - signal.entry_price
        slip_pips = slippage / pip
        trade_data = {
            "pattern_id": pattern_record.id,
            "symbol": sym,
            "direction": signal.direction,
            "pattern_type": self.PATTERN_TYPE,
            "mt5_ticket": position_ticket,
            "entry_price": fill_price,
            "stop_loss": signal.stop_loss,
            "target_1": signal.take_profit,
            "target_2": signal.take_profit,
            "lot_size": lot_size,
            "opened_at": datetime.now(timezone.utc),
            "status": "OPEN",
            "intended_entry": signal.entry_price,
            "intended_sl": signal.stop_loss,
            "slippage": slippage,
            "pattern_metadata": pattern_metadata,
        }
        trade_record = self._trade_logger.log_trade_open(trade_data)
        self._open_trade_id = trade_record.id
        self._clear_pending_state()

        logger.info(
            "[QUANTUM_LONDON] %s %s LIMIT FILLED: pos=%d @ %.5f "
            "(limit=%.5f slip=%+.2fp TP=%.5f SL=%.5f)",
            signal.direction, sym, position_ticket, fill_price,
            signal.entry_price, slip_pips,
            signal.take_profit, signal.stop_loss,
        )
        if self._alerter:
            self._alerter.send_message(
                f"<b>[QUANTUM_LONDON] {signal.direction} {sym} FILLED</b>\n"
                f"Entry: {fill_price:.5f} (limit {signal.entry_price:.5f}, "
                f"slip {slip_pips:+.2f}p)\n"
                f"TP: {signal.take_profit:.5f} ({cfg['target_pips']:.0f}p)  "
                f"SL: {signal.stop_loss:.5f} ({cfg['stop_pips']:.0f}p)\n"
                f"Lots: {lot_size}"
            )

    def _cancel_all_pending(self, reason):
        """Cancel any still-active pending LIMITs and clear state."""
        cancelled_any = False
        for ticket, label in (
            (self._pending_long_ticket, "BUY_LIMIT"),
            (self._pending_short_ticket, "SELL_LIMIT"),
        ):
            if ticket is None:
                continue
            ok = self._order_manager.cancel_pending_order(ticket)
            if ok:
                logger.info(
                    "[QUANTUM_LONDON] %s %d cancelled (%s)",
                    label, ticket, reason,
                )
                cancelled_any = True
            else:
                logger.warning(
                    "[QUANTUM_LONDON] Cancel failed for %s %d — may already "
                    "be filled/expired", label, ticket,
                )
        if cancelled_any and self._alerter:
            sym = (
                (self._pending_long_signal and self._pending_long_signal.symbol)
                or (self._pending_short_signal and self._pending_short_signal.symbol)
                or "?"
            )
            self._alerter.send_message(
                f"<b>[QUANTUM_LONDON] {sym} pending LIMITs cancelled</b>\n"
                f"Reason: {reason}"
            )
        if self._session_stats is not None:
            self._session_stats["executions_failed"] += 1
        self._clear_pending_state()

    def _clear_pending_state(self):
        self._pending_long_ticket = None
        self._pending_short_ticket = None
        self._pending_long_signal = None
        self._pending_short_signal = None
        self._pending_lot_size = None
        self._pending_placed_at = None

    def _cleanup_stale_pendings_on_startup(self):
        """Cancel any QL pending orders in the broker book at process start.

        Required because pending state lives only in process memory — a
        restart loses the tickets. Stale pendings could fill while the bot
        is blind to them, creating a ghost position.
        """
        if not MT5_AVAILABLE:
            return
        sym = self._cfg["instrument"]
        try:
            orders = mt5.orders_get(symbol=sym) or []
        except Exception as e:
            logger.warning(
                "[QUANTUM_LONDON] startup-cleanup: orders_get failed: %s", e,
            )
            return
        cancelled = 0
        for o in orders:
            if o.magic != 20250305:
                continue
            if o.comment != self.PATTERN_TYPE:
                continue
            if self._order_manager.cancel_pending_order(o.ticket):
                cancelled += 1
                logger.info(
                    "[QUANTUM_LONDON] startup-cleanup: cancelled stale pending "
                    "ticket=%d type=%s @ %.5f", o.ticket, o.type, o.price_open,
                )
        if cancelled and self._alerter:
            self._alerter.send_message(
                f"<b>[QUANTUM_LONDON] {sym} startup cleanup</b>\n"
                f"Cancelled {cancelled} stale pending order(s) from prior session."
            )

    def _reset_session_after_pending(self):
        """Mirror the force-exit reset path used in _tick."""
        if self._tracker.state == "TRADING":
            self._emit_session_summary()
        if self._tracker.state != "IDLE":
            self._tracker.reset()
            self._session_stats = None

    # ─── Trade-monitor helpers ───────────────────────────────────────

    def _check_if_closed(self):
        """Detect broker-side TP/SL fills, log close with deal-history PnL."""
        if not MT5_AVAILABLE or self._open_trade_id is None:
            return
        from hvf_trader.database.models import TradeRecord
        trade = self._trade_logger._session.get(TradeRecord, self._open_trade_id)
        if not trade or trade.status == "CLOSED":
            self._open_trade_id = None
            return
        positions = mt5.positions_get(ticket=trade.mt5_ticket)
        if positions and len(positions) > 0:
            return  # still open
        # Position gone — find close deal
        from hvf_trader.execution.deal_utils import search_deal_history, find_close_deal
        deals = search_deal_history(trade.mt5_ticket, trade.symbol)
        close_deal = find_close_deal(
            deals, trade.mt5_ticket, trade.symbol, trade.direction, trade.opened_at,
        )
        pip = config.PIP_VALUES.get(trade.symbol, 0.0001)
        if close_deal:
            close_price = close_deal.price
            pnl = close_deal.profit
            if trade.direction == "LONG":
                pnl_pips = (close_price - trade.entry_price) / pip
            else:
                pnl_pips = (trade.entry_price - close_price) / pip
            reason = "TAKE_PROFIT" if pnl > 0 else "STOP_LOSS"
            self._trade_logger.log_trade_close(
                trade.id, close_price, pnl, pnl_pips, reason,
            )
            logger.info(
                "[QUANTUM_LONDON] Trade closed: %s, PnL=$%+.2f (%+.1fp)",
                reason, pnl, pnl_pips,
            )
            if self._alerter:
                emoji = "\u2705" if pnl > 0 else "\u274c"
                self._alerter.send_message(
                    f"<b>{emoji} [QUANTUM_LONDON] {reason}</b>\n"
                    f"{trade.symbol} {trade.direction}\n"
                    f"Close: {close_price:.5f}\n"
                    f"PnL: ${pnl:+.2f} ({pnl_pips:+.1f}p)"
                )
            self._open_trade_id = None

    def _force_exit_open_trade(self):
        """Force-close any still-open trade at the 21:00 UTC session end."""
        if self._open_trade_id is None:
            return
        from hvf_trader.database.models import TradeRecord
        trade = self._trade_logger._session.get(TradeRecord, self._open_trade_id)
        if not trade or trade.status == "CLOSED":
            self._open_trade_id = None
            return
        result = self._order_manager.close_position(
            trade.mt5_ticket, trade.symbol, trade.direction, "QL force_exit",
        )
        pip = config.PIP_VALUES.get(trade.symbol, 0.0001)
        if result:
            close_price = result["fill_price"] if isinstance(result, dict) else trade.entry_price
            if trade.direction == "LONG":
                pnl_pips = (close_price - trade.entry_price) / pip
            else:
                pnl_pips = (trade.entry_price - close_price) / pip
            pnl = result.get("profit", pnl_pips * 10.0 * trade.lot_size) if isinstance(result, dict) else (pnl_pips * 10.0 * trade.lot_size)
            self._trade_logger.log_trade_close(
                trade.id, close_price, pnl, pnl_pips, "TIME_EXIT",
            )
            logger.info(
                "[QUANTUM_LONDON] Force-exit: %s %s @ %.5f, PnL=$%+.2f (%+.1fp)",
                trade.symbol, trade.direction, close_price, pnl, pnl_pips,
            )
            if self._alerter:
                emoji = "\u2705" if pnl > 0 else "\u274c"
                self._alerter.send_message(
                    f"<b>{emoji} [QUANTUM_LONDON] TIME_EXIT</b>\n"
                    f"{trade.symbol} {trade.direction}\n"
                    f"Close: {close_price:.5f}  PnL: ${pnl:+.2f} ({pnl_pips:+.1f}p)"
                )
        self._open_trade_id = None

    def _emit_session_summary(self):
        """Log + alert end-of-session telemetry."""
        if self._session_stats is None:
            return
        s = self._session_stats
        cfg = self._cfg
        trig = cfg["trigger_pips"]
        ex_attempted = s["executions_attempted"]
        ex_filled = s["executions_filled"]
        ex_failed = s["executions_failed"]
        logger.info(
            "[QUANTUM_LONDON] SESSION SUMMARY date=%s open=%.5f polls=%d "
            "range=(below %.1fp / above %.1fp) trigger=%.0fp "
            "crosses(L/S)=%d/%d execution(att/fill/fail)=%d/%d/%d",
            s["date"], s["session_open"], s["polls"],
            s["max_below_pips"], s["max_above_pips"], trig,
            s["trigger_crosses_long"], s["trigger_crosses_short"],
            ex_attempted, ex_filled, ex_failed,
        )
        # Telegram only when something interesting happened
        if self._alerter and (ex_attempted > 0 or s["trigger_crosses_long"]
                              or s["trigger_crosses_short"]):
            if ex_filled > 0:
                headline = "Order filled"
            elif ex_failed > 0:
                headline = "Execution failed"
            else:
                headline = "Setup not actioned"
            self._alerter.send_message(
                f"<b>[QUANTUM_LONDON] Session ended — {headline}</b>\n"
                f"Open: {s['session_open']:.5f}  trigger: {trig:.0f}p\n"
                f"Range: -{s['max_below_pips']:.1f}p / +{s['max_above_pips']:.1f}p\n"
                f"Crosses (L/S): {s['trigger_crosses_long']}/{s['trigger_crosses_short']}\n"
                f"Execution: att={ex_attempted} fill={ex_filled} fail={ex_failed}"
            )
