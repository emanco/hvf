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
import types
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
from hvf_trader.alerts.telegram_commands import TelegramCommandHandler
from hvf_trader.detector.zigzag import compute_zigzag
from hvf_trader.detector.hvf_detector import detect_hvf_patterns, check_entry_confirmation
from hvf_trader.detector.pattern_scorer import score_pattern
from hvf_trader.detector.viper_detector import detect_viper_patterns, check_viper_entry_confirmation
from hvf_trader.detector.viper_scorer import score_viper
from hvf_trader.detector.kz_hunt_detector import detect_kz_hunt_patterns, check_kz_hunt_entry_confirmation
from hvf_trader.detector.kz_hunt_scorer import score_kz_hunt
from hvf_trader.detector.london_sweep_detector import detect_london_sweep_patterns, check_london_sweep_entry_confirmation
from hvf_trader.detector.london_sweep_scorer import score_london_sweep
from hvf_trader.detector.wedge_detector import detect_wedge_patterns, check_wedge_breakout, check_wedge_entry_confirmation
from hvf_trader.detector.wedge_scorer import score_wedge
from hvf_trader.detector.killzone_tracker import KillZoneTracker
from hvf_trader.detector.signal_prioritizer import prioritize_signals
from hvf_trader.data.data_fetcher import fetch_and_prepare, get_volume_average
from hvf_trader.data.calendar_cache import ensure_fresh_cache, is_cache_stale, get_cache_age_hours
from hvf_trader.data.news_filter import has_upcoming_news
from hvf_trader.risk.risk_manager import RiskManager
from hvf_trader.risk.circuit_breaker import CircuitBreaker
from hvf_trader.monitoring.performance_monitor import PerformanceMonitor

logger = logging.getLogger("hvf_trader")


