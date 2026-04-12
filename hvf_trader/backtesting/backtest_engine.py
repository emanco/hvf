"""
Event-driven backtester that reuses the detector and risk code.
"""

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config
from hvf_trader.detector.zigzag import compute_zigzag
from hvf_trader.detector.hvf_detector import detect_hvf_patterns, HVFPattern
from hvf_trader.detector.pattern_scorer import score_pattern
from hvf_trader.detector.viper_detector import detect_viper_patterns
from hvf_trader.detector.viper_scorer import score_viper
from hvf_trader.detector.kz_hunt_detector import detect_kz_hunt_patterns
from hvf_trader.detector.kz_hunt_scorer import score_kz_hunt
from hvf_trader.detector.london_sweep_detector import detect_london_sweep_patterns
from hvf_trader.detector.london_sweep_scorer import score_london_sweep
from hvf_trader.detector.killzone_tracker import KillZoneTracker
from hvf_trader.detector.signal_prioritizer import prioritize_signals
from hvf_trader.risk.position_sizer import calculate_lot_size, validate_lot_size

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    lot_size: float
    entry_bar: int
    entry_time: pd.Timestamp
    score: float
    rrr: float
    pattern_type: str = "HVF"

    # Invalidation levels (h3/l3 or kz_high/kz_low)
    invalidation_long: float = 0.0   # LONG invalidated if price <= this (l3/kz_low)
    invalidation_short: float = 0.0  # SHORT invalidated if price >= this (h3/kz_high)

    # Filled on close
    exit_price: float = 0.0
    exit_bar: int = 0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: str = ""
    pnl_pips: float = 0.0
    pnl_currency: float = 0.0
    partial_closed: bool = False
    partial_price: float = 0.0
    max_favourable: float = 0.0  # Max favourable excursion in pips
    max_adverse: float = 0.0     # Max adverse excursion in pips


@dataclass
class BacktestResult:
    symbol: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    trades: list[BacktestTrade] = field(default_factory=list)

    # Computed metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    invalidation_exits: int = 0
    win_rate: float = 0.0
    total_pnl_pips: float = 0.0
    total_pnl_currency: float = 0.0
    avg_win_pips: float = 0.0
    avg_loss_pips: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_rrr_achieved: float = 0.0
    avg_score: float = 0.0

    def compute_metrics(self, starting_equity: float = 500.0):
        """Calculate all performance metrics from trades."""
        self.total_trades = len(self.trades)
        if self.total_trades == 0:
            return

        winners = [t for t in self.trades if t.pnl_pips > 0]
        losers = [t for t in self.trades if t.pnl_pips <= 0]

        self.winning_trades = len(winners)
        self.losing_trades = len(losers)
        self.invalidation_exits = sum(1 for t in self.trades if t.exit_reason == "INVALIDATION")
        self.win_rate = self.winning_trades / self.total_trades * 100

        self.total_pnl_pips = sum(t.pnl_pips for t in self.trades)
        self.total_pnl_currency = sum(t.pnl_currency for t in self.trades)

        self.avg_win_pips = (
            np.mean([t.pnl_pips for t in winners]) if winners else 0.0
        )
        self.avg_loss_pips = (
            np.mean([abs(t.pnl_pips) for t in losers]) if losers else 0.0
        )

        gross_profit = sum(t.pnl_currency for t in winners) if winners else 0.0
        gross_loss = abs(sum(t.pnl_currency for t in losers)) if losers else 0.0
        self.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        self.avg_score = np.mean([t.score for t in self.trades])

        # Drawdown calculation
        equity_curve = [starting_equity]
        for trade in self.trades:
            equity_curve.append(equity_curve[-1] + trade.pnl_currency)
        peak = starting_equity
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown_pct = max_dd

        # Average achieved RRR
        achieved_rrrs = []
        for t in self.trades:
            risk = abs(t.entry_price - t.stop_loss)
            if risk > 0:
                achieved_rrrs.append(t.pnl_pips * config.PIP_VALUES.get(t.symbol, 0.0001) / risk)
        self.avg_rrr_achieved = np.mean(achieved_rrrs) if achieved_rrrs else 0.0


