"""
Event-driven backtester that reuses the detector and risk code.
"""

import logging
from datetime import datetime, timezone
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
    ):
        self.starting_equity = starting_equity
        self.risk_pct = risk_pct or config.RISK_PCT
        self.score_threshold = score_threshold or config.SCORE_THRESHOLD
        self.equity = starting_equity
        # Which pattern types to detect. Default: HVF only (backward compatible)
        self.enabled_patterns = enabled_patterns or ["HVF"]

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
        # KZ tracker for Kill Zone Hunt
        kz_tracker = KillZoneTracker() if "KZ_HUNT" in self.enabled_patterns else None

        # Minimum lookback for indicators and zigzag
        min_lookback = 250
        pip_value = config.PIP_VALUES.get(symbol, 0.0001)

        for bar_idx in range(min_lookback, len(df_1h)):
            bar = df_1h.iloc[bar_idx]

            # ─── Manage open trades ──────────────────────────────────────
            closed_trades = []
            for i, trade in enumerate(open_trades):
                closed = self._manage_trade(
                    trade, bar, i, highest_since_partial, lowest_since_partial, pip_value
                )
                if closed:
                    self.equity += trade.pnl_currency
                    result.trades.append(trade)
                    closed_trades.append(i)

            for i in sorted(closed_trades, reverse=True):
                open_trades.pop(i)
                highest_since_partial.pop(i, None)
                lowest_since_partial.pop(i, None)

            # ─── Update KZ tracker ─────────────────────────────────────
            if kz_tracker and "time" in df_1h.columns:
                kz_tracker.update(bar["time"], bar["high"], bar["low"], bar_idx)

            # ─── Check armed patterns for entry ──────────────────────────
            triggered = []
            for j, arm in enumerate(armed_patterns):
                pattern = arm["pattern"]
                armed_bar = arm["armed_bar"]
                pat_type = arm.get("pattern_type", "HVF")

                # Check expiry
                if bar_idx - armed_bar > config.PATTERN_EXPIRY_BARS:
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
                    actual_entry = bar["close"]
                    if pattern.direction == "LONG" and actual_entry >= pattern.target_1:
                        triggered.append(j)
                        continue
                    if pattern.direction == "SHORT" and actual_entry <= pattern.target_1:
                        triggered.append(j)
                        continue

                    # Position sizing (per-pattern risk%)
                    stop_dist = abs(actual_entry - pattern.stop_loss)
                    if stop_dist <= 0:
                        triggered.append(j)
                        continue
                    risk_pct = config.RISK_PCT_BY_PATTERN.get(pat_type, self.risk_pct)
                    lot_size = calculate_lot_size(
                        self.equity, risk_pct, stop_dist, symbol
                    )
                    lot_size = validate_lot_size(lot_size)

                    if lot_size > 0:
                        trade = BacktestTrade(
                            symbol=symbol,
                            direction=pattern.direction,
                            entry_price=actual_entry,
                            stop_loss=pattern.stop_loss,
                            target_1=pattern.target_1,
                            target_2=pattern.target_2,
                            lot_size=lot_size,
                            entry_bar=bar_idx,
                            entry_time=bar["time"],
                            score=pattern.score,
                            rrr=pattern.rrr,
                            pattern_type=pat_type,
                        )
                        open_trades.append(trade)
                        trade_counter += 1
                        pat_key = arm.get("pat_key")
                        if pat_key:
                            triggered_pattern_keys.add(pat_key)
                        triggered.append(j)

            for j in sorted(triggered, reverse=True):
                armed_patterns.pop(j)

            # ─── Scan for new patterns (every 4 bars to limit CPU) ────────
            if bar_idx % 4 != 0:
                continue
            window_start = max(0, bar_idx - 499)
            window_df = df_1h.iloc[window_start:bar_idx + 1].reset_index(drop=True)

            if len(window_df) >= 100:
                all_candidates: list[dict] = []

                # HVF Detection
                if "HVF" in self.enabled_patterns:
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

                # Viper Detection
                if "VIPER" in self.enabled_patterns:
                    viper_pats = detect_viper_patterns(window_df, symbol, config.PRIMARY_TIMEFRAME)
                    for p in viper_pats:
                        pat_key = (round(p.entry_price, 5), round(p.stop_loss, 5), p.direction, "VIPER")
                        if pat_key in triggered_pattern_keys:
                            continue
                        already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                        if already_armed:
                            continue
                        p.score = score_viper(p, window_df)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("VIPER", 50)
                        if p.score >= threshold:
                            all_candidates.append({
                                "pattern": p, "pattern_type": "VIPER",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score, "pat_key": pat_key,
                            })

                # KZ Hunt Detection
                if "KZ_HUNT" in self.enabled_patterns and kz_tracker:
                    kz_pats = detect_kz_hunt_patterns(
                        window_df, symbol, config.PRIMARY_TIMEFRAME, kz_tracker,
                    )
                    for p in kz_pats:
                        pat_key = (round(p.entry_price, 5), round(p.kz_high, 5), p.direction, "KZ_HUNT")
                        if pat_key in triggered_pattern_keys:
                            continue
                        already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                        if already_armed:
                            continue
                        p.score = score_kz_hunt(p, window_df)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("KZ_HUNT", 50)
                        if p.score >= threshold:
                            all_candidates.append({
                                "pattern": p, "pattern_type": "KZ_HUNT",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score, "pat_key": pat_key,
                            })

                # London Sweep Detection (only during London hours 6-11 UTC)
                bar_hour = bar["time"].hour if hasattr(bar["time"], "hour") else 0
                if "LONDON_SWEEP" in self.enabled_patterns and 6 <= bar_hour <= 11:
                    ls_pats = detect_london_sweep_patterns(window_df, symbol, config.PRIMARY_TIMEFRAME)
                    for p in ls_pats:
                        pat_key = (round(p.entry_price, 5), round(p.asian_high, 5), p.direction, "LONDON_SWEEP")
                        if pat_key in triggered_pattern_keys:
                            continue
                        already_armed = any(a.get("pat_key") == pat_key for a in armed_patterns)
                        if already_armed:
                            continue
                        p.score = score_london_sweep(p, window_df)
                        threshold = config.SCORE_THRESHOLD_BY_PATTERN.get("LONDON_SWEEP", 50)
                        if p.score >= threshold:
                            all_candidates.append({
                                "pattern": p, "pattern_type": "LONDON_SWEEP",
                                "symbol": symbol, "direction": p.direction,
                                "score": p.score, "pat_key": pat_key,
                            })

                # Prioritize and arm
                prioritized = prioritize_signals(all_candidates)
                for sig in prioritized:
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
    ) -> bool:
        """
        Manage an open trade for a single bar.
        Returns True if trade was closed.
        """
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]

        # Track max favourable/adverse excursion
        if trade.direction == "LONG":
            fav = (high - trade.entry_price) / pip_value
            adv = (trade.entry_price - low) / pip_value
        else:
            fav = (trade.entry_price - low) / pip_value
            adv = (high - trade.entry_price) / pip_value
        trade.max_favourable = max(trade.max_favourable, fav)
        trade.max_adverse = max(trade.max_adverse, adv)

        # ─── Check stop loss ─────────────────────────────────────────
        current_sl = trade.stop_loss
        if trade.partial_closed:
            # Use trailing SL if available
            if trade.direction == "LONG":
                trail_highest = highest_since_partial.get(trade_idx, trade.entry_price)
                atr = bar.get("atr", 0)
                if atr > 0:
                    trailing_sl = trail_highest - config.TRAILING_STOP_ATR_MULT * atr
                    current_sl = max(current_sl, trailing_sl)
            else:
                trail_lowest = lowest_since_partial.get(trade_idx, trade.entry_price)
                atr = bar.get("atr", 0)
                if atr > 0:
                    trailing_sl = trail_lowest + config.TRAILING_STOP_ATR_MULT * atr
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
        if trade.direction == "LONG" and high >= trade.target_2:
            trade.exit_price = trade.target_2
            trade.exit_bar = bar.name if isinstance(bar.name, int) else 0
            trade.exit_time = bar["time"]
            trade.exit_reason = "TARGET_2"
            self._calc_pnl(trade, pip_value)
            return True
        elif trade.direction == "SHORT" and low <= trade.target_2:
            trade.exit_price = trade.target_2
            trade.exit_bar = bar.name if isinstance(bar.name, int) else 0
            trade.exit_time = bar["time"]
            trade.exit_reason = "TARGET_2"
            self._calc_pnl(trade, pip_value)
            return True

        # ─── Check target 1 (partial close simulation) ───────────────
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

        # Account for partial close: 50% at target_1, 50% at exit
        if trade.partial_closed and trade.exit_reason != "STOP_LOSS":
            if trade.direction == "LONG":
                partial_pips = (trade.partial_price - trade.entry_price) / pip_value
                remaining_pips = (trade.exit_price - trade.entry_price) / pip_value
            else:
                partial_pips = (trade.entry_price - trade.partial_price) / pip_value
                remaining_pips = (trade.entry_price - trade.exit_price) / pip_value
            trade.pnl_pips = (partial_pips * 0.5) + (remaining_pips * 0.5)
        else:
            trade.pnl_pips = raw_pips

        # Approximate currency PnL (simplified)
        contract_size = 100000
        trade.pnl_currency = trade.pnl_pips * pip_value * trade.lot_size * contract_size
