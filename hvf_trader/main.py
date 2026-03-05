"""
HVF Auto-Trader Orchestrator
3 threads: scanner, trade monitor, health check
Graceful shutdown on SIGINT/SIGTERM
"""

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.database.models import init_db, get_engine, get_session
from hvf_trader.database.trade_logger import TradeLogger, setup_file_logging
from hvf_trader.execution.mt5_connector import MT5Connector
from hvf_trader.execution.order_manager import OrderManager
from hvf_trader.execution.trade_monitor import TradeMonitor
from hvf_trader.monitoring.health_check import HealthChecker
from hvf_trader.monitoring.reconciliation import Reconciliator
from hvf_trader.alerts.telegram_bot import TelegramAlerter
from hvf_trader.detector.zigzag import compute_zigzag
from hvf_trader.detector.hvf_detector import detect_hvf_patterns, check_entry_confirmation
from hvf_trader.detector.pattern_scorer import score_pattern
from hvf_trader.data.data_fetcher import fetch_and_prepare, get_volume_average
from hvf_trader.data.news_filter import has_upcoming_news
from hvf_trader.risk.risk_manager import RiskManager
from hvf_trader.risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger("hvf_trader")


class HVFTrader:
    def __init__(self):
        # ─── Logging ─────────────────────────────────────────────────────
        setup_file_logging()
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # ─── Database ────────────────────────────────────────────────────
        self.engine = get_engine()
        init_db(self.engine)
        self.trade_logger = TradeLogger()

        # ─── MT5 ─────────────────────────────────────────────────────────
        self.connector = MT5Connector()
        self.order_manager = OrderManager(connector=self.connector)

        # ─── Risk ────────────────────────────────────────────────────────
        self.circuit_breaker = CircuitBreaker(trade_logger=self.trade_logger)
        self.risk_manager = RiskManager(
            circuit_breaker=self.circuit_breaker,
            trade_logger=self.trade_logger,
        )

        # ─── Trade Monitor ───────────────────────────────────────────────
        self.trade_monitor = TradeMonitor(
            order_manager=self.order_manager,
            trade_logger=self.trade_logger,
            connector=self.connector,
        )

        # ─── Health Check ────────────────────────────────────────────────
        self.health_checker = HealthChecker(
            connector=self.connector,
            trade_logger=self.trade_logger,
            order_manager=self.order_manager,
        )

        # ─── Reconciliation ──────────────────────────────────────────────
        self.reconciliator = Reconciliator(
            trade_logger=self.trade_logger,
            order_manager=self.order_manager,
        )

        # ─── Alerts ──────────────────────────────────────────────────────
        self.alerter = TelegramAlerter()

        # ─── State ───────────────────────────────────────────────────────
        self._running = False
        self._armed_patterns = []  # In-memory list of armed patterns
        self._last_scan_bar = {}   # symbol -> last bar timestamp scanned
        self._last_reconcile = None
        self._last_daily_summary = None

    def start(self):
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info("HVF Auto-Trader starting...")
        logger.info(f"Environment: {config.ENVIRONMENT}")
        logger.info(f"Instruments: {config.INSTRUMENTS}")
        logger.info(f"Risk: {config.RISK_PCT}% per trade")
        logger.info("=" * 60)

        # Connect to MT5
        if not self.connector.connect():
            logger.error("Failed to connect to MT5. Exiting.")
            return

        account = self.connector.get_account_info()
        if account:
            logger.info(
                f"Account: balance={account['balance']:.2f}, "
                f"equity={account['equity']:.2f}"
            )

        self.trade_logger.log_event("STARTUP", details=f"Environment={config.ENVIRONMENT}")

        # Load armed patterns from DB
        self._armed_patterns = self.trade_logger.get_armed_patterns()
        logger.info(f"Loaded {len(self._armed_patterns)} armed patterns from DB")

        # Start threads
        self._running = True

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start health checker (daemon thread)
        self.health_checker.start()

        # Start trade monitor (daemon thread)
        monitor_thread = threading.Thread(
            target=self.trade_monitor.start, daemon=True
        )
        monitor_thread.start()

        # Notify
        self.alerter.alert_startup()

        # Main scanner loop (runs on main thread)
        logger.info("Starting scanner loop...")
        self._scanner_loop()

    def _scanner_loop(self):
        """
        Main loop: runs every 60 seconds, checks for new 1H candle closes.
        On new candle: scan → detect → score → arm → check entry
        """
        while self._running:
            try:
                now = datetime.now(timezone.utc)

                # Scanner: check each instrument for new patterns
                for symbol in config.INSTRUMENTS:
                    self._scan_instrument(symbol)

                # Entry monitor: check armed patterns for confirmation
                self._check_armed_patterns()

                # Reconciliation (every 60s)
                if (
                    self._last_reconcile is None
                    or (now - self._last_reconcile).total_seconds() >= 60
                ):
                    self.reconciliator.reconcile()
                    self._last_reconcile = now

                # Circuit breaker update (after any trade closes)
                account = self.connector.get_account_info()
                if account:
                    self.circuit_breaker.update(account["balance"])
                    # Log equity snapshot every cycle
                    self.trade_logger.log_equity_snapshot(
                        balance=account["balance"],
                        equity=account["equity"],
                        free_margin=account["free_margin"],
                        margin_used=account.get("margin", 0),
                        open_positions=len(self.trade_logger.get_open_trades()),
                        daily_pnl=self.trade_logger.get_daily_pnl(),
                        weekly_pnl=self.trade_logger.get_weekly_pnl(),
                        monthly_pnl=self.trade_logger.get_monthly_pnl(),
                    )

                # Daily summary at 21:00 UTC (after NY close)
                if now.hour == 21 and (
                    self._last_daily_summary is None
                    or self._last_daily_summary.date() < now.date()
                ):
                    self.alerter.send_daily_summary(self.trade_logger)
                    self._last_daily_summary = now

            except Exception as e:
                logger.error(f"Scanner loop error: {e}", exc_info=True)
                self.trade_logger.log_event(
                    "ERROR", details=f"Scanner: {e}", severity="ERROR"
                )

            # Sleep until next cycle (60 seconds)
            time.sleep(60)

    def _scan_instrument(self, symbol: str):
        """Scan a single instrument for new HVF patterns."""
        # Fetch 1H data
        df_1h = fetch_and_prepare(symbol, config.PRIMARY_TIMEFRAME, bars=500)
        if df_1h is None or df_1h.empty:
            return

        # Check if we have a new bar
        latest_time = df_1h["time"].iloc[-1]
        last_scanned = self._last_scan_bar.get(symbol)
        if last_scanned is not None and latest_time <= last_scanned:
            return  # No new bar

        self._last_scan_bar[symbol] = latest_time

        # Fetch 4H data for multi-TF confirmation
        df_4h = fetch_and_prepare(symbol, config.CONFIRMATION_TIMEFRAME, bars=200)

        # Run zigzag
        pivots = compute_zigzag(df_1h, config.ZIGZAG_ATR_MULTIPLIER)
        if len(pivots) < 6:
            return

        # Detect patterns
        patterns = detect_hvf_patterns(
            df=df_1h,
            symbol=symbol,
            timeframe=config.PRIMARY_TIMEFRAME,
            pivots=pivots,
            df_4h=df_4h,
        )

        for pattern in patterns:
            # Score
            score = score_pattern(pattern, df_1h, df_4h)
            pattern.score = score

            if score >= config.SCORE_THRESHOLD:
                pattern.status = "ARMED"
                pattern.detected_at = datetime.now(timezone.utc)

                # Log to DB
                pattern_record = self.trade_logger.log_pattern({
                    "symbol": pattern.symbol,
                    "timeframe": pattern.timeframe,
                    "direction": pattern.direction,
                    "detected_at": pattern.detected_at,
                    "h1_price": pattern.h1.price,
                    "l1_price": pattern.l1.price,
                    "h2_price": pattern.h2.price,
                    "l2_price": pattern.l2.price,
                    "h3_price": pattern.h3.price,
                    "l3_price": pattern.l3.price,
                    "h1_index": pattern.h1.index,
                    "l1_index": pattern.l1.index,
                    "h2_index": pattern.h2.index,
                    "l2_index": pattern.l2.index,
                    "h3_index": pattern.h3.index,
                    "l3_index": pattern.l3.index,
                    "score": score,
                    "status": "ARMED",
                    "entry_price": pattern.entry_price,
                    "stop_loss": pattern.stop_loss,
                    "target_1": pattern.target_1,
                    "target_2": pattern.target_2,
                    "rrr": pattern.rrr,
                })

                self._armed_patterns.append(pattern_record)

                logger.info(
                    f"Pattern armed: {symbol} {pattern.direction} "
                    f"score={score:.0f} rrr={pattern.rrr:.1f}"
                )
                self.trade_logger.log_event(
                    "PATTERN_ARMED",
                    symbol=symbol,
                    pattern_id=pattern_record.id,
                    details=f"Score={score:.0f}, RRR={pattern.rrr:.1f}",
                )
                self.alerter.alert_pattern_detected(
                    symbol, pattern.direction, score, pattern.rrr
                )

    def _check_armed_patterns(self):
        """Check armed patterns for entry confirmation."""
        expired = []
        triggered = []

        for pattern_record in self._armed_patterns:
            symbol = pattern_record.symbol
            direction = pattern_record.direction

            # Fetch latest 1H data
            df = fetch_and_prepare(symbol, config.PRIMARY_TIMEFRAME, bars=50)
            if df is None or df.empty:
                continue

            latest_bar = df.iloc[-1]

            # Check expiry
            bars_since_detection = len(df)  # Simplified - use bar count
            if bars_since_detection > config.PATTERN_EXPIRY_BARS:
                expired.append(pattern_record)
                continue

            # Build a lightweight pattern object for confirmation check
            from hvf_trader.detector.hvf_detector import HVFPattern
            from hvf_trader.detector.zigzag import Pivot
            import pandas as pd

            pattern = HVFPattern(
                symbol=symbol,
                timeframe=pattern_record.timeframe,
                direction=direction,
                h1=Pivot(0, pattern_record.h1_price, "H", pd.NaT),
                l1=Pivot(0, pattern_record.l1_price, "L", pd.NaT),
                h2=Pivot(0, pattern_record.h2_price, "H", pd.NaT),
                l2=Pivot(0, pattern_record.l2_price, "L", pd.NaT),
                h3=Pivot(0, pattern_record.h3_price, "H", pd.NaT),
                l3=Pivot(0, pattern_record.l3_price, "L", pd.NaT),
                entry_price=pattern_record.entry_price,
                stop_loss=pattern_record.stop_loss,
                target_1=pattern_record.target_1,
                target_2=pattern_record.target_2,
            )

            vol_avg = get_volume_average(df, 20)

            if check_entry_confirmation(pattern, latest_bar, vol_avg):
                # Entry confirmed — run pre-trade checks
                self._attempt_entry(pattern_record, pattern, df)
                triggered.append(pattern_record)

        # Clean up expired patterns
        for p in expired:
            self.trade_logger.update_pattern_status(p.id, "EXPIRED")
            self._armed_patterns.remove(p)
            logger.info(f"Pattern expired: {p.symbol} {p.direction} (id={p.id})")

        for p in triggered:
            if p in self._armed_patterns:
                self._armed_patterns.remove(p)

    def _attempt_entry(self, pattern_record, pattern, df):
        """Run pre-trade risk checks and execute if all pass."""
        symbol = pattern_record.symbol
        direction = pattern_record.direction

        account = self.connector.get_account_info()
        if not account:
            return

        symbol_info = self.connector.get_symbol_info(symbol)
        if not symbol_info:
            return

        open_trades = self.trade_logger.get_open_trades()
        news_blocking = has_upcoming_news(symbol)

        result = self.risk_manager.pre_trade_check(
            symbol=symbol,
            direction=direction,
            entry_price=pattern.entry_price,
            stop_loss=pattern.stop_loss,
            target_2=pattern.target_2,
            equity=account["equity"],
            free_margin=account["free_margin"],
            margin_used=account.get("margin", 0),
            current_spread=symbol_info["spread"] * symbol_info["point"],
            open_trades=open_trades,
            news_within_window=news_blocking,
        )

        if not result.passed:
            logger.info(
                f"Pre-trade check failed for {symbol}: "
                f"{result.check_name} — {result.reason}"
            )
            self.trade_logger.log_event(
                "TRADE_REJECTED",
                symbol=symbol,
                pattern_id=pattern_record.id,
                details=f"Check={result.check_name}: {result.reason}",
            )
            return

        # Execute market order
        ticket = self.order_manager.place_market_order(
            symbol=symbol,
            direction=direction,
            lot_size=result.lot_size,
            stop_loss=pattern.stop_loss,
        )

        if ticket is None:
            logger.error(f"Order execution failed for {symbol}")
            self.trade_logger.log_event(
                "ERROR",
                symbol=symbol,
                pattern_id=pattern_record.id,
                details="Market order execution failed",
                severity="ERROR",
            )
            return

        # Log trade
        trade_record = self.trade_logger.log_trade_open({
            "pattern_id": pattern_record.id,
            "symbol": symbol,
            "direction": direction,
            "mt5_ticket": ticket,
            "entry_price": pattern.entry_price,
            "stop_loss": pattern.stop_loss,
            "target_1": pattern.target_1,
            "target_2": pattern.target_2,
            "lot_size": result.lot_size,
            "opened_at": datetime.now(timezone.utc),
            "status": "OPEN",
        })

        # Update pattern status
        self.trade_logger.update_pattern_status(pattern_record.id, "TRIGGERED")

        self.trade_logger.log_event(
            "TRADE_OPENED",
            symbol=symbol,
            trade_id=trade_record.id,
            pattern_id=pattern_record.id,
            details=f"Ticket={ticket}, Lots={result.lot_size}, Entry={pattern.entry_price}",
        )

        self.alerter.alert_trade_opened(
            symbol=symbol,
            direction=direction,
            lot_size=result.lot_size,
            entry_price=pattern.entry_price,
            stop_loss=pattern.stop_loss,
            target_1=pattern.target_1,
            target_2=pattern.target_2,
        )

        logger.info(
            f"Trade opened: {symbol} {direction} {result.lot_size} lots "
            f"ticket={ticket}"
        )

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Signal {signum} received, initiating graceful shutdown...")
        self.stop()

    def stop(self):
        """Graceful shutdown."""
        logger.info("Shutting down HVF Trader...")
        self._running = False

        # Stop components
        self.trade_monitor.stop()
        self.health_checker.stop()

        # Flush DB
        self.trade_logger.log_event("SHUTDOWN", details="Graceful shutdown")

        # Notify
        self.alerter.alert_shutdown("Graceful shutdown")

        # Disconnect MT5 (keep server-side SLs active)
        self.connector.disconnect()

        logger.info("HVF Trader stopped")


def main():
    trader = HVFTrader()
    try:
        trader.start()
    except KeyboardInterrupt:
        trader.stop()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        trader.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