class BacktestEngine:
    def __init__(
        self,
        starting_equity: float = 500.0,
        risk_pct: float = None,
        score_threshold: float = None,
        enabled_patterns: list[str] = None,
        simulate_news_blocks: bool = False,
        simulate_circuit_breaker: bool = False,
    ):
        self.starting_equity = starting_equity
        self.risk_pct = risk_pct or config.RISK_PCT
        self.score_threshold = score_threshold or config.SCORE_THRESHOLD
        self.equity = starting_equity
        # Which pattern types to detect. Default: HVF only (backward compatible)
        self.enabled_patterns = enabled_patterns or ["HVF"]
        self.simulate_news_blocks = simulate_news_blocks
        self.simulate_circuit_breaker = simulate_circuit_breaker

    # ------------------------------------------------------------------
    # News filter simulation helpers
    # ------------------------------------------------------------------

    # Map symbols to affected currencies (matches live news_filter.py)
    _SYMBOL_CURRENCIES = {
        "EURUSD": ["EUR", "USD"], "NZDUSD": ["NZD", "USD"],
        "EURGBP": ["EUR", "GBP"], "USDCHF": ["USD", "CHF"],
        "EURAUD": ["EUR", "AUD"], "GBPUSD": ["GBP", "USD"],
    }

    @staticmethod
    def _generate_news_events(start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[tuple]:
        """Generate known recurring high-impact news event times.

        Returns list of (event_name, event_time_utc, affected_currencies).
        Covers the major recurring events that predictably block trades.
        """
        events = []
        # NFP: First Friday of each month at 13:30 UTC (affects USD pairs)
        current = start_date.to_pydatetime().replace(day=1, tzinfo=None)
        end_dt = end_date.to_pydatetime().replace(tzinfo=None)
        while current <= end_dt:
            day = current
            while day.weekday() != 4:  # Friday
                day += timedelta(days=1)
            nfp_time = day.replace(hour=13, minute=30, second=0, microsecond=0)
            if start_date.to_pydatetime().replace(tzinfo=None) <= nfp_time <= end_dt:
                events.append(("NFP", pd.Timestamp(nfp_time, tz="UTC"), ["USD"]))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return events

    def _is_news_blocked(self, bar_time: pd.Timestamp, symbol: str, news_events: list) -> bool:
        """Check if entry should be blocked due to high-impact news."""
        window = timedelta(minutes=config.NEWS_BLOCK_MINUTES)
        currencies = self._SYMBOL_CURRENCIES.get(symbol, [])
        for _, event_time, affected in news_events:
            if any(c in currencies for c in affected):
                diff = abs((bar_time - event_time).total_seconds())
                if diff <= window.total_seconds():
                    return True
        return False

    # ------------------------------------------------------------------
    # Circuit breaker simulation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_period_start(bar_time: pd.Timestamp, level: str) -> pd.Timestamp:
        """Get the start of the daily/weekly/monthly period for a bar time."""
        t = bar_time
        if level == "DAILY":
            return pd.Timestamp(t.year, t.month, t.day)
        elif level == "WEEKLY":
            days_since_monday = t.weekday()
            monday = t - timedelta(days=days_since_monday)
            return pd.Timestamp(monday.year, monday.month, monday.day)
        else:  # MONTHLY
            return pd.Timestamp(t.year, t.month, 1)

    def run(
        self,
        df_1h: pd.DataFrame,
        symbol: str,
        df_4h: pd.DataFrame = None,
    ) -> BacktestResult:
        """
        Run event-driven backtest on historical data.

        The backtest walks through bars sequentially:
        1. At each bar, check if any armed patterns are confirmed
        2. Manage open trades (check SL, targets, trailing)
        3. At each new bar, scan for new patterns (using a lookback window)
        4. Score and arm new patterns

        Args:
            df_1h: Historical 1H OHLCV with indicators (atr, ema_200, adx)
            symbol: instrument symbol
            df_4h: Historical 4H data (optional, for multi-TF scoring)

        Returns:
            BacktestResult with all trades and metrics
        """
        result = BacktestResult(
            symbol=symbol,
            start_date=df_1h["time"].iloc[0],
            end_date=df_1h["time"].iloc[-1],
        )

        self.equity = self.starting_equity
        armed_patterns: list[dict] = []  # {pattern, armed_bar, pattern_id, pattern_type}
        open_trades: list[BacktestTrade] = []
        highest_since_partial: dict[int, float] = {}  # trade_idx -> price
        lowest_since_partial: dict[int, float] = {}
        trade_counter = 0
        # Track triggered patterns to prevent re-entry on the same pattern
        triggered_pattern_keys: set[tuple] = set()
        # Track recently triggered (symbol, direction) with bar index — matches live
        # recently_triggered cooldown (live main.py:437-441 blocks 24h after arm/trigger)
        recently_triggered: dict[tuple, int] = {}  # (symbol, direction) -> last triggered bar
        TRIGGER_COOLDOWN_BARS = 24  # 24 H1 bars = 24 hours, matching live
        # KZ tracker for Kill Zone Hunt
        kz_tracker = KillZoneTracker() if "KZ_HUNT" in self.enabled_patterns else None

        # News filter: pre-generate high-impact events for the data range
        news_events = []
        if self.simulate_news_blocks:
            news_events = self._generate_news_events(
                df_1h["time"].iloc[0], df_1h["time"].iloc[-1]
            )

        # Circuit breaker state
        cb_tripped_until: dict[str, pd.Timestamp | None] = {
            "DAILY": None, "WEEKLY": None, "MONTHLY": None,
        }
        cb_period_start_equity: dict[str, float] = {}
        cb_period_key: dict[str, str] = {}
        cb_period_pnl: dict[str, float] = {"DAILY": 0.0, "WEEKLY": 0.0, "MONTHLY": 0.0}
        cb_limits = {
            "DAILY": config.DAILY_LOSS_LIMIT_PCT,
            "WEEKLY": config.WEEKLY_LOSS_LIMIT_PCT,
            "MONTHLY": config.MONTHLY_LOSS_LIMIT_PCT,
        }
        # Per-pattern consecutive loss tracking
        pattern_consec_losses: dict[str, int] = {}
        pattern_paused_until_bar: dict[str, int] = {}  # bar_idx when pause expires
        PATTERN_LOSS_PAUSE_THRESHOLD = 3
        PATTERN_PAUSE_BARS = 48  # 48 H1 bars = 48 hours

        # Minimum lookback for indicators and zigzag
        min_lookback = 250
        pip_value = config.PIP_VALUES.get(symbol, 0.0001)

        for bar_idx in range(min_lookback, len(df_1h)):
            bar = df_1h.iloc[bar_idx]

            # ─── Manage open trades ──────────────────────────────────────
            closed_trades = []
            for i, trade in enumerate(open_trades):
                trail_mult = config.TRAILING_STOP_ATR_MULT_BY_PATTERN.get(
                    trade.pattern_type, config.TRAILING_STOP_ATR_MULT
                )
                closed = self._manage_trade(
                    trade, bar, i, highest_since_partial, lowest_since_partial, pip_value,
                    trail_mult=trail_mult,
                )
                if closed:
                    self.equity += trade.pnl_currency
                    result.trades.append(trade)
                    closed_trades.append(i)

                    # Update circuit breaker PnL tracking
                    if self.simulate_circuit_breaker:
                        for level in ("DAILY", "WEEKLY", "MONTHLY"):
                            cb_period_pnl[level] += trade.pnl_currency
                        # Per-pattern consecutive loss tracking
                        pt = trade.pattern_type
                        if trade.pnl_pips > 0:
                            pattern_consec_losses[pt] = 0
                        else:
                            pattern_consec_losses[pt] = pattern_consec_losses.get(pt, 0) + 1
                            if pattern_consec_losses[pt] >= PATTERN_LOSS_PAUSE_THRESHOLD:
                                pattern_paused_until_bar[pt] = bar_idx + PATTERN_PAUSE_BARS

            for i in sorted(closed_trades, reverse=True):
                open_trades.pop(i)
                highest_since_partial.pop(i, None)
                lowest_since_partial.pop(i, None)

            # ─── Update KZ tracker ─────────────────────────────────────
            if kz_tracker and "time" in df_1h.columns:
                kz_tracker.update(bar["time"], bar["high"], bar["low"], bar_idx)

            # ─── Circuit breaker period tracking ──────────────────────────
            if self.simulate_circuit_breaker and hasattr(bar["time"], "year"):
                bar_time = bar["time"]
                for level in ("DAILY", "WEEKLY", "MONTHLY"):
                    period_start = self._get_period_start(bar_time, level)
                    pkey = period_start.isoformat()
                    if cb_period_key.get(level) != pkey:
                        # New period — reset PnL and capture start equity
                        cb_period_pnl[level] = 0.0
                        cb_period_start_equity[level] = self.equity
                        cb_period_key[level] = pkey
                        cb_tripped_until[level] = None

            # ─── Check armed patterns for entry ──────────────────────────
            triggered = []
            for j, arm in enumerate(armed_patterns):
                pattern = arm["pattern"]
                armed_bar = arm["armed_bar"]
                pat_type = arm.get("pattern_type", "HVF")

                # Check expiry (per-pattern freshness)
                expiry = config.PATTERN_FRESHNESS_BARS.get(pat_type, config.PATTERN_EXPIRY_BARS)
                if bar_idx - armed_bar > expiry:
                    triggered.append(j)
                    continue

                # Check entry confirmation based on pattern type
                vol_avg = df_1h["tick_volume"].iloc[max(0, bar_idx - 20):bar_idx].mean()
                confirmed = False

                if pat_type == "HVF":
                    if pattern.direction == "LONG":
                        if bar["close"] > pattern.entry_price and bar["tick_volume"] > vol_avg * config.VOLUME_SPIKE_MULT:
                            confirmed = True
                    else:
                        if bar["close"] < pattern.entry_price and bar["tick_volume"] > vol_avg * config.VOLUME_SPIKE_MULT:
                            confirmed = True
                else:
                    # Viper, KZ Hunt, London Sweep: simple price confirmation
                    if pattern.direction == "LONG":
                        confirmed = bar["close"] > pattern.entry_price
                    else:
                        confirmed = bar["close"] < pattern.entry_price

                if confirmed and len(open_trades) < config.MAX_CONCURRENT_TRADES:
                    # News filter check (matches live risk_manager gate 3)
                    if self.simulate_news_blocks and news_events:
                        if self._is_news_blocked(bar["time"], symbol, news_events):
                            triggered.append(j)
                            continue

                    # Circuit breaker check (matches live risk_manager gate 1)
                    if self.simulate_circuit_breaker:
                        cb_blocked = False
                        for level in ("DAILY", "WEEKLY", "MONTHLY"):
                            base_eq = cb_period_start_equity.get(level, self.starting_equity)
                            if base_eq > 0 and cb_period_pnl[level] < 0:
                                loss_pct = abs(cb_period_pnl[level]) / base_eq * 100.0
                                if loss_pct >= cb_limits[level]:
                                    cb_blocked = True
                                    break
                        if cb_blocked:
                            triggered.append(j)
                            continue
                        # Per-pattern consecutive loss pause
                        if pattern_paused_until_bar.get(pat_type, 0) > bar_idx:
                            triggered.append(j)
                            continue

                    # Same-symbol dedup (matches live risk_manager.py:159-166)
                    already_on_symbol = any(t.symbol == symbol for t in open_trades)
                    if already_on_symbol:
                        triggered.append(j)
                        continue

                    actual_entry = bar["close"]
                    if pattern.direction == "LONG" and actual_entry >= pattern.target_1:
                        triggered.append(j)
                        continue
                    if pattern.direction == "SHORT" and actual_entry <= pattern.target_1:
                        triggered.append(j)
                        continue

                    # Spread simulation: widen SL by typical spread (matches live main.py:729-740)
                    pip_sz = config.PIP_VALUES.get(symbol, 0.0001)
                    spread_price = pip_sz * 1.5  # ~1.5 pip typical spread
                    if pattern.direction == "LONG":
                        adjusted_sl = pattern.stop_loss - spread_price
                    else:
                        adjusted_sl = pattern.stop_loss + spread_price

                    # Position sizing with spread-adjusted SL (per-pattern risk%)
                    stop_dist = abs(actual_entry - adjusted_sl)
                    if stop_dist <= 0:
                        triggered.append(j)
                        continue

                    # Min stop distance guard (matches live main.py:744-762)
                    min_stop_pips = config.MIN_STOP_PIPS_BY_PATTERN.get(pat_type, 5)
                    min_stop_dist = max(spread_price * 5, pip_sz * min_stop_pips)
                    if stop_dist < min_stop_dist:
                        triggered.append(j)
                        continue

                    # RRR check (matches live risk_manager.py:184-195)
                    reward_dist = abs(pattern.target_2 - actual_entry)
                    min_rrr = config.MIN_RRR_BY_PATTERN.get(pat_type, config.HVF_MIN_RRR)
                    if stop_dist > 0 and (reward_dist / stop_dist) < min_rrr:
                        triggered.append(j)
                        continue

                    risk_pct = config.RISK_PCT_BY_PATTERN.get(pat_type, self.risk_pct)
                    lot_size = calculate_lot_size(
                        self.equity, risk_pct, stop_dist, symbol
                    )
                    lot_size = validate_lot_size(lot_size)

                    if lot_size > 0:
                        # Extract invalidation levels from pattern
                        inv_long = 0.0
                        inv_short = 0.0
                        if pat_type == "HVF":
                            inv_long = pattern.l3.price
                            inv_short = pattern.h3.price
                        elif pat_type == "KZ_HUNT":
                            inv_long = pattern.kz_low
                            inv_short = pattern.kz_high

                        trade = BacktestTrade(
                            symbol=symbol,
                            direction=pattern.direction,
                            entry_price=actual_entry,
                            stop_loss=adjusted_sl,
                            target_1=pattern.target_1,
                            target_2=pattern.target_2,
                            lot_size=lot_size,
                            entry_bar=bar_idx,
                            entry_time=bar["time"],
                            score=pattern.score,
                            rrr=pattern.rrr,
                            pattern_type=pat_type,
                            invalidation_long=inv_long,
                            invalidation_short=inv_short,
                        )
                        open_trades.append(trade)
                        trade_counter += 1
                        pat_key = arm.get("pat_key")
                        if pat_key:
                            triggered_pattern_keys.add(pat_key)
                        # Record trigger for cooldown (matches live recently_triggered)
                        recently_triggered[(symbol, pattern.direction)] = bar_idx
                        triggered.append(j)

            for j in sorted(triggered, reverse=True):
                armed_patterns.pop(j)

            # ─── Scan for new patterns ──────────────────────────────────
            # HVF every 4 bars (needs 500-bar zigzag history)
            # Viper every 8 bars (momentum patterns need fast detection)
            # KZ_HUNT, LONDON_SWEEP: every bar (matches live bot behavior)
            scan_hvf = (bar_idx % 4 == 0) and "HVF" in self.enabled_patterns
            scan_viper = (bar_idx % 8 == 0) and "VIPER" in self.enabled_patterns
            non_hvf_patterns = [p for p in self.enabled_patterns if p != "HVF"]
            slow_patterns = [p for p in non_hvf_patterns if p != "VIPER"]
            scan_slow_others = len(slow_patterns) > 0
            scan_others = scan_viper or scan_slow_others
            if not scan_hvf and not scan_viper and not scan_slow_others:
                continue
            window_start = max(0, bar_idx - 499)
            window_df = df_1h.iloc[window_start:bar_idx + 1].reset_index(drop=True)
            # Smaller window for non-HVF detectors (built when Viper or others need it)
            # Exclude current bar from detection (bar_idx) to match live behavior:
            # live uses df_completed = df_1h.iloc[:-1], only scanning completed bars.
            small_window_df = None
            kz_window_df = None
            if scan_viper or scan_slow_others:
                small_window_start = max(0, bar_idx - 199)
                small_window_df = df_1h.iloc[small_window_start:bar_idx].reset_index(drop=True)
                # KZ Hunt needs original indices (kz_tracker stores df_1h bar_idx)
                kz_window_df = df_1h.iloc[small_window_start:bar_idx]

            if len(window_df) >= 100:
                all_candidates: list[dict] = []

                # HVF Detection (every 4 bars)
                if scan_hvf and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("HVF", []):
                    pivots = compute_zigzag(window_df, config.ZIGZAG_ATR_MULTIPLIER)
                    if len(pivots) >= 6:
                        hvf_patterns = detect_hvf_patterns(
                            df=window_df, symbol=symbol,
                            timeframe=config.PRIMARY_TIMEFRAME,
                            pivots=pivots, df_4h=df_4h,
                        )
                        for p in hvf_patterns:
                            pat_key = (round(p.h3.price, 5), round(p.l3.price, 5), p.direction, "HVF")
                            if pat_key in triggered_pattern_keys:
                                continue
                            already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                            if already_armed:
                                continue
                            p.score = score_pattern(p, window_df, df_4h)
                            threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("HVF", self.score_threshold)
                            if p.score >= threshold:
                                all_candidates.append({
                                    "pattern": p, "pattern_type": "HVF",
                                    "symbol": symbol, "direction": p.direction,
                                    "score": p.score, "pat_key": pat_key,
                                })

                # Viper Detection (every 8 bars, 200-bar window)
                if scan_viper and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("VIPER", []):
                    viper_pats = detect_viper_patterns(small_window_df, symbol, config.PRIMARY_TIMEFRAME)
                    for p in viper_pats:
                        # Direction filter (SHORT-only Viper)
                        allowed_dir = config.ALLOWED_DIRECTIONS_BY_PATTERN.get("VIPER")
                        if allowed_dir and p.direction != allowed_dir:
                            continue
                        pat_key = (round(p.entry_price, 5), round(p.stop_loss, 5), p.direction, "VIPER")
                        if pat_key in triggered_pattern_keys:
                            continue
                        already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                        if already_armed:
                            continue
                        p.score = score_viper(p, small_window_df)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("VIPER", 50)
                        if p.score >= threshold:
                            all_candidates.append({
                                "pattern": p, "pattern_type": "VIPER",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score, "pat_key": pat_key,
                            })

                # KZ Hunt Detection (every 24 bars, 200-bar window)
                if scan_slow_others and "KZ_HUNT" in self.enabled_patterns and kz_tracker and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("KZ_HUNT", []):
                    kz_pats = detect_kz_hunt_patterns(
                        kz_window_df, symbol, config.PRIMARY_TIMEFRAME, kz_tracker,
                    )
                    for p in kz_pats:
                        # Direction filter (LONG-only KZ Hunt)
                        allowed_dir = config.ALLOWED_DIRECTIONS_BY_PATTERN.get("KZ_HUNT")
                        if allowed_dir and p.direction != allowed_dir:
                            continue
                        pat_key = (round(p.entry_price, 5), round(p.kz_high, 5), p.direction, "KZ_HUNT")
                        if pat_key in triggered_pattern_keys:
                            continue
                        already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                        if already_armed:
                            continue
                        p.score = score_kz_hunt(p, kz_window_df)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("KZ_HUNT", 50)
                        if p.score >= threshold:
                            all_candidates.append({
                                "pattern": p, "pattern_type": "KZ_HUNT",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score, "pat_key": pat_key,
                            })

                # London Sweep Detection (every 24 bars, 200-bar window, London hours 6-11 UTC)
                bar_hour = bar["time"].hour if hasattr(bar["time"], "hour") else 0
                if scan_slow_others and "LONDON_SWEEP" in self.enabled_patterns and 6 <= bar_hour <= 11 and symbol not in config.PATTERN_SYMBOL_EXCLUSIONS.get("LONDON_SWEEP", []):
                    ls_pats = detect_london_sweep_patterns(small_window_df, symbol, config.PRIMARY_TIMEFRAME)
                    for p in ls_pats:
                        pat_key = (round(p.entry_price, 5), round(p.asian_high, 5), p.direction, "LONDON_SWEEP")
                        if pat_key in triggered_pattern_keys:
                            continue
                        already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                        if already_armed:
                            continue
                        p.score = score_london_sweep(p, small_window_df)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("LONDON_SWEEP", 50)
                        if p.score >= threshold:
                            all_candidates.append({
                                "pattern": p, "pattern_type": "LONDON_SWEEP",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score, "pat_key": pat_key,
                            })

                # Prioritize and arm (matches live main.py:443-463)
                prioritized = prioritize_signals(all_candidates)
                active_armed = {
                    (a["pattern"].symbol, a["pattern"].direction)
                    for a in armed_patterns
                }
                for sig in prioritized:
                    sym_dir = (sig.symbol, sig.direction)
                    # Same-symbol+direction dedup: skip if already armed
                    if sym_dir in active_armed:
                        continue
                    # Recently triggered cooldown (matches live recently_triggered check)
                    last_triggered_bar = recently_triggered.get(sym_dir, -9999)
                    if bar_idx - last_triggered_bar < TRIGGER_COOLDOWN_BARS:
                        continue
                    armed_patterns.append({
                        "pattern": sig.pattern,
                        "armed_bar": bar_idx,
                        "pattern_id": trade_counter,
                        "pattern_type": sig.pattern_type,
                        "pat_key": next(
                            (c["pat_key"] for c in all_candidates
                             if c["pattern"] is sig.pattern), None
                        ),
                    })
                    # Record arm for cooldown (live treats ARMED same as TRIGGERED)
                    recently_triggered[sym_dir] = bar_idx
                    active_armed.add(sym_dir)

        # Close any remaining open trades at last bar
        last_bar = df_1h.iloc[-1]
        for trade in open_trades:
            trade.exit_price = last_bar["close"]
            trade.exit_bar = len(df_1h) - 1
            trade.exit_time = last_bar["time"]
            trade.exit_reason = "END_OF_DATA"
            self._calc_pnl(trade, pip_value)
            self.equity += trade.pnl_currency
            result.trades.append(trade)

        result.compute_metrics(self.starting_equity)
        return result

    def _manage_trade(
        self,
        trade: BacktestTrade,
        bar: pd.Series,
        trade_idx: int,
        highest_since_partial: dict,
        lowest_since_partial: dict,
        pip_value: float,
        trail_mult: float = None,
    ) -> bool:
        """
        Manage an open trade for a single bar.
        Returns True if trade was closed.
        """
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]

        bar_idx = bar.name if isinstance(bar.name, int) else 0
        bars_since_entry = bar_idx - trade.entry_bar

        # Track max favourable/adverse excursion
        if trade.direction == "LONG":
            fav = (high - trade.entry_price) / pip_value
            adv = (trade.entry_price - low) / pip_value
        else:
            fav = (trade.entry_price - low) / pip_value
            adv = (high - trade.entry_price) / pip_value
        trade.max_favourable = max(trade.max_favourable, fav)
        trade.max_adverse = max(trade.max_adverse, adv)

        # ─── Check invalidation (after 2-bar grace period) ──────────
        if bars_since_entry >= 2 and not trade.partial_closed:
            invalidated = False
            if trade.direction == "LONG" and trade.invalidation_long > 0 and low <= trade.invalidation_long:
                invalidated = True
                trade.exit_price = trade.invalidation_long
            elif trade.direction == "SHORT" and trade.invalidation_short > 0 and high >= trade.invalidation_short:
                invalidated = True
                trade.exit_price = trade.invalidation_short

            if invalidated:
                trade.exit_bar = bar_idx
                trade.exit_time = bar["time"]
                trade.exit_reason = "INVALIDATION"
                self._calc_pnl(trade, pip_value)
                return True

        # ─── Check stop loss ─────────────────────────────────────────
        current_sl = trade.stop_loss
        _trail_mult = trail_mult if trail_mult is not None else config.TRAILING_STOP_ATR_MULT
        if trade.partial_closed:
            # Use trailing SL if available (pattern-specific multiplier)
            if trade.direction == "LONG":
                trail_highest = highest_since_partial.get(trade_idx, trade.entry_price)
                atr = bar.get("atr", 0)
                if atr > 0:
                    trailing_sl = trail_highest - _trail_mult * atr
                    current_sl = max(current_sl, trailing_sl)
            else:
                trail_lowest = lowest_since_partial.get(trade_idx, trade.entry_price)
                atr = bar.get("atr", 0)
                if atr > 0:
                    trailing_sl = trail_lowest + _trail_mult * atr
                    current_sl = min(current_sl, trailing_sl)

        sl_hit = False
        if trade.direction == "LONG" and low <= current_sl:
            sl_hit = True
            trade.exit_price = current_sl
        elif trade.direction == "SHORT" and high >= current_sl:
            sl_hit = True
            trade.exit_price = current_sl

        if sl_hit:
            trade.exit_bar = bar.name if isinstance(bar.name, int) else 0
            trade.exit_time = bar["time"]
            trade.exit_reason = "TRAILING_STOP" if trade.partial_closed else "STOP_LOSS"
            self._calc_pnl(trade, pip_value)
            return True

        # ─── Check target 2 (full close) ─────────────────────────────
        # Use bar close (not high/low) to match live split-order behavior
        # where T2 is detected via 30s price snapshots, not intra-bar wicks.
        if trade.direction == "LONG" and close >= trade.target_2:
            trade.exit_price = trade.target_2
            trade.exit_bar = bar.name if isinstance(bar.name, int) else 0
            trade.exit_time = bar["time"]
            trade.exit_reason = "TARGET_2"
            self._calc_pnl(trade, pip_value)
            return True
        elif trade.direction == "SHORT" and close <= trade.target_2:
            trade.exit_price = trade.target_2
            trade.exit_bar = bar.name if isinstance(bar.name, int) else 0
            trade.exit_time = bar["time"]
            trade.exit_reason = "TARGET_2"
            self._calc_pnl(trade, pip_value)
            return True

        # ─── Check target 1 (partial close simulation) ───────────────
        # Use bar high/low here because live now places a limit order at T1
        # (split-order approach), so MT5 catches T1 at tick level — matching
        # the bar high/low check which also catches intra-bar touches.
        if not trade.partial_closed:
            if trade.direction == "LONG" and high >= trade.target_1:
                trade.partial_closed = True
                trade.partial_price = trade.target_1
                # Move SL to breakeven
                trade.stop_loss = trade.entry_price
                # Init trailing tracker
                highest_since_partial[trade_idx] = high
            elif trade.direction == "SHORT" and low <= trade.target_1:
                trade.partial_closed = True
                trade.partial_price = trade.target_1
                trade.stop_loss = trade.entry_price
                lowest_since_partial[trade_idx] = low
        else:
            # Update trailing trackers
            if trade.direction == "LONG":
                prev = highest_since_partial.get(trade_idx, high)
                highest_since_partial[trade_idx] = max(prev, high)
            else:
                prev = lowest_since_partial.get(trade_idx, low)
                lowest_since_partial[trade_idx] = min(prev, low)

        return False

    def _calc_pnl(self, trade: BacktestTrade, pip_value: float):
        """Calculate PnL for a closed trade."""
        if trade.direction == "LONG":
            raw_pips = (trade.exit_price - trade.entry_price) / pip_value
        else:
            raw_pips = (trade.entry_price - trade.exit_price) / pip_value

        # Account for partial close at T1
        partial_pct = config.PARTIAL_CLOSE_PCT
        if trade.partial_closed and trade.exit_reason != "STOP_LOSS":
            if trade.direction == "LONG":
                partial_pips = (trade.partial_price - trade.entry_price) / pip_value
                remaining_pips = (trade.exit_price - trade.entry_price) / pip_value
            else:
                partial_pips = (trade.entry_price - trade.partial_price) / pip_value
                remaining_pips = (trade.entry_price - trade.exit_price) / pip_value
            trade.pnl_pips = (partial_pips * partial_pct) + (remaining_pips * (1 - partial_pct))
        else:
            trade.pnl_pips = raw_pips

        # Approximate currency PnL (simplified)
        contract_size = 100000
        trade.pnl_currency = trade.pnl_pips * pip_value * trade.lot_size * contract_size
