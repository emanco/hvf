"""
Viper Pattern Detector — momentum/continuation setup.

Pattern: strong impulse → shallow Fibonacci retracement → continuation.
Expected frequency: ~10-15 trades/year/pair.

Rules:
1. Impulse > 2.0 * ATR(14) within 5 bars
2. Retracement 23.6%-61.8% Fibonacci
3. RSI stays above 40 (bull) / below 60 (bear) during retrace
4. Entry: candle closes past 50% Fib + MACD confirms
5. SL: beyond 78.6% Fib + 0.3 * ATR
6. T1: 100% extension, T2: 161.8% extension
"""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config

logger = logging.getLogger(__name__)

# Fibonacci levels
FIB_236 = 0.236
FIB_382 = 0.382
FIB_500 = 0.500
FIB_618 = 0.618
FIB_786 = 0.786
FIB_EXT_100 = 1.000
FIB_EXT_161 = 1.618


@dataclass
class ViperPattern:
    symbol: str
    timeframe: str
    direction: str  # 'LONG' or 'SHORT'

    # Impulse leg
    impulse_start_idx: int
    impulse_start_price: float
    impulse_end_idx: int
    impulse_end_price: float
    impulse_range: float

    # Retracement leg
    retrace_end_idx: int
    retrace_end_price: float
    retrace_fib_level: float  # Actual fib level of retracement

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
    pattern_type: str = "VIPER"

    def compute_levels(self, current_atr: float):
        """Calculate entry, SL, targets from Fibonacci extensions."""
        atr_buffer = 0.3 * current_atr

        if self.direction == "LONG":
            # Entry at retrace end (candle must close above 50% fib)
            self.entry_price = self.retrace_end_price
            # SL below 78.6% retracement + ATR buffer
            fib_786_price = self.impulse_end_price - (
                self.impulse_range * FIB_786
            )
            self.stop_loss = fib_786_price - atr_buffer
            # Targets: 100% and 161.8% extension from retrace low
            self.target_1 = self.retrace_end_price + (
                self.impulse_range * FIB_EXT_100
            )
            self.target_2 = self.retrace_end_price + (
                self.impulse_range * FIB_EXT_161
            )
        else:  # SHORT
            self.entry_price = self.retrace_end_price
            fib_786_price = self.impulse_end_price + (
                self.impulse_range * FIB_786
            )
            self.stop_loss = fib_786_price + atr_buffer
            self.target_1 = self.retrace_end_price - (
                self.impulse_range * FIB_EXT_100
            )
            self.target_2 = self.retrace_end_price - (
                self.impulse_range * FIB_EXT_161
            )

        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_2 - self.entry_price)
        self.rrr = reward / risk if risk > 0 else 0.0


