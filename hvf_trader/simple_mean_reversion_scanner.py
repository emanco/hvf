"""Simple Mean Reversion scanner thread.

Faithful FF thread #743125 implementation. Captures daily open at 22:00 UTC,
trades 22:00 UTC capture-day → 21:00 UTC next-day (≈22h cycle), wide trigger,
narrow TP, no filters. One trade per session.

Notes:
- Entry uses LIMIT order at the exact trigger price (not market at ask/bid).
  This was the killer bug in the old QL implementation: entering at broker
  ask shifted TP further away by the spread, halving the win probability.
- No news filter, no spread filter, no range filter — per FF community
  consensus that filters degrade results on this strategy.
- Force-exit at 21:00 UTC fires for any still-open trade.
"""
import json
import logging
import time
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.detector.simple_mean_reversion import SMRTracker
from hvf_trader.data.data_fetcher import fetch_and_prepare

logger = logging.getLogger("hvf_trader")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


class SimpleMeanReversionScanner:
    """Dedicated scanner thread for the SMR strategy."""

    PATTERN_TYPE = "SIMPLE_MEAN_REVERSION"

    def __init__(self, order_manager, trade_logger, risk_manager,
                 circuit_breaker, connector, alerter, cfg=None):
        self._tracker = SMRTracker()
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._connector = connector
        self._alerter = alerter
        self._running = False
        self._open_trade_id = None
        self._cfg = cfg or config.SIMPLE_MEAN_REVERSION
        self._session_stats: dict | None = None
        self._last_telemetry_log_hour: int | None = None

    # ─── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        self._running = True
        poll = self._cfg["poll_interval_sec"]
        hb_every = max(1, int(60 / poll))
        logger.info(
            "[SMR] Scanner thread started (poll=%ds, heartbeat every %d iters)",
            poll, hb_every,
        )
        iter_count = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[SMR] Scanner error: %s", e, exc_info=True)
            iter_count += 1
            if iter_count % hb_every == 0:
                logger.info(
                    "[SMR] heartbeat: iter=%d state=%s open_trade=%s",
                    iter_count, self._tracker.state, self._open_trade_id,
                )
            time.sleep(poll)
        logger.info("[SMR] Scanner thread stopped")

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
                logger.warning("[SMR] Could not fetch capture bar")
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
                "[SMR] Daily open captured: %.5f, date=%s, hold until %02d:00 UTC",
                session_open, now.date(), force_exit_hour,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[SMR] Daily open captured</b>\n"
                    f"{sym}: {session_open:.5f}\n"
                    f"Date: {now.date()}\n"
                    f"Trigger: ±{cfg['trigger_pips']:.0f}p\n"
                    f"TP/SL: {cfg['target_pips']:.0f}p / {cfg['stop_pips']:.0f}p\n"
                    f"Force-exit: {force_exit_hour:02d}:00 UTC"
                )
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
                    "[SMR] @%02d:00 UTC polls=%d max_below=%.1fp max_above=%.1fp "
                    "crosses(L/S)=%d/%d",
                    hour, s["polls"], s["max_below_pips"], s["max_above_pips"],
                    s["trigger_crosses_long"], s["trigger_crosses_short"],
                )

        # Trigger check
        signal = self._tracker.check_trigger(
            bid=tick.bid, ask=tick.ask, pip_value=pip,
            trigger_pips=cfg["trigger_pips"],
            target_pips=cfg["target_pips"],
            stop_pips=cfg["stop_pips"],
            symbol=sym,
        )
        if signal:
            self._execute(signal)

    # ─── Execution ───────────────────────────────────────────────────

    def _execute(self, signal):
        cfg = self._cfg
        sym = signal.symbol
        if self._session_stats is not None:
            self._session_stats["executions_attempted"] += 1

        if self._circuit_breaker.is_tripped:
            logger.info("[SMR] Circuit breaker tripped, skipping entry")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            return

        account = self._connector.get_account_info()
        if not account:
            logger.error("[SMR] Cannot get account info")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            return

        equity = account["equity"]
        risk_pct = cfg["risk_pct"]
        stop_distance = abs(signal.entry_price - signal.stop_loss)

        from hvf_trader.risk.position_sizer import calculate_lot_size
        lot_size = calculate_lot_size(
            equity=equity, risk_pct=risk_pct,
            stop_distance_price=stop_distance, symbol=sym,
            account_currency=account.get("currency", "USD"),
        )
        if lot_size <= 0:
            logger.warning("[SMR] Lot size zero, skipping")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            return

        # CRITICAL: limit_price = signal.entry_price ensures we fill AT the
        # trigger or not at all. If price has already drifted past the trigger
        # by the time the order request reaches the broker, MT5 returns
        # REQUOTE and we skip — this is correct behavior, mirrors the
        # backtest assumption. See order_manager.place_market_order docs.
        result = self._order_manager.place_market_order(
            symbol=sym, direction=signal.direction, lot_size=lot_size,
            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            comment=self.PATTERN_TYPE,
            limit_price=signal.entry_price,
        )

        if not result:
            logger.error("[SMR] Order placement failed (likely REQUOTE — price drifted past trigger)")
            if self._session_stats is not None:
                self._session_stats["executions_failed"] += 1
            self._tracker.mark_traded()
            return

        if self._session_stats is not None:
            self._session_stats["executions_filled"] += 1

        ticket = result["ticket"]
        fill_price = result["fill_price"]

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
        trade_data = {
            "pattern_id": pattern_record.id,
            "symbol": sym,
            "direction": signal.direction,
            "pattern_type": self.PATTERN_TYPE,
            "mt5_ticket": ticket,
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
        self._tracker.mark_traded()

        logger.info(
            "[SMR] %s %s: trigger=%.5f fill=%.5f TP=%.5f SL=%.5f lots=%s slip=%.1fp",
            signal.direction, sym, signal.entry_price, fill_price,
            signal.take_profit, signal.stop_loss, lot_size,
            slippage / config.PIP_VALUES.get(sym, 0.0001),
        )
        if self._alerter:
            self._alerter.send_message(
                f"<b>[SMR] {signal.direction} {sym}</b>\n"
                f"Entry: {fill_price:.5f} (trigger {signal.entry_price:.5f})\n"
                f"TP: {signal.take_profit:.5f} ({cfg['target_pips']:.0f}p)\n"
                f"SL: {signal.stop_loss:.5f} ({cfg['stop_pips']:.0f}p)\n"
                f"Lots: {lot_size}"
            )

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
                "[SMR] Trade closed: %s, PnL=$%+.2f (%+.1fp)",
                reason, pnl, pnl_pips,
            )
            if self._alerter:
                emoji = "\u2705" if pnl > 0 else "\u274c"
                self._alerter.send_message(
                    f"<b>{emoji} [SMR] {reason}</b>\n"
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
            trade.mt5_ticket, trade.symbol, trade.direction, "SMR force_exit",
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
                "[SMR] Force-exit: %s %s @ %.5f, PnL=$%+.2f (%+.1fp)",
                trade.symbol, trade.direction, close_price, pnl, pnl_pips,
            )
            if self._alerter:
                emoji = "\u2705" if pnl > 0 else "\u274c"
                self._alerter.send_message(
                    f"<b>{emoji} [SMR] TIME_EXIT</b>\n"
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
            "[SMR] SESSION SUMMARY date=%s open=%.5f polls=%d "
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
                f"<b>[SMR] Session ended — {headline}</b>\n"
                f"Open: {s['session_open']:.5f}  trigger: {trig:.0f}p\n"
                f"Range: -{s['max_below_pips']:.1f}p / +{s['max_above_pips']:.1f}p\n"
                f"Crosses (L/S): {s['trigger_crosses_long']}/{s['trigger_crosses_short']}\n"
                f"Execution: att={ex_attempted} fill={ex_filled} fail={ex_failed}"
            )
