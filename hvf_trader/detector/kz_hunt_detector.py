"""
Kill Zone Hunt Detector — session reversal at KZ extremes.

Pattern: Price reaches KZ extreme → rejection candle → reversal.
Expected frequency: ~2-5 trades/week/pair.

Rules:
1. Track KZ high/low during each Kill Zone period
2. Lock levels when KZ ends
3. Rejection candle at KZ extreme (wick > 2x body)
4. SL beyond KZ extreme + 0.5 * ATR
5. T1 = opposite KZ extreme, T2 = 1.5x KZ range
6. Direction aligns with EMA200
"""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config
from hvf_trader.detector.killzone_tracker import KillZoneTracker, KZLevels

logger = logging.getLogger(__name__)


@dataclass
class KZHuntPattern:
    symbol: str
    timeframe: str
    direction: str  # 'LONG' or 'SHORT'

    # KZ context
    kz_name: str
    kz_high: float
    kz_low: float
    kz_range: float

    # Rejection candle
    rejection_bar_idx: int
    rejection_price: float  # Close of rejection candle

    # Trade levels
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    rrr: float = 0.0

    # Metadata
    detected_at: Optional[pd.Timestamp] = None
    score: float = 0.0
    status: str = "DETECTED"
    pattern_type: str = "KZ_HUNT"

    def compute_levels(self, current_atr: float):
        """Calculate entry, SL, targets from KZ extremes.

        If config.FLAT_TP_PIPS_BY_PATTERN sets a flat pip TP for this pattern
        type, target_1 and target_2 are overridden to that fixed distance from
        entry — disabling the KZ-extreme-derived dynamic targets. This pairs
        with SPLIT_ORDER_BY_PATTERN=False for pure broker-side TP/SL exit.
        """
        from hvf_trader import config
        atr_buffer = getattr(config, "KZ_HUNT_SL_ATR_BUFFER", 0.5) * current_atr

        if self.direction == "LONG":
            # Reversal from KZ low — long entry
            self.entry_price = self.rejection_price
            self.stop_loss = self.kz_low - atr_buffer
            self.target_1 = self.kz_high  # Opposite KZ extreme
            self.target_2 = self.rejection_price + (self.kz_range * 1.5)
        else:
            # Reversal from KZ high — short entry
            self.entry_price = self.rejection_price
            self.stop_loss = self.kz_high + atr_buffer
            self.target_1 = self.kz_low
            self.target_2 = self.rejection_price - (self.kz_range * 1.5)

        # Flat-TP override (e.g., KZ_HUNT @ 20p)
        flat_tp_pips = config.FLAT_TP_PIPS_BY_PATTERN.get(self.pattern_type, 0)
        if flat_tp_pips and flat_tp_pips > 0:
            pip = config.PIP_VALUES.get(getattr(self, "symbol", ""), 0.0001)
            tp_distance = flat_tp_pips * pip
            if self.direction == "LONG":
                self.target_1 = self.entry_price + tp_distance
                self.target_2 = self.target_1
            else:
                self.target_1 = self.entry_price - tp_distance
                self.target_2 = self.target_1

        # Geometric validity: SL must be on the loss side of entry. If the
        # rejection candle closes past `kz_extreme + atr_buffer` (i.e., the
        # bearish rejection didn't return inside the KZ range from above,
        # or the bullish rejection from below), the computed SL ends up in
        # profit direction — invalid pattern. Set rrr=0 so the detector's
        # MIN_RRR filter drops it cleanly.
        # Toggleable via KZ_HUNT_ENFORCE_VALID_GEOMETRY for A/B studies.
        if getattr(config, "KZ_HUNT_ENFORCE_VALID_GEOMETRY", True):
            invalid_short = (
                self.direction == "SHORT" and self.stop_loss <= self.entry_price
            )
            invalid_long = (
                self.direction == "LONG" and self.stop_loss >= self.entry_price
            )
            if invalid_short or invalid_long:
                self.rrr = 0.0
                return

        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_2 - self.entry_price)
        self.rrr = reward / risk if risk > 0 else 0.0