def detect_viper_patterns(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> list[ViperPattern]:
    """
    Scan for Viper momentum/continuation patterns.

    Args:
        df: OHLCV DataFrame with 'atr', 'rsi', 'macd', 'macd_signal' columns
        symbol: instrument symbol
        timeframe: e.g. 'H1'

    Returns:
        List of valid ViperPattern objects sorted by detection time descending
    """
    required_cols = {"atr", "rsi", "macd", "macd_signal"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        logger.warning("Viper detector missing columns: %s", missing)
        return []

    if len(df) < 50:
        return []

    patterns: list[ViperPattern] = []
    min_impulse_bars = 2
    max_impulse_bars = 5
    max_retrace_bars = 15
    last_bar = len(df) - 1

    # Scan from enough lookback to current
    for i in range(30, last_bar - max_retrace_bars):
        atr = df["atr"].iloc[i]
        if np.isnan(atr) or atr <= 0:
            continue

        min_impulse = 2.0 * atr

        # Check for BULLISH impulse: strong up-move
        for lookback in range(min_impulse_bars, max_impulse_bars + 1):
            start_idx = i - lookback
            if start_idx < 0:
                continue

            impulse_low = df["low"].iloc[start_idx:i + 1].min()
            impulse_low_idx = df["low"].iloc[start_idx:i + 1].idxmin()
            impulse_high = df["high"].iloc[start_idx:i + 1].max()
            impulse_high_idx = df["high"].iloc[start_idx:i + 1].idxmax()

            # Bullish impulse: low comes before high
            if impulse_high_idx > impulse_low_idx:
                impulse_range = impulse_high - impulse_low
                if impulse_range >= min_impulse:
                    pattern = _check_bullish_retrace(
                        df, symbol, timeframe,
                        impulse_low_idx, impulse_low,
                        impulse_high_idx, impulse_high,
                        impulse_range, i, max_retrace_bars,
                    )
                    if pattern:
                        patterns.append(pattern)
                        break  # Don't overlap lookback windows

            # Bearish impulse: high comes before low
            if impulse_low_idx > impulse_high_idx:
                impulse_range = impulse_high - impulse_low
                if impulse_range >= min_impulse:
                    pattern = _check_bearish_retrace(
                        df, symbol, timeframe,
                        impulse_high_idx, impulse_high,
                        impulse_low_idx, impulse_low,
                        impulse_range, i, max_retrace_bars,
                    )
                    if pattern:
                        patterns.append(pattern)
                        break

    # Deduplicate: remove patterns with overlapping impulse legs
    patterns = _deduplicate_vipers(patterns)

    # Filter stale patterns
    patterns = [
        p for p in patterns
        if (last_bar - p.retrace_end_idx) <= config.PATTERN_EXPIRY_BARS
    ]

    patterns.sort(
        key=lambda p: p.detected_at if p.detected_at else pd.Timestamp.min,
        reverse=True,
    )
    return patterns


def _check_bullish_retrace(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    impulse_start_idx: int,
    impulse_start_price: float,
    impulse_end_idx: int,
    impulse_end_price: float,
    impulse_range: float,
    scan_bar: int,
    max_retrace_bars: int,
) -> Optional[ViperPattern]:
    """Check for valid bullish retracement after an up-impulse."""
    retrace_end = min(impulse_end_idx + max_retrace_bars, len(df) - 1)

    # Find the lowest point after impulse end (retracement low)
    retrace_slice = df.iloc[impulse_end_idx + 1:retrace_end + 1]
    if len(retrace_slice) < 2:
        return None

    retrace_low_pos = retrace_slice["low"].idxmin()
    retrace_low_price = df["low"].iloc[retrace_low_pos]

    # Check Fibonacci retracement level (23.6% to 61.8%)
    retrace_depth = impulse_end_price - retrace_low_price
    if impulse_range <= 0:
        return None
    fib_level = retrace_depth / impulse_range

    if not (FIB_236 <= fib_level <= FIB_618):
        return None

    # Check RSI stays above 40 during retracement
    rsi_slice = df["rsi"].iloc[impulse_end_idx:retrace_low_pos + 1]
    if rsi_slice.dropna().min() < 40:
        return None

    # Check for MACD confirmation at retrace end (MACD > signal = bullish)
    if retrace_low_pos < len(df):
        macd_val = df["macd"].iloc[retrace_low_pos]
        macd_sig = df["macd_signal"].iloc[retrace_low_pos]
        if np.isnan(macd_val) or np.isnan(macd_sig):
            return None
        if macd_val <= macd_sig:
            return None

    # Check candle closes above 50% Fib level
    fib_50_price = impulse_end_price - (impulse_range * FIB_500)
    close_at_retrace = df["close"].iloc[retrace_low_pos]
    if close_at_retrace < fib_50_price:
        return None

    atr = df["atr"].iloc[retrace_low_pos]
    if np.isnan(atr):
        return None

    pattern = ViperPattern(
        symbol=symbol,
        timeframe=timeframe,
        direction="LONG",
        impulse_start_idx=impulse_start_idx,
        impulse_start_price=impulse_start_price,
        impulse_end_idx=impulse_end_idx,
        impulse_end_price=impulse_end_price,
        impulse_range=impulse_range,
        retrace_end_idx=retrace_low_pos,
        retrace_end_price=close_at_retrace,
        retrace_fib_level=fib_level,
        detected_at=df["time"].iloc[retrace_low_pos] if "time" in df.columns else None,
    )
    pattern.compute_levels(float(atr))

    if pattern.rrr < config.HVF_MIN_RRR:
        return None

    return pattern


def _check_bearish_retrace(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    impulse_start_idx: int,
    impulse_start_price: float,
    impulse_end_idx: int,
    impulse_end_price: float,
    impulse_range: float,
    scan_bar: int,
    max_retrace_bars: int,
) -> Optional[ViperPattern]:
    """Check for valid bearish retracement after a down-impulse."""
    retrace_end = min(impulse_end_idx + max_retrace_bars, len(df) - 1)

    retrace_slice = df.iloc[impulse_end_idx + 1:retrace_end + 1]
    if len(retrace_slice) < 2:
        return None

    retrace_high_pos = retrace_slice["high"].idxmax()
    retrace_high_price = df["high"].iloc[retrace_high_pos]

    # Fibonacci retracement level
    retrace_depth = retrace_high_price - impulse_end_price
    if impulse_range <= 0:
        return None
    fib_level = retrace_depth / impulse_range

    if not (FIB_236 <= fib_level <= FIB_618):
        return None

    # RSI stays below 60 during retracement
    rsi_slice = df["rsi"].iloc[impulse_end_idx:retrace_high_pos + 1]
    if rsi_slice.dropna().max() > 60:
        return None

    # MACD confirmation (MACD < signal = bearish)
    if retrace_high_pos < len(df):
        macd_val = df["macd"].iloc[retrace_high_pos]
        macd_sig = df["macd_signal"].iloc[retrace_high_pos]
        if np.isnan(macd_val) or np.isnan(macd_sig):
            return None
        if macd_val >= macd_sig:
            return None

    # Candle closes below 50% Fib level
    fib_50_price = impulse_end_price + (impulse_range * FIB_500)
    close_at_retrace = df["close"].iloc[retrace_high_pos]
    if close_at_retrace > fib_50_price:
        return None

    atr = df["atr"].iloc[retrace_high_pos]
    if np.isnan(atr):
        return None

    pattern = ViperPattern(
        symbol=symbol,
        timeframe=timeframe,
        direction="SHORT",
        impulse_start_idx=impulse_start_idx,
        impulse_start_price=impulse_start_price,
        impulse_end_idx=impulse_end_idx,
        impulse_end_price=impulse_end_price,
        impulse_range=impulse_range,
        retrace_end_idx=retrace_high_pos,
        retrace_end_price=close_at_retrace,
        retrace_fib_level=fib_level,
        detected_at=df["time"].iloc[retrace_high_pos] if "time" in df.columns else None,
    )
    pattern.compute_levels(float(atr))

    if pattern.rrr < config.HVF_MIN_RRR:
        return None

    return pattern


def _deduplicate_vipers(patterns: list[ViperPattern]) -> list[ViperPattern]:
    """Remove patterns with overlapping impulse legs, keeping highest score."""
    if len(patterns) <= 1:
        return patterns

    patterns.sort(key=lambda p: p.impulse_start_idx)
    deduped: list[ViperPattern] = [patterns[0]]

    for p in patterns[1:]:
        prev = deduped[-1]
        # Overlap if impulse ranges intersect
        if p.impulse_start_idx <= prev.impulse_end_idx:
            # Keep the one with better RRR
            if p.rrr > prev.rrr:
                deduped[-1] = p
        else:
            deduped.append(p)

    return deduped


def check_viper_entry_confirmation(
    pattern: ViperPattern,
    latest_bar: pd.Series,
) -> bool:
    """
    Check if latest bar confirms Viper entry.

    LONG: candle closes above retrace end price (already past 50% fib).
    SHORT: candle closes below retrace end price.
    """
    close_price = latest_bar.get("close", None)
    if close_price is None:
        return False

    if pattern.direction == "LONG":
        return float(close_price) > pattern.entry_price
    else:
        return float(close_price) < pattern.entry_price
