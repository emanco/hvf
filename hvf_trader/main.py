"""
HVF Auto-Trader Orchestrator
3 threads: scanner, trade monitor, health check
Graceful shutdown on SIGINT/SIGTERM
"""

import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Ensure the parent of hvf_trader/ is on sys.path so package imports work
# regardless of the working directory (e.g. running from C:\hvf_trader\ on VPS)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from hvf_trader.detector.viper_detector import detect_viper_patterns, check_viper_entry_confirmation
from hvf_trader.detector.viper_scorer import score_viper
from hvf_trader.detector.kz_hunt_detector import detect_kz_hunt_patterns, check_kz_hunt_entry_confirmation
from hvf_trader.detector.kz_hunt_scorer import score_kz_hunt
from hvf_trader.detector.london_sweep_detector import detect_london_sweep_patterns, check_london_sweep_entry_confirmation
from hvf_trader.detector.london_sweep_scorer import score_london_sweep
from hvf_trader.detector.killzone_tracker import KillZoneTracker
from hvf_trader.detector.signal_prioritizer import prioritize_signals
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

        # ─── Multi-Pattern Detectors ───────────────────────────────────
        self._kz_trackers: dict[str, KillZoneTracker] = {}
        for sym in config.INSTRUMENTS:
            self._kz_trackers[sym] = KillZoneTracker()

        # ─── State ───────────────────────────────────────────────────────
        self._running = False
        self._armed_patterns = []  # In-memory list of armed patterns (dicts with pattern_type)
        self._last_scan_bar = {}   # symbol -> last bar timestamp scanned
        self._last_reconcile = None
        self._last_daily_summary = None

    def start(self):
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info("HVF Auto-Trader starting...")
        logger.info(f"Environment: {config.ENVIRONMENT}")
        logger.info(f"Instruments: {config.INSTRUMENTS}")
        logger.info(f"Enabled patterns: {config.ENABLED_PATTERNS}")
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
        """Scan a single instrument for patterns across all detectors."""
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

        # Fetch multi-TF data
        df_4h = fetch_and_prepare(symbol, config.CONFIRMATION_TIMEFRAME, bars=200)
        df_d1 = fetch_and_prepare(symbol, "D1", bars=100)

        # Update KZ tracker with latest bar
        kz_tracker = self._kz_trackers.get(symbol)
        if kz_tracker:
            latest_bar = df_1h.iloc[-1]
            kz_tracker.update(
                latest_bar["time"], latest_bar["high"],
                latest_bar["low"], len(df_1h) - 1,
            )

        # Collect all signals from all detectors
        all_signals: list[dict] = []

        # 1. HVF Detector
        if "HVF" in config.ENABLED_PATTERNS:
            pivots = compute_zigzag(df_1h, config.ZIGZAG_ATR_MULTIPLIER)
            if len(pivots) >= 6:
                hvf_patterns = detect_hvf_patterns(
                    df=df_1h, symbol=symbol,
                    timeframe=config.PRIMARY_TIMEFRAME,
                    pivots=pivots, df_4h=df_4h,
                )
                for p in hvf_patterns:
                    p.score = score_pattern(p, df_1h, df_4h, df_d1)
                    threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("HVF", config.SCORE_THRESHOLD)
                    if p.score >= threshold:
                        all_signals.append({
                            "pattern": p, "pattern_type": "HVF",
                            "symbol": symbol, "direction": p.direction,
                            "score": p.score,
                        })

        # 2. Viper Detector
        if "VIPER" in config.ENABLED_PATTERNS:
            viper_patterns = detect_viper_patterns(df_1h, symbol, config.PRIMARY_TIMEFRAME)
            for p in viper_patterns:
                p.score = score_viper(p, df_1h)
                threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("VIPER", 50)
                if p.score >= threshold:
                    all_signals.append({
                        "pattern": p, "pattern_type": "VIPER",
                        "symbol": symbol, "direction": p.direction,
                        "score": p.score,
                    })

        # 3. KZ Hunt Detector
        if "KZ_HUNT" in config.ENABLED_PATTERNS and kz_tracker:
            kz_patterns = detect_kz_hunt_patterns(
                df_1h, symbol, config.PRIMARY_TIMEFRAME, kz_tracker,
            )
            for p in kz_patterns:
                p.score = score_kz_hunt(p, df_1h)
                threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("KZ_HUNT", 50)
                if p.score >= threshold:
                    all_signals.append({
                        "pattern": p, "pattern_type": "KZ_HUNT",
                        "symbol": symbol, "direction": p.direction,
                        "score": p.score,
                    })

        # 4. London Sweep Detector
        if "LONDON_SWEEP" in config.ENABLED_PATTERNS:
            ls_patterns = detect_london_sweep_patterns(df_1h, symbol, config.PRIMARY_TIMEFRAME)
            for p in ls_patterns:
                p.score = score_london_sweep(p, df_1h)
                threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("LONDON_SWEEP", 50)
                if p.score >= threshold:
                    all_signals.append({
                        "pattern": p, "pattern_type": "LONDON_SWEEP",
                        "symbol": symbol, "direction": p.direction,
                        "score": p.score,
                    })

        # Prioritize and arm
        prioritized = prioritize_signals(all_signals)
        for sig in prioritized:
            # Check per-pattern circuit breaker
            cb_ok, cb_reason = self.circuit_breaker.check_pattern(sig.pattern_type)
            if not cb_ok:
                logger.info(f"Pattern CB blocked {sig.pattern_type}: {cb_reason}")
                continue

            self._arm_signal(sig, df_1h)

    def _arm_signal(self, sig, df_1h):
        """Arm a prioritized signal by logging to DB and adding to armed list."""
        pattern = sig.pattern
        pattern_type = sig.pattern_type
        now = datetime.now(timezone.utc)

        # Build common pattern data
        pattern_data = {
            "symbol": sig.symbol,
            "timeframe": config.PRIMARY_TIMEFRAME,
            "direction": sig.direction,
            "detected_at": now,
            "score": sig.score,
            "status": "ARMED",
            "entry_price": pattern.entry_price,
            "stop_loss": pattern.stop_loss,
            "target_1": pattern.target_1,
            "target_2": pattern.target_2,
            "rrr": pattern.rrr,
            "pattern_type": pattern_type,
        }

        # HVF-specific pivot data
        if pattern_type == "HVF":
            pattern_data.update({
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
            })
        else:
            # Non-HVF patterns use zero pivots in DB
            pattern_data.update({
                "h1_price": 0, "l1_price": 0,
                "h2_price": 0, "l2_price": 0,
                "h3_price": 0, "l3_price": 0,
                "h1_index": 0, "l1_index": 0,
                "h2_index": 0, "l2_index": 0,
                "h3_index": 0, "l3_index": 0,
            })

        pattern_record = self.trade_logger.log_pattern(pattern_data)

        # Store armed pattern with its type and the original pattern object
        self._armed_patterns.append({
            "record": pattern_record,
            "pattern_type": pattern_type,
            "pattern_obj": pattern,
        })

        logger.info(
            f"[{pattern_type}] Armed: {sig.symbol} {sig.direction} "
            f"score={sig.score:.0f} rrr={pattern.rrr:.1f}"
        )
        self.trade_logger.log_event(
            "PATTERN_ARMED",
            symbol=sig.symbol,
            pattern_id=pattern_record.id,
            details=f"Type={pattern_type}, Score={sig.score:.0f}, RRR={pattern.rrr:.1f}",
        )
        self.alerter.alert_pattern_detected(
            sig.symbol, sig.direction, sig.score, pattern.rrr
        )

    def _check_armed_patterns(self):
        """Check armed patterns for entry confirmation across all types."""
        expired = []
        triggered = []

        for armed in self._armed_patterns:
            record = armed["record"]
            pattern_type = armed["pattern_type"]
            pattern_obj = armed["pattern_obj"]
            symbol = record.symbol
            direction = record.direction

            # Fetch latest 1H data
            df = fetch_and_prepare(symbol, config.PRIMARY_TIMEFRAME, bars=50)
            if df is None or df.empty:
                continue

            latest_bar = df.iloc[-1]

            # Check expiry
            bars_since_detection = len(df)
            if bars_since_detection > config.PATTERN_EXPIRY_BARS:
                expired.append(armed)
                continue

            # Entry confirmation depends on pattern type
            confirmed = False
            if pattern_type == "HVF":
                from hvf_trader.detector.hvf_detector import HVFPattern
                from hvf_trader.detector.zigzag import Pivot
                hvf_pattern = HVFPattern(
                    symbol=symbol, timeframe=record.timeframe,
                    direction=direction,
                    h1=Pivot(0, record.h1_price, "H", pd.NaT),
                    l1=Pivot(0, record.l1_price, "L", pd.NaT),
                    h2=Pivot(0, record.h2_price, "H", pd.NaT),
                    l2=Pivot(0, record.l2_price, "L", pd.NaT),
                    h3=Pivot(0, record.h3_price, "H", pd.NaT),
                    l3=Pivot(0, record.l3_price, "L", pd.NaT),
                    entry_price=record.entry_price,
                    stop_loss=record.stop_loss,
                    target_1=record.target_1,
                    target_2=record.target_2,
                )
                vol_avg = get_volume_average(df, 20)
                confirmed = check_entry_confirmation(hvf_pattern, latest_bar, vol_avg)
            elif pattern_type == "VIPER":
                confirmed = check_viper_entry_confirmation(pattern_obj, latest_bar)
            elif pattern_type == "KZ_HUNT":
                confirmed = check_kz_hunt_entry_confirmation(pattern_obj, latest_bar)
            elif pattern_type == "LONDON_SWEEP":
                confirmed = check_london_sweep_entry_confirmation(pattern_obj, latest_bar)

            if confirmed:
                self._attempt_entry(record, pattern_obj, df, pattern_type)
                triggered.append(armed)

        # Clean up expired patterns
        for armed in expired:
            self.trade_logger.update_pattern_status(armed["record"].id, "EXPIRED")
            self._armed_patterns.remove(armed)
            r = armed["record"]
            logger.info(
                f"[{armed['pattern_type']}] Expired: {r.symbol} {r.direction} (id={r.id})"
            )

        for armed in triggered:
            if armed in self._armed_patterns:
                self._armed_patterns.remove(armed)

    def _attempt_entry(self, pattern_record, pattern, df, pattern_type="HVF"):
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
            pattern_type=pattern_type,
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