def detect_kz_hunt_patterns(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    kz_tracker: KillZoneTracker,
) -> list[KZHuntPattern]:
    """
    Scan for Kill Zone Hunt reversal patterns.

    Args:
        df: OHLCV DataFrame with 'atr', 'ema_200' columns
        symbol: instrument symbol
        timeframe: e.g. 'H1'
        kz_tracker: KillZoneTracker with populated KZ levels

    Returns:
        List of valid KZHuntPattern objects
    """
    if len(df) < 30:
        return []
    if "atr" not in df.columns:
        return []

    patterns: list[KZHuntPattern] = []
    completed_kzs = kz_tracker.get_all_completed()

    if not completed_kzs:
        return []

    last_bar = df.index[-1]

    # Check each completed KZ for rejection patterns in the bars after it ended
    for kz_name, kz_levels in completed_kzs.items():
        kz_range = kz_levels.high - kz_levels.low
        if kz_range <= 0:
            continue
        if kz_levels.bar_count < 2:
            continue

        # Scan bars after KZ ended (within 30 bars)
        search_start = max(kz_levels.high_idx, kz_levels.low_idx) + 1
        search_end = min(search_start + 30, last_bar + 1)

        for i in range(search_start, search_end):
            if i not in df.index:
                continue
            bar = df.loc[i]
            atr = bar.get("atr", 0)
            if np.isnan(atr) or atr <= 0:
                continue

            # SHORT — bearish rejection at KZ HIGH.
            # ICT/Hunt sweep semantics: bar must have actually TAKEN OUT the
            # prior KZ high (true stop-run) AND closed back inside the range.
            # An "approach + wick" without a sweep is a different (weaker)
            # population and conflates non-sweep tests with real liquidity
            # grabs, which is the prevailing hypothesis for the live PF
            # collapse from 1.53 backtest to 0.79 live.
            require_sweep = config.KZ_HUNT_REQUIRE_SWEEP
            short_trigger = (
                (bar["high"] > kz_levels.high and bar["close"] <= kz_levels.high)
                if require_sweep
                else (bar["high"] >= kz_levels.high - (0.3 * atr))
            )
            if short_trigger and _is_rejection_candle(bar, "BEARISH"):
                pattern = KZHuntPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    kz_name=kz_name,
                    kz_high=kz_levels.high,
                    kz_low=kz_levels.low,
                    kz_range=kz_range,
                    rejection_bar_idx=i,
                    rejection_price=bar["close"],
                    detected_at=bar["time"] if "time" in df.columns else None,
                )
                pattern.compute_levels(float(atr))
                if pattern.rrr >= config.MIN_RRR_BY_PATTERN.get("KZ_HUNT", config.HVF_MIN_RRR):
                    patterns.append(pattern)

            # LONG — bullish rejection at KZ LOW (mirror).
            long_trigger = (
                (bar["low"] < kz_levels.low and bar["close"] >= kz_levels.low)
                if require_sweep
                else (bar["low"] <= kz_levels.low + (0.3 * atr))
            )
            if long_trigger and _is_rejection_candle(bar, "BULLISH"):
                pattern = KZHuntPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    kz_name=kz_name,
                    kz_high=kz_levels.high,
                    kz_low=kz_levels.low,
                    kz_range=kz_range,
                    rejection_bar_idx=i,
                    rejection_price=bar["close"],
                    detected_at=bar["time"] if "time" in df.columns else None,
                )
                pattern.compute_levels(float(atr))
                if pattern.rrr >= config.MIN_RRR_BY_PATTERN.get("KZ_HUNT", config.HVF_MIN_RRR):
                    patterns.append(pattern)

    # Filter stale (last_bar is an original df index, not positional)
    patterns = [
        p for p in patterns
        if (last_bar - p.rejection_bar_idx) <= config.PATTERN_FRESHNESS_BARS.get("KZ_HUNT", config.PATTERN_EXPIRY_BARS)
    ]

    patterns.sort(
        key=lambda p: p.detected_at if p.detected_at else pd.Timestamp.min,
        reverse=True,
    )
    return patterns


def _is_rejection_candle(bar: pd.Series, rejection_type: str) -> bool:
    """
    Check if bar is a rejection candle.
    Rejection = wick > 2x body.

    BULLISH rejection: long lower wick (price rejected downside)
    BEARISH rejection: long upper wick (price rejected upside)
    """
    body = abs(bar["close"] - bar["open"])
    if body == 0:
        body = 0.00001  # Avoid division by zero

    if rejection_type == "BULLISH":
        lower_wick = min(bar["open"], bar["close"]) - bar["low"]
        return lower_wick > 2.0 * body
    else:  # BEARISH
        upper_wick = bar["high"] - max(bar["open"], bar["close"])
        return upper_wick > 2.0 * body


def check_kz_hunt_entry_confirmation(
    pattern: KZHuntPattern,
    latest_bar: pd.Series,
) -> bool:
    """Check if latest bar confirms KZ Hunt entry."""
    close_price = latest_bar.get("close", None)
    if close_price is None:
        return False

    if pattern.direction == "LONG":
        return float(close_price) > pattern.entry_price
    else:
        return float(close_price) < pattern.entry_price