def _detach_record(record):
    """Snapshot a PatternRecord ORM object into a SimpleNamespace.

    Prevents DetachedInstanceError when accessing attributes after
    a session.commit() expires loaded instances.
    """
    return types.SimpleNamespace(
        id=record.id,
        symbol=record.symbol,
        direction=record.direction,
        timeframe=record.timeframe,
        detected_at=record.detected_at,
        entry_price=record.entry_price,
        stop_loss=record.stop_loss,
        target_1=record.target_1,
        target_2=record.target_2,
        h1_price=record.h1_price,
        l1_price=record.l1_price,
        h2_price=record.h2_price,
        l2_price=record.l2_price,
        h3_price=record.h3_price,
        l3_price=record.l3_price,
        score=record.score,
        pattern_type=record.pattern_type,
    )


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
        self.trade_monitor.alerter = self.alerter

        # ─── State (init early so refs can be passed) ──────────────────
        self._armed_patterns = []  # In-memory list of armed patterns (dicts with pattern_type)
        self._armed_lock = threading.Lock()  # Protects _armed_patterns from concurrent access

        # ─── Telegram Commands ─────────────────────────────────────────
        self.telegram_commands = TelegramCommandHandler(
            alerter=self.alerter,
            trade_logger=self.trade_logger,
            connector=self.connector,
            order_manager=self.order_manager,
            armed_patterns_ref=self._armed_patterns,
            armed_lock=self._armed_lock,
        )

        # ─── Performance Monitor ────────────────────────────────────────
        self.perf_monitor = PerformanceMonitor(
            trade_logger=self.trade_logger,
            alerter=self.alerter,
            circuit_breaker=self.circuit_breaker,
        )

        # ─── Multi-Pattern Detectors ───────────────────────────────────
        self._kz_trackers: dict[str, KillZoneTracker] = {}
        for sym in config.INSTRUMENTS:
            self._kz_trackers[sym] = KillZoneTracker()

        # ─── State ───────────────────────────────────────────────────────
        self._running = False
        self._last_scan_bar = {}   # symbol -> last bar timestamp scanned
        self._last_reconcile = None
        self._last_daily_summary = None
        self._last_cache_alert = None

    def start(self):
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info(f"{config.BOT_NAME} starting...")
        logger.info(f"Environment: {config.ENVIRONMENT}")
        logger.info(f"Instruments: {config.INSTRUMENTS}")
        logger.info(f"Enabled patterns: {config.ENABLED_PATTERNS}")
        logger.info(f"Risk: {config.RISK_PCT}% per trade")
        logger.info("=" * 60)

        # Refresh economic calendar on startup if stale
        ensure_fresh_cache(max_age_hours=config.NEWS_CACHE_MAX_AGE_HOURS)

        # Connect to MT5
        if not self.connector.connect():
            logger.error("Failed to connect to MT5. Exiting.")
            return

        account = self.connector.get_account_info()
        if account:
            self._account_currency = account.get("currency", "USD")
            logger.info(
                f"Account: balance={account['balance']:.2f}, "
                f"equity={account['equity']:.2f}, "
                f"currency={self._account_currency}"
            )
        else:
            self._account_currency = "USD"

        self.trade_logger.log_event("STARTUP", details=f"Environment={config.ENVIRONMENT}")

        # ─── Startup reconciliation: DB vs MT5 ─────────────────────────
        self._reconcile_on_startup()

        # Load armed patterns from DB, filtering out stale and duplicate ones
        db_armed = self.trade_logger.get_armed_patterns()
        now = pd.Timestamp.now(tz="UTC")
        self._armed_patterns = []
        seen_keys = set()
        stale_count = 0
        dedup_count = 0
        for rec in db_armed:
            ptype = rec.pattern_type or "HVF"
            max_hours = config.PATTERN_FRESHNESS_BARS.get(ptype, 100)
            if rec.detected_at:
                hours_age = (now - pd.Timestamp(rec.detected_at, tz="UTC")).total_seconds() / 3600
                if hours_age > max_hours:
                    self.trade_logger.update_pattern_status(rec.id, "EXPIRED")
                    stale_count += 1
                    continue
            key = (rec.symbol, rec.direction)
            if key in seen_keys:
                self.trade_logger.update_pattern_status(rec.id, "EXPIRED")
                dedup_count += 1
                continue
            seen_keys.add(key)
            self._armed_patterns.append(
                {"record": _detach_record(rec), "pattern_type": ptype, "pattern_obj": None}
            )
        if stale_count:
            logger.info(f"Expired {stale_count} stale armed patterns on startup")
        if dedup_count:
            logger.info(f"Expired {dedup_count} duplicate armed patterns on startup")
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

        # Start Telegram command listener (daemon thread)
        self.telegram_commands.start()

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
        cycle_count = 0
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

                # Performance health check (hourly)
                self.perf_monitor.check_health()

                # Refresh economic calendar if stale (checked every cycle)
                if is_cache_stale():
                    refreshed = ensure_fresh_cache(max_age_hours=config.NEWS_CACHE_MAX_AGE_HOURS)
                    if not refreshed:
                        age = get_cache_age_hours()
                        age_str = f"{age:.1f}h" if age is not None else "missing"
                        if (self._last_cache_alert is None or
                                (now - self._last_cache_alert).total_seconds() >= 3600):
                            self.alerter.send_message(
                                f"\u26a0\ufe0f <b>News calendar stale</b>\n"
                                f"Cache age: {age_str} (limit: {config.NEWS_CACHE_MAX_AGE_HOURS}h)\n"
                                f"Trading blocked until refreshed."
                            )
                            logger.warning(f"Calendar cache stale ({age_str}), trading blocked")
                            self._last_cache_alert = now

                # Daily summary at 21:00 UTC (after NY close), skip weekends
                if now.hour == 21 and (
                    self._last_daily_summary is None
                    or self._last_daily_summary.date() < now.date()
                ):
                    if now.weekday() <= 4:  # Mon-Fri only
                        self.alerter.send_daily_summary(self.trade_logger, connector=self.connector)
                    if now.weekday() == 6:  # Sunday — weekly performance summary
                        self.alerter.send_performance_summary(self.trade_logger)
                    self._last_daily_summary = now

            except Exception as e:
                logger.error(f"Scanner loop error: {e}", exc_info=True)
                self.trade_logger.log_event(
                    "ERROR", details=f"Scanner: {e}", severity="ERROR"
                )

            # Heartbeat log every 60 cycles (~1 hour)
            cycle_count += 1
            if cycle_count % 60 == 0:
                logger.info(
                    f"Heartbeat: {cycle_count} cycles, "
                    f"armed={len(self._armed_patterns)}"
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

        # Update KZ tracker incrementally — only process bars newer than last update.
        # This matches the backtest's continuous tracker (single instance fed every bar).
        # On first scan after startup the tracker is empty so we warm up from 200 bars.
        kz_tracker = self._kz_trackers[symbol]
        if not hasattr(kz_tracker, '_last_bar_time') or kz_tracker._last_bar_time is None:
            # First run: warm up from 200 bars (all completed bars)
            lookback = min(200, len(df_1h) - 1)  # -1 to exclude forming bar
            for i in range(len(df_1h) - 1 - lookback, len(df_1h) - 1):
                bar = df_1h.iloc[i]
                kz_tracker.update(bar["time"], bar["high"], bar["low"], i)
            kz_tracker._last_bar_time = df_1h["time"].iloc[-2] if len(df_1h) > 1 else None
        else:
            # Incremental: only update with completed bars newer than last update
            for i in range(len(df_1h) - 1):  # exclude forming bar
                bar = df_1h.iloc[i]
                if bar["time"] > kz_tracker._last_bar_time:
                    kz_tracker.update(bar["time"], bar["high"], bar["low"], i)
            if len(df_1h) > 1:
                kz_tracker._last_bar_time = df_1h["time"].iloc[-2]

        # Use only completed bars for detection — exclude the current forming bar.
        # The forming bar's high/low/close update mid-bar and can produce phantom
        # rejection candles that disappear by bar close.  Backtest only uses
        # completed bars, so this aligns live detection with backtest behavior.
        df_completed = df_1h.iloc[:-1] if len(df_1h) > 1 else df_1h

        # Collect all signals from all detectors
        all_signals: list[dict] = []

        # 1. HVF Detector
        if "HVF" in config.ENABLED_PATTERNS:
            pivots = compute_zigzag(df_completed, config.ZIGZAG_ATR_MULTIPLIER)
            if len(pivots) >= 6:
                hvf_patterns = detect_hvf_patterns(
                    df=df_completed, symbol=symbol,
                    timeframe=config.PRIMARY_TIMEFRAME,
                    pivots=pivots, df_4h=df_4h,
                )
                for p in hvf_patterns:
                    p.score = score_pattern(p, df_completed, df_4h, df_d1)
                    threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("HVF", config.SCORE_THRESHOLD)
                    if p.score >= threshold:
                        all_signals.append({
                            "pattern": p, "pattern_type": "HVF",
                            "symbol": symbol, "direction": p.direction,
                            "score": p.score,
                        })

        # 2. Viper Detector (skip excluded symbols)
        if "VIPER" in config.ENABLED_PATTERNS and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("VIPER", []):
            viper_patterns = detect_viper_patterns(df_completed, symbol, config.PRIMARY_TIMEFRAME)
            for p in viper_patterns:
                # Direction filter (SHORT-only Viper)
                allowed_dir = config.ALLOWED_DIRECTIONS_BY_PATTERN.get("VIPER")
                if allowed_dir and p.direction != allowed_dir:
                    continue
                p.score = score_viper(p, df_completed)
                threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("VIPER", 50)
                if p.score >= threshold:
                    all_signals.append({
                        "pattern": p, "pattern_type": "VIPER",
                        "symbol": symbol, "direction": p.direction,
                        "score": p.score,
                    })

        # 3. KZ Hunt Detector (skip excluded symbols)
        if "KZ_HUNT" in config.ENABLED_PATTERNS and kz_tracker and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("KZ_HUNT", []):
            kz_patterns = detect_kz_hunt_patterns(
                df_completed, symbol, config.PRIMARY_TIMEFRAME, kz_tracker,
            )
            for p in kz_patterns:
                # Direction filter (LONG-only KZ Hunt)
                allowed_dir = config.ALLOWED_DIRECTIONS_BY_PATTERN.get("KZ_HUNT")
                if allowed_dir and p.direction != allowed_dir:
                    continue
                p.score = score_kz_hunt(p, df_completed)
                threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("KZ_HUNT", 50)
                if p.score >= threshold:
                    all_signals.append({
                        "pattern": p, "pattern_type": "KZ_HUNT",
                        "symbol": symbol, "direction": p.direction,
                        "score": p.score,
                    })

        # 4. London Sweep Detector (skip excluded symbols)
        if "LONDON_SWEEP" in config.ENABLED_PATTERNS and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("LONDON_SWEEP", []):
            ls_patterns = detect_london_sweep_patterns(df_completed, symbol, config.PRIMARY_TIMEFRAME)
            for p in ls_patterns:
                p.score = score_london_sweep(p, df_completed)
                threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("LONDON_SWEEP", 50)
                if p.score >= threshold:
                    all_signals.append({
                        "pattern": p, "pattern_type": "LONDON_SWEEP",
                        "symbol": symbol, "direction": p.direction,
                        "score": p.score,
                    })

        # 5. Wedge Detector (D1 timeframe, skip excluded symbols)
        if "WEDGE" in config.ENABLED_PATTERNS and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("WEDGE", []):
            if df_d1 is not None and len(df_d1) >= config.WEDGE_MIN_BARS + 2 * config.WEDGE_SWING_LOOKBACK:
                wedge_patterns = detect_wedge_patterns(df_d1, symbol, config.WEDGE_DETECTION_TIMEFRAME)
                for p in wedge_patterns:
                    allowed_dir = config.ALLOWED_DIRECTIONS_BY_PATTERN.get("WEDGE")
                    if allowed_dir and p.direction != allowed_dir:
                        continue
                    # Only arm if breakout is confirmed on the latest D1 bar
                    d1_atr = df_d1["atr"].iloc[-1] if "atr" in df_d1.columns else 0
                    if d1_atr > 0 and check_wedge_breakout(p, df_d1.iloc[-1], len(df_d1) - 1, d1_atr):
                        p.score = score_wedge(p, df_d1)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("WEDGE", 55)
                        if p.score >= threshold:
                            all_signals.append({
                                "pattern": p, "pattern_type": "WEDGE",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score,
                            })

        # Prioritize and arm
        prioritized = prioritize_signals(all_signals)
        armed_count = 0

        # Build sets of already-active symbol+direction combos to avoid duplicates
        open_trades = self.trade_logger.get_open_trades()
        active_positions = {(t.symbol, t.direction) for t in open_trades}
        with self._armed_lock:
            active_armed = {(a["record"].symbol, a["record"].direction) for a in self._armed_patterns}
        recent_patterns = self.trade_logger.get_recent_patterns(hours=24)
        recently_triggered = {
            (p.symbol, p.direction) for p in recent_patterns
            if p.status in ("ARMED", "TRIGGERED")
        }

        for sig in prioritized:
            key = (sig.symbol, sig.direction)
            if key in active_positions:
                logger.debug(f"Skip {sig.pattern_type} {sig.symbol} {sig.direction}: open trade exists")
                continue
            if key in active_armed:
                logger.debug(f"Skip {sig.pattern_type} {sig.symbol} {sig.direction}: already armed")
                continue
            if key in recently_triggered:
                logger.debug(f"Skip {sig.pattern_type} {sig.symbol} {sig.direction}: recently triggered")
                continue

            # Check per-pattern circuit breaker
            cb_ok, cb_reason = self.circuit_breaker.check_pattern(sig.pattern_type)
            if not cb_ok:
                logger.info(f"Pattern CB blocked {sig.pattern_type}: {cb_reason}")
                continue

            self._arm_signal(sig, df_1h)
            armed_count += 1
            active_armed.add(key)  # Prevent arming another signal for same symbol+direction

        logger.info(
            f"Scan {symbol}: {len(all_signals)} candidates, "
            f"{len(prioritized)} prioritized, {armed_count} armed"
        )

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
        elif pattern_type == "KZ_HUNT":
            # KZ invalidation: price returns to the KZ extreme we're fading
            # LONG (fading KZ low): invalidate if price revisits KZ low
            # SHORT (fading KZ high): invalidate if price revisits KZ high
            pattern_data.update({
                "h1_price": 0, "l1_price": 0,
                "h2_price": 0, "l2_price": 0,
                "h3_price": pattern.kz_high,  # SHORT invalidation level
                "l3_price": pattern.kz_low,   # LONG invalidation level
                "h1_index": 0, "l1_index": 0,
                "h2_index": 0, "l2_index": 0,
                "h3_index": 0, "l3_index": 0,
            })
        else:
            # Other non-HVF patterns: disable invalidation by using extreme values
            pattern_data.update({
                "h1_price": 0, "l1_price": 0,
                "h2_price": 0, "l2_price": 0,
                "h3_price": 999999, "l3_price": -999999,
                "h1_index": 0, "l1_index": 0,
                "h2_index": 0, "l2_index": 0,
                "h3_index": 0, "l3_index": 0,
            })

        pattern_record = self.trade_logger.log_pattern(pattern_data)

        # Store armed pattern with its type and the original pattern object
        with self._armed_lock:
            self._armed_patterns.append({
                "record": _detach_record(pattern_record),
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
            sig.symbol, sig.direction, sig.score, pattern.rrr, pattern_type
        )

    def _check_armed_patterns(self):
        """Check armed patterns for entry confirmation across all types."""
        expired = []
        triggered = []

        # Snapshot under lock to avoid RuntimeError from concurrent modification
        with self._armed_lock:
            armed_snapshot = list(self._armed_patterns)

        for armed in armed_snapshot:
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

            # Check expiry using actual time since detection (per-pattern freshness)
            expiry_bars = config.PATTERN_FRESHNESS_BARS.get(pattern_type, config.PATTERN_EXPIRY_BARS)
            if record.detected_at:
                hours_since = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(record.detected_at, tz="UTC")).total_seconds() / 3600
                bars_since_detection = int(hours_since)  # H1 bars ≈ hours
            else:
                bars_since_detection = len(df)
            if bars_since_detection > expiry_bars:
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
            elif pattern_type in ("VIPER", "KZ_HUNT", "LONDON_SWEEP", "WEDGE"):
                # pattern_obj may be None for DB-loaded patterns; use record for price check
                if pattern_obj is not None:
                    if pattern_type == "VIPER":
                        confirmed = check_viper_entry_confirmation(pattern_obj, latest_bar)
                    elif pattern_type == "KZ_HUNT":
                        confirmed = check_kz_hunt_entry_confirmation(pattern_obj, latest_bar)
                    elif pattern_type == "WEDGE":
                        confirmed = check_wedge_entry_confirmation(pattern_obj, latest_bar)
                    else:
                        confirmed = check_london_sweep_entry_confirmation(pattern_obj, latest_bar)
                else:
                    # DB-loaded pattern (no pattern_obj after restart):
                    # same simple confirmation as fresh patterns.
                    # Pattern freshness (24-bar expiry) already guards against stale entries.
                    close_price = latest_bar.get("close")
                    if close_price is not None and record.entry_price:
                        if direction == "LONG":
                            confirmed = float(close_price) > record.entry_price
                        else:
                            confirmed = float(close_price) < record.entry_price

            if confirmed:
                try:
                    self._attempt_entry(record, pattern_obj, df, pattern_type)
                except Exception as e:
                    logger.error(
                        f"[{pattern_type}] _attempt_entry failed for {symbol} {direction}: {e}",
                        exc_info=True,
                    )
                    self.trade_logger.update_pattern_status(record.id, "REJECTED")
                    self.trade_logger.log_event(
                        "ERROR",
                        symbol=symbol,
                        pattern_id=record.id,
                        details=f"Entry attempt exception: {e}",
                        severity="ERROR",
                    )
                triggered.append(armed)

        # Clean up expired patterns
        for armed in expired:
            self.trade_logger.update_pattern_status(armed["record"].id, "EXPIRED")
            with self._armed_lock:
                if armed in self._armed_patterns:
                    self._armed_patterns.remove(armed)
            r = armed["record"]
            logger.info(
                f"[{armed['pattern_type']}] Expired: {r.symbol} {r.direction} (id={r.id})"
            )

        with self._armed_lock:
            for armed in triggered:
                if armed in self._armed_patterns:
                    self._armed_patterns.remove(armed)

    def _get_quote_to_account_rate(self, symbol: str) -> float:
        """Get exchange rate to convert pip value from quote currency to account currency.

        Works with any account currency (USD, EUR, GBP, etc.) by dynamically
        looking up the conversion pair in MT5.
        """
        quote_ccy = symbol[3:6]  # e.g. EURUSD -> USD, EURGBP -> GBP
        account_ccy = self._account_currency
        if quote_ccy == account_ccy:
            return 1.0

        # Try direct pair: {quote}{account} e.g. GBPUSD
        direct = quote_ccy + account_ccy
        fx_info = self.connector.get_symbol_info(direct, quiet=True)
        if fx_info and fx_info["bid"] > 0:
            logger.debug(f"FX rate {symbol}: {direct} bid={fx_info['bid']:.5f}")
            return fx_info["bid"]

        # Try inverse pair: {account}{quote} e.g. USDCHF -> invert
        inverse = account_ccy + quote_ccy
        fx_info = self.connector.get_symbol_info(inverse, quiet=True)
        if fx_info and fx_info["bid"] > 0:
            rate = 1.0 / fx_info["bid"]
            logger.debug(f"FX rate {symbol}: 1/{inverse} bid={fx_info['bid']:.5f} = {rate:.5f}")
            return rate

        logger.warning(f"Cannot find FX pair for {quote_ccy}->{account_ccy}, defaulting to 1.0")
        return 1.0

    def _attempt_entry(self, pattern_record, pattern, df, pattern_type="HVF"):
        """Run pre-trade risk checks and execute if all pass."""
        symbol = pattern_record.symbol
        direction = pattern_record.direction

        # For DB-loaded patterns, pattern_obj may be None — use record as fallback
        if pattern is None:
            pattern = pattern_record

        account = self.connector.get_account_info()
        if not account:
            return

        symbol_info = self.connector.get_symbol_info(symbol)
        if not symbol_info:
            return

        open_trades = self.trade_logger.get_open_trades()
        news_blocking = has_upcoming_news(symbol)

        # Use current market price for position sizing (not pattern's theoretical
        # entry). This matches the backtest which uses actual bar close, and
        # accounts for spread + price movement since detection.
        spread_price = symbol_info["spread"] * symbol_info["point"]
        if direction == "LONG":
            live_entry = symbol_info["ask"]
        else:
            live_entry = symbol_info["bid"]

        # Widen SL by the spread to match backtest conditions (no spread).
        # LONG: move SL down by spread; SHORT: move SL up by spread.
        if direction == "LONG":
            adjusted_sl = pattern.stop_loss - spread_price
        else:
            adjusted_sl = pattern.stop_loss + spread_price

        # Guard: SL must be on the correct side of live price with enough room.
        # Minimum stop distance = max(5x spread, pattern minimum pips) to avoid noise stops.
        pip_size = config.PIP_VALUES.get(symbol, 0.0001)
        min_stop_pips = config.MIN_STOP_PIPS_BY_PATTERN.get(pattern_type, 5)
        min_stop_dist = max(spread_price * 5, pip_size * min_stop_pips)
        if direction == "LONG" and (live_entry - adjusted_sl) < min_stop_dist:
            logger.info(
                f"[{pattern_type}] Skipping {symbol} {direction}: "
                f"SL too close or wrong side (entry={live_entry:.5f}, sl={adjusted_sl:.5f}, "
                f"min_dist={min_stop_dist:.5f})"
            )
            self.trade_logger.update_pattern_status(pattern_record.id, "REJECTED")
            return
        if direction == "SHORT" and (adjusted_sl - live_entry) < min_stop_dist:
            logger.info(
                f"[{pattern_type}] Skipping {symbol} {direction}: "
                f"SL too close or wrong side (entry={live_entry:.5f}, sl={adjusted_sl:.5f}, "
                f"min_dist={min_stop_dist:.5f})"
            )
            self.trade_logger.update_pattern_status(pattern_record.id, "REJECTED")
            return

        # Convert pip value to account currency (USD) for non-USD quoted pairs
        fx_rate = self._get_quote_to_account_rate(symbol)

        result = self.risk_manager.pre_trade_check(
            symbol=symbol,
            direction=direction,
            entry_price=live_entry,
            stop_loss=adjusted_sl,
            target_2=pattern.target_2,
            equity=account["equity"],
            free_margin=account["free_margin"],
            margin_used=account.get("margin", 0),
            current_spread=spread_price,
            open_trades=open_trades,
            news_within_window=news_blocking,
            pattern_type=pattern_type,
            exchange_rate_to_account=fx_rate,
        )

        if not result.passed:
            logger.info(
                f"Pre-trade check failed for {symbol}: "
                f"{result.check_name} — {result.reason}"
            )
            self.trade_logger.update_pattern_status(pattern_record.id, "REJECTED")
            self.trade_logger.log_event(
                "TRADE_REJECTED",
                symbol=symbol,
                pattern_id=pattern_record.id,
                details=f"Check={result.check_name}: {result.reason}",
            )
            if result.check_name == "news_filter":
                self.alerter.send_message(
                    f"\U0001F4F0 <b>News Block</b>: {symbol} {direction} "
                    f"({pattern_type}) rejected\n{result.reason}"
                )
            return

        # Execute market order(s) with spread-adjusted SL.
        # Split into two positions: 60% with TP=T1 (MT5 handles at tick level)
        # and 40% without TP (managed by trade monitor trailing stop).
        # This ensures T1 is caught on any intra-bar wick, matching backtest behavior.
        partial_pct = config.PARTIAL_CLOSE_PCT  # 0.60
        partial_lots = round(result.lot_size * partial_pct, 2)
        remaining_lots = round(result.lot_size - partial_lots, 2)

        # Validate both lot sizes meet minimums
        symbol_info_mt5 = self.connector.get_symbol_info(symbol)
        vol_min = symbol_info_mt5.get("volume_min", 0.01) if symbol_info_mt5 else 0.01
        can_split = partial_lots >= vol_min and remaining_lots >= vol_min

        ticket_partial = None
        if can_split and pattern.target_1:
            # Place 60% position with TP=T1 (auto-closed by MT5 at tick level)
            order_partial = self.order_manager.place_market_order(
                symbol=symbol,
                direction=direction,
                lot_size=partial_lots,
                stop_loss=adjusted_sl,
                take_profit=pattern.target_1,
                comment=f"{pattern_type} T1",
            )
            if order_partial is None:
                logger.error(f"Partial order (60%) failed for {symbol}, falling back to single order")
                can_split = False
            else:
                ticket_partial = order_partial["ticket"]

            # Place 40% position without TP (trailing managed by trade monitor)
            if can_split:
                order_remaining = self.order_manager.place_market_order(
                    symbol=symbol,
                    direction=direction,
                    lot_size=remaining_lots,
                    stop_loss=adjusted_sl,
                    comment=f"{pattern_type} T2",
                )
                if order_remaining is None:
                    logger.error(
                        f"Remaining order (40%) failed for {symbol}, "
                        f"closing partial position"
                    )
                    self.order_manager.close_position(
                        ticket_partial, symbol, direction, "failed_split"
                    )
                    can_split = False
                    ticket_partial = None

        if can_split and ticket_partial:
            # Split order succeeded
            order_result = order_remaining
            fill_price = order_remaining["fill_price"]
            ticket = order_remaining["ticket"]
            logger.info(
                f"[{pattern_type}] Split order: partial={partial_lots} lots "
                f"ticket={ticket_partial} TP={pattern.target_1:.5f}, "
                f"remaining={remaining_lots} lots ticket={ticket}"
            )
        else:
            # Fallback: single order (original behavior for small lots)
            ticket_partial = None
            order_result = self.order_manager.place_market_order(
                symbol=symbol,
                direction=direction,
                lot_size=result.lot_size,
                stop_loss=adjusted_sl,
                comment=pattern_type,
            )

        if order_result is None:
            logger.error(f"Order execution failed for {symbol}")
            self.trade_logger.update_pattern_status(pattern_record.id, "REJECTED")
            self.trade_logger.log_event(
                "ERROR",
                symbol=symbol,
                pattern_id=pattern_record.id,
                details="Market order execution failed",
                severity="ERROR",
            )
            return

        ticket = order_result["ticket"]
        fill_price = order_result["fill_price"]

        # Recalculate SL from actual fill price to maintain the intended stop distance.
        # Use the validated pre-order distance (live_entry to adjusted_sl), not the
        # stale pattern geometry which can be tiny when fill differs from pattern entry.
        stop_distance = abs(live_entry - adjusted_sl)
        if direction == "LONG":
            final_sl = fill_price - stop_distance
        else:
            final_sl = fill_price + stop_distance

        # Post-fill min-stop guard: if recalculated SL is too tight, keep the
        # original adjusted_sl which already passed the pre-order guard.
        final_stop_dist = abs(fill_price - final_sl)
        if final_stop_dist < min_stop_dist:
            logger.warning(
                f"[{pattern_type}] Post-fill SL too tight ({final_stop_dist/pip_size:.1f} pips), "
                f"keeping pre-order SL={adjusted_sl:.5f}"
            )
            final_sl = adjusted_sl

        # Apply the recalculated SL if it differs from what was sent with the order
        # Derive digits from point: 0.00001 -> 5, 0.001 -> 3
        digits = len(str(symbol_info["point"]).rstrip('0').split('.')[-1])
        final_sl = round(final_sl, digits)
        if abs(final_sl - adjusted_sl) > symbol_info["point"]:
            modified = self.order_manager.modify_stop_loss(ticket, symbol, final_sl)
            if modified:
                logger.info(
                    f"[{pattern_type}] SL recalculated from fill: "
                    f"sent_sl={adjusted_sl:.5f} -> final_sl={final_sl:.5f} "
                    f"(fill={fill_price:.5f} vs pre-fill={live_entry:.5f})"
                )
                # Also update SL on partial position if split order
                if ticket_partial:
                    self.order_manager.modify_stop_loss(ticket_partial, symbol, final_sl)
            else:
                logger.warning(
                    f"[{pattern_type}] SL modify failed, keeping sent_sl={adjusted_sl:.5f}"
                )
                final_sl = adjusted_sl
        else:
            final_sl = adjusted_sl

        logger.info(
            f"[{pattern_type}] Executed {direction} {symbol}: "
            f"pattern_entry={pattern.entry_price:.5f}, fill={fill_price:.5f}, "
            f"original_sl={pattern.stop_loss:.5f}, final_sl={final_sl:.5f}, "
            f"spread={spread_price:.5f}, lots={result.lot_size}"
        )

        # Compute slippage: positive = worse fill (paid more for LONG, got less for SHORT)
        if direction == "LONG":
            slippage = fill_price - pattern.entry_price
        else:
            slippage = pattern.entry_price - fill_price

        # Log trade
        trade_data = {
            "pattern_id": pattern_record.id,
            "symbol": symbol,
            "direction": direction,
            "pattern_type": pattern_type,
            "mt5_ticket": ticket,
            "entry_price": fill_price,
            "stop_loss": final_sl,
            "target_1": pattern.target_1,
            "target_2": pattern.target_2,
            "lot_size": result.lot_size,
            "opened_at": datetime.now(timezone.utc),
            "status": "OPEN",
            "intended_entry": pattern.entry_price,
            "intended_sl": pattern.stop_loss,
            "slippage": slippage,
        }
        if ticket_partial:
            trade_data["mt5_ticket_partial"] = ticket_partial
        trade_record = self.trade_logger.log_trade_open(trade_data)

        # Update pattern status
        self.trade_logger.update_pattern_status(pattern_record.id, "TRIGGERED")

        self.trade_logger.log_event(
            "TRADE_OPENED",
            symbol=symbol,
            trade_id=trade_record.id,
            pattern_id=pattern_record.id,
            details=f"Ticket={ticket}, Lots={result.lot_size}, Entry={fill_price:.5f}",
        )

        self.alerter.alert_trade_opened(
            symbol=symbol,
            direction=direction,
            lot_size=result.lot_size,
            entry_price=pattern.entry_price,
            stop_loss=pattern.stop_loss,
            target_1=pattern.target_1,
            target_2=pattern.target_2,
            pattern_type=pattern_type,
        )

        logger.info(
            f"Trade opened: {symbol} {direction} {result.lot_size} lots "
            f"ticket={ticket}"
        )

    def _reconcile_on_startup(self):
        """Compare DB open trades against MT5 positions. Log and alert on mismatches."""
        db_trades = self.trade_logger.get_open_trades()
        mt5_positions = self.order_manager.get_all_positions() if hasattr(self.order_manager, 'get_all_positions') else []

        # Build lookup sets
        db_tickets = {}
        for t in db_trades:
            if t.mt5_ticket:
                db_tickets[t.mt5_ticket] = t
        mt5_tickets = {p["ticket"]: p for p in mt5_positions}

        # Collect split-order partial tickets so they aren't flagged as orphans
        partial_tickets = {
            t.mt5_ticket_partial
            for t in db_trades
            if getattr(t, 'mt5_ticket_partial', None)
        }

        issues = []

        # DB says open, MT5 has no position (ghost trade)
        for ticket, trade in db_tickets.items():
            if ticket not in mt5_tickets:
                issues.append(
                    f"GHOST: DB trade {trade.id} ({trade.symbol} {trade.direction}) "
                    f"ticket={ticket} not found in MT5 — may have been closed while bot was down"
                )

        # MT5 has position, DB doesn't know about it (orphan position)
        for ticket, pos in mt5_tickets.items():
            if ticket not in db_tickets:
                # Skip split-order partial positions (managed by trade_monitor)
                if ticket in partial_tickets:
                    continue
                issues.append(
                    f"ORPHAN: MT5 position ticket={ticket} ({pos['symbol']} {pos['type']} "
                    f"{pos['volume']} lots) not tracked in DB"
                )

        # Volume mismatch (partial close happened server-side or DB out of sync)
        for ticket in db_tickets:
            if ticket in mt5_tickets:
                db_trade = db_tickets[ticket]
                mt5_pos = mt5_tickets[ticket]
                # For split orders, DB lot_size is total but MT5 position is
                # only the remainder (40%).  Skip volume check in that case.
                if getattr(db_trade, 'mt5_ticket_partial', None):
                    continue
                if db_trade.lot_size and abs(mt5_pos["volume"] - db_trade.lot_size) > 0.001:
                    # Could be a partial close — only flag if NOT already marked partial
                    if not db_trade.partial_closed:
                        issues.append(
                            f"VOLUME: DB trade {db_trade.id} ({db_trade.symbol}) "
                            f"lots DB={db_trade.lot_size} vs MT5={mt5_pos['volume']}"
                        )

        if issues:
            msg = f"RECONCILIATION: {len(issues)} issue(s) found on startup:\n" + "\n".join(issues)
            logger.warning(msg)
            self.trade_logger.log_event("RECONCILIATION", details=msg, severity="WARNING")
            self.alerter.send_message(f"⚠️ {msg}")
        else:
            n_db = len(db_trades)
            n_mt5 = len(mt5_positions)
            logger.info(f"Reconciliation OK: {n_db} DB trades, {n_mt5} MT5 positions — all match")

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Signal {signum} received, initiating graceful shutdown...")
        self.stop()

    def stop(self):
        """Graceful shutdown."""
        logger.info(f"Shutting down {config.BOT_NAME}...")
        self._running = False

        # Stop components
        self.telegram_commands.stop()
        self.trade_monitor.stop()
        self.health_checker.stop()

        # Flush DB
        self.trade_logger.log_event("SHUTDOWN", details="Graceful shutdown")

        # Notify
        self.alerter.alert_shutdown("Graceful shutdown")

        # Disconnect MT5 (keep server-side SLs active)
        self.connector.disconnect()

        logger.info(f"{config.BOT_NAME} stopped")


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
