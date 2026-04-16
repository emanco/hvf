"""
Asian Gravity scanner thread.

Runs as a daemon thread alongside the main KZ Hunt scanner.
Active only during Asian session (00:00-06:00 UTC) on configured days.

Formation (00:00-02:00): Uses M15 bars to measure range.
Trading (02:00-06:00): Polls live ticks every 30s for trigger detection.
Execution: TP and SL set on MT5 order (broker-side tick-level fills).
"""

import json
import logging
import time
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.detector.asian_gravity import AsianGravityTracker
from hvf_trader.data.data_fetcher import fetch_and_prepare

logger = logging.getLogger("hvf_trader")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


class AsianGravityScanner:
    """Dedicated scanner for the Asian Gravity strategy."""

    def __init__(self, order_manager, trade_logger, risk_manager,
                 circuit_breaker, connector, alerter, cfg=None):
        self._tracker = AsianGravityTracker()
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._connector = connector
        self._alerter = alerter
        self._running = False
        self._open_trade_id = None
        self._cfg = cfg or config.ASIAN_GRAVITY
        self._pattern_type = self._cfg.get("pattern_type", "ASIAN_GRAVITY")
        self._daily_open_captured = False

    def start(self):
        """Main loop. Runs until stop() is called."""
        self._running = True
        logger.info("[%s] Scanner thread started", self._pattern_type)

        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[%s] Scanner error: %s", self._pattern_type, e, exc_info=True)
            time.sleep(self._cfg["poll_interval_sec"])

        logger.info("[%s] Scanner thread stopped", self._pattern_type)

    def stop(self):
        self._running = False

    # ─── Core Loop ────────────────────────────────────────────────────

    def _tick(self):
        now = datetime.now(timezone.utc)
        hour = now.hour
        weekday = now.weekday()

        cfg = self._cfg
        sym = cfg["instrument"]
        pip = config.PIP_VALUES.get(sym, 0.0001)
        pt = self._pattern_type

        daily_open_hour = cfg.get("daily_open_utc_hour")  # None for Asian Gravity, 22 for QL
        trading_start = cfg.get("trading_start_utc", cfg.get("formation_end_utc", 2))
        forced_exit = cfg["forced_exit_utc"]

        # ─── Capture daily open at 22:00 UTC (Quantum London mode) ───

        if daily_open_hour is not None:
            if hour == daily_open_hour and not self._daily_open_captured:
                df = fetch_and_prepare(sym, cfg["formation_timeframe"], bars=5)
                if df is not None and not df.empty:
                    bar = df.iloc[-1]
                    self._tracker.start_session(
                        bar_open=bar["open"], bar_high=bar["high"],
                        bar_low=bar["low"], date=str(now.date()),
                    )
                    # Skip formation — go straight to trading
                    self._tracker.finalize_formation(pip, cfg["max_range_pips"])
                    self._daily_open_captured = True
                    logger.info(
                        "[%s] Daily open captured: %.5f, date=%s",
                        pt, bar["open"], now.date())

                    # News filter
                    from hvf_trader.data.news_filter import has_high_impact_same_day
                    if has_high_impact_same_day(sym):
                        self._tracker.state = "DONE"
                        logger.info("[%s] Session skipped: high-impact event today", pt)
                        return
                return

            # Between daily open capture (22:00) and trading start (00:00): wait
            if hour > daily_open_hour or hour < trading_start:
                if hour >= forced_exit and hour < daily_open_hour:
                    # After exit, before next open: reset
                    if self._tracker.state != "IDLE":
                        self._force_exit_if_open()
                        self._tracker.reset()
                        self._daily_open_captured = False
                return

            # Day filter (check the trading day, not the open day)
            if weekday not in cfg["days"]:
                return

            # Force exit
            if hour >= forced_exit:
                self._force_exit_if_open()
                self._tracker.state = "DONE"
                return

        else:
            # ─── Original Asian Gravity mode (00:00 UTC session open) ──

            # Outside session
            if hour >= forced_exit or hour < cfg["formation_start_utc"]:
                if self._tracker.state not in ("IDLE", "DONE"):
                    self._force_exit_if_open()
                    self._tracker.state = "DONE"
                if hour >= forced_exit and self._tracker.state == "DONE":
                    self._tracker.reset()
                return

            # Day filter
            if weekday not in cfg["days"]:
                return

            # Formation phase
            if hour < cfg.get("formation_end_utc", 2):
                if self._tracker.state == "IDLE":
                    df = fetch_and_prepare(sym, cfg["formation_timeframe"], bars=5)
                    if df is None or df.empty:
                        return
                    bar = df.iloc[-1]
                    self._tracker.start_session(
                        bar_open=bar["open"], bar_high=bar["high"],
                        bar_low=bar["low"], date=str(now.date()),
                    )
                    logger.info("[%s] Formation started: open=%.5f, date=%s",
                                pt, bar["open"], now.date())
                elif self._tracker.state == "FORMING":
                    df = fetch_and_prepare(sym, cfg["formation_timeframe"], bars=5)
                    if df is not None and not df.empty:
                        bar = df.iloc[-1]
                        self._tracker.update_formation(bar["high"], bar["low"])
                return

            # Transition: formation -> trading
            if self._tracker.state == "FORMING":
                self._tracker.finalize_formation(pip, cfg["max_range_pips"])
                if self._tracker.state == "DONE":
                    if self._alerter:
                        self._alerter.send_message(
                            "<b>[{}]</b> Session skipped\n"
                            "Range: {:.1f} pips (max: {})".format(
                                pt, self._tracker.range_pips, cfg["max_range_pips"]))
                    return

                from hvf_trader.data.news_filter import has_high_impact_same_day
                if has_high_impact_same_day(sym):
                    self._tracker.state = "DONE"
                    logger.info("[%s] Session skipped: high-impact event today", pt)
                    if self._alerter:
                        self._alerter.send_message(
                            "<b>[{}]</b> Session skipped\n"
                            "High-impact event scheduled today".format(pt))
                    return

        # ─── Trading phase (02:00 - 06:00) ───────────────────────────

        if self._tracker.state != "TRADING":
            return

        # Force exit check (06:00)
        if hour >= cfg["forced_exit_utc"]:
            self._force_exit_if_open()
            self._tracker.state = "DONE"
            return

        # If we already have an open trade, just monitor for time exit
        if self._open_trade_id:
            # TP and SL are broker-side — nothing to do until 06:00
            # But check if position was closed by broker (TP/SL hit)
            self._check_if_closed()
            return

        # ─── Entry detection via live tick ────────────────────────────

        if not MT5_AVAILABLE:
            return

        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return

        signal = self._tracker.check_trigger(
            bid=tick.bid, ask=tick.ask, pip_value=pip,
            trigger_pips=cfg["trigger_pips"],
            target_pips=cfg["target_pips"],
            stop_pips=cfg["stop_pips"],
            max_spread_pips=cfg["max_spread_pips"],
            symbol=sym,
            direction=cfg["direction"],
        )

        if signal:
            self._execute(signal)

    # ─── Execution ────────────────────────────────────────────────────

    def _execute(self, signal):
        """Execute an entry with broker-side TP and SL."""
        cfg = self._cfg
        sym = signal.symbol
        pt = self._pattern_type

        # Circuit breaker check
        if self._circuit_breaker.is_tripped:
            logger.info("[%s] Circuit breaker tripped, skipping entry", pt)
            self._tracker.mark_traded()
            return

        # Position sizing
        account = self._connector.get_account_info()
        if not account:
            logger.error("[%s] Cannot get account info", pt)
            return

        equity = account["equity"]
        risk_pct = cfg["risk_pct"]
        stop_distance = cfg["stop_pips"] * config.PIP_VALUES.get(sym, 0.0001)

        from hvf_trader.risk.position_sizer import calculate_lot_size
        lot_size = calculate_lot_size(
            equity=equity, risk_pct=risk_pct,
            stop_distance_price=stop_distance, symbol=sym,
            account_currency=account.get("currency", "USD"),
        )

        if lot_size <= 0:
            logger.warning("[%s] Lot size zero, skipping", pt)
            self._tracker.mark_traded()
            return

        # Place order with TP and SL on MT5
        result = self._order_manager.place_market_order(
            symbol=sym, direction=signal.direction, lot_size=lot_size,
            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            comment=self._pattern_type,
        )

        if not result:
            logger.error("[%s] Order placement failed", pt)
            self._tracker.mark_traded()
            return

        ticket = result["ticket"]
        fill_price = result["fill_price"]

        # Log pattern
        pattern_metadata = json.dumps({
            "session_open": signal.session_open,
            "session_range_pips": signal.session_range_pips,
            "trigger_pips": signal.trigger_pips,
            "spread_pips": signal.spread_pips,
        })

        pattern_data = {
            "symbol": sym,
            "timeframe": cfg["formation_timeframe"],
            "direction": signal.direction,
            "detected_at": datetime.now(timezone.utc),
            "score": 100,  # gravity signal, no scoring
            "status": "TRIGGERED",
            "entry_price": fill_price,
            "stop_loss": signal.stop_loss,
            "target_1": signal.take_profit,
            "target_2": signal.take_profit,
            "rrr": cfg["target_pips"] / cfg["stop_pips"],
            "pattern_type": self._pattern_type,
            "pattern_metadata": pattern_metadata,
            "h1_price": 0, "l1_price": 0,
            "h2_price": 0, "l2_price": 0,
            "h3_price": 0, "l3_price": 0,
            "h1_index": 0, "l1_index": 0,
            "h2_index": 0, "l2_index": 0,
            "h3_index": 0, "l3_index": 0,
        }
        pattern_record = self._trade_logger.log_pattern(pattern_data)

        # Log trade
        slippage = fill_price - signal.entry_price
        trade_data = {
            "pattern_id": pattern_record.id,
            "symbol": sym,
            "direction": signal.direction,
            "pattern_type": self._pattern_type,
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
            f"[{pt}] {signal.direction} {sym}: fill={fill_price:.5f}, "
            f"TP={signal.take_profit:.5f}, SL={signal.stop_loss:.5f}, "
            f"lots={lot_size}, spread={signal.spread_pips:.1f}p"
        )

        if self._alerter:
            self._alerter.send_message(
                f"<b>[{pt}] {signal.direction} {sym}</b>\n"
                f"Entry: {fill_price:.5f}\n"
                f"TP: {signal.take_profit:.5f} (+{cfg['target_pips']}p)\n"
                f"SL: {signal.stop_loss:.5f} (-{cfg['stop_pips']}p)\n"
                f"Lots: {lot_size}\n"
                f"Session range: {signal.session_range_pips:.1f}p\n"
                f"Spread: {signal.spread_pips:.1f}p"
            )

    # ─── Trade Monitoring ─────────────────────────────────────────────

    def _check_if_closed(self):
        """Check if broker closed the trade (TP or SL hit)."""
        pt = self._pattern_type
        if not self._open_trade_id or not MT5_AVAILABLE:
            return

        trade = self._trade_logger._session.get(
            __import__("hvf_trader.database.models", fromlist=["TradeRecord"]).TradeRecord,
            self._open_trade_id,
        )
        if not trade or trade.status == "CLOSED":
            self._open_trade_id = None
            return

        # Check if MT5 position still exists
        ticket = trade.mt5_ticket
        positions = mt5.positions_get(ticket=ticket)
        if positions and len(positions) > 0:
            return  # Still open

        # Position gone — broker closed it (TP or SL)
        from hvf_trader.execution.deal_utils import search_deal_history, find_close_deal

        deals = search_deal_history(ticket, trade.symbol)
        close_deal = find_close_deal(
            deals, ticket, trade.symbol, trade.direction, trade.opened_at,
        )

        if close_deal:
            close_price = close_deal.price
            pnl = close_deal.profit
            pip_value = config.PIP_VALUES.get(trade.symbol, 0.0001)
            if trade.direction == "LONG":
                pnl_pips = (close_price - trade.entry_price) / pip_value
            else:
                pnl_pips = (trade.entry_price - close_price) / pip_value
            reason = "TAKE_PROFIT" if pnl > 0 else "STOP_LOSS"
        else:
            # Estimate from TP/SL levels
            close_price = trade.target_1  # assume TP hit (most likely)
            pip_value = config.PIP_VALUES.get(trade.symbol, 0.0001)
            if trade.direction == "LONG":
                pnl_pips = (close_price - trade.entry_price) / pip_value
            else:
                pnl_pips = (trade.entry_price - close_price) / pip_value
            pnl = pnl_pips * 10.0 * trade.lot_size  # approximate
            reason = "TAKE_PROFIT"

        self._trade_logger.log_trade_close(
            trade.id, close_price, pnl, pnl_pips, reason,
            pnl_estimated=close_deal is None,
        )

        logger.info(
            f"[{pt}] Trade closed: {reason}, "
            f"PnL={pnl:.2f} ({pnl_pips:+.1f} pips)"
        )

        if self._alerter:
            emoji = "\u2705" if pnl > 0 else "\u274C"
            self._alerter.send_message(
                f"<b>{emoji} [{pt}] {reason}</b>\n"
                f"Close: {close_price:.5f}\n"
                f"PnL: {pnl:+.2f} ({pnl_pips:+.1f} pips)"
            )

        self._open_trade_id = None

    def _force_exit_if_open(self):
        """Force close any open trade at session end."""
        pt = self._pattern_type
        if not self._open_trade_id:
            return

        trade = self._trade_logger._session.get(
            __import__("hvf_trader.database.models", fromlist=["TradeRecord"]).TradeRecord,
            self._open_trade_id,
        )
        if not trade or trade.status == "CLOSED":
            self._open_trade_id = None
            return

        ticket = trade.mt5_ticket
        result = self._order_manager.close_position(
            ticket, trade.symbol, trade.direction, "{} time_exit".format(pt)
        )

        if result:
            close_price = result["fill_price"] if isinstance(result, dict) else 0
            pip_value = config.PIP_VALUES.get(trade.symbol, 0.0001)
            if trade.direction == "LONG":
                pnl_pips = (close_price - trade.entry_price) / pip_value
            else:
                pnl_pips = (trade.entry_price - close_price) / pip_value

            # Get actual PnL from position profit
            pnl = result.get("profit", pnl_pips * 10.0 * trade.lot_size) if isinstance(result, dict) else 0

            self._trade_logger.log_trade_close(
                trade.id, close_price, pnl, pnl_pips, "TIME_EXIT"
            )

            logger.info(
                f"[{pt}] Time exit: {pnl_pips:+.1f} pips, PnL={pnl:+.2f}"
            )

            if self._alerter:
                emoji = "\u2705" if pnl > 0 else "\u274C"
                self._alerter.send_message(
                    f"<b>{emoji} [{pt}] TIME EXIT</b>\n"
                    f"Close: {close_price:.5f}\n"
                    f"PnL: {pnl:+.2f} ({pnl_pips:+.1f} pips)"
                )
        else:
            logger.error(f"[{pt}] Failed to close position {ticket}")

        self._open_trade_id = None
