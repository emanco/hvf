"""
London Sweep Detector — Asian range sweep reversal at London open.

Pattern: Asian range forms → London open sweeps past extreme →
         rejection candle closes back inside range → reversal.
Expected frequency: ~3-5 trades/week/pair.

Rules:
1. Track Asian range (23:00-06:00 UTC)
2. London open (07:00-10:00) sweeps past Asian extreme
3. Rejection candle: wick > 1.5x body, close back inside range
4. SL beyond sweep + 0.3 * ATR
5. T1 = opposite Asian extreme, T2 = range projection beyond T1
6. Asian range > 0.3x ATR (filter flat sessions)
"""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config

logger = logging.getLogger(__name__)

# Asian session: 23:00-06:00 UTC (wraps midnight)
ASIAN_START_HOUR = 23
ASIAN_END_HOUR = 6

# London sweep window: 07:00-10:00 UTC
LONDON_SWEEP_START_HOUR = 7
LONDON_SWEEP_END_HOUR = 10


@dataclass
class AsianRange:
    high: float
    low: float
    high_idx: int
    low_idx: int
    range_size: float
    date: pd.Timestamp  # Date of the Asian session


@dataclass
class LondonSweepPattern:
    symbol: str
    timeframe: str
    direction: str  # 'LONG' or 'SHORT'

    # Asian range context
    asian_high: float
    asian_low: float
    asian_range: float

    # Sweep details
    sweep_bar_idx: int
    sweep_extreme: float  # How far past the Asian extreme the sweep went
    rejection_close: float  # Close price (back inside range)

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
    pattern_type: str = "LONDON_SWEEP"

    def compute_levels(self, current_atr: float):
        """Calculate entry, SL, targets from Asian range and sweep."""
        atr_buffer = 0.3 * current_atr

        if self.direction == "LONG":
            # Swept below Asian low → long reversal
            self.entry_price = self.rejection_close
            self.stop_loss = self.sweep_extreme - atr_buffer
            self.target_1 = self.asian_high  # Opposite extreme
            self.target_2 = self.asian_high + self.asian_range  # Range projection
        else:
            # Swept above Asian high → short reversal
            self.entry_price = self.rejection_close
            self.stop_loss = self.sweep_extreme + atr_buffer
            self.target_1 = self.asian_low
            self.target_2 = self.asian_low - self.asian_range

        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_2 - self.entry_price)
        self.rrr = reward / risk if risk > 0 else 0.0


def detect_london_sweep_patterns(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> list[LondonSweepPattern]:
    """
    Scan for London Sweep reversal patterns.

    Args:
        df: OHLCV DataFrame with 'atr', 'time' columns
        symbol: instrument symbol
        timeframe: e.g. 'H1'

    Returns:
        List of valid LondonSweepPattern objects
    """
    if len(df) < 50 or "time" not in df.columns or "atr" not in df.columns:
        return []

    patterns: list[LondonSweepPattern] = []
    last_bar = len(df) - 1

    # Build Asian ranges and check London sweeps
    asian_ranges = _build_asian_ranges(df)

    for asian in asian_ranges:
        # Filter: Asian range must be > 0.3x ATR
        atr_at_range = _get_atr_near(df, asian.high_idx)
        if atr_at_range <= 0:
            continue
        if asian.range_size < 0.3 * atr_at_range:
            continue

        # Find London sweep bars (07:00-10:00 UTC on the day after Asian close)
        sweep_patterns = _check_london_sweep(
            df, symbol, timeframe, asian, last_bar
        )
        patterns.extend(sweep_patterns)

    # Filter stale
    patterns = [
        p for p in patterns
        if (last_bar - p.sweep_bar_idx) <= config.PATTERN_EXPIRY_BARS
    ]

    patterns.sort(
        key=lambda p: p.detected_at if p.detected_at else pd.Timestamp.min,
        reverse=True,
    )
    return patterns


def _build_asian_ranges(df: pd.DataFrame) -> list[AsianRange]:
    """Build Asian session ranges from hourly data."""
    ranges: list[AsianRange] = []

    # Group bars by Asian session (23:00 to 06:00)
    current_session: list[int] = []

    for i in range(len(df)):
        hour = df["time"].iloc[i].hour
        if hour >= ASIAN_START_HOUR or hour < ASIAN_END_HOUR:
            current_session.append(i)
        else:
            if len(current_session) >= 3:  # Minimum bars for valid range
                session_slice = df.iloc[current_session]
                high = session_slice["high"].max()
                low = session_slice["low"].min()
                high_idx = current_session[session_slice["high"].values.argmax()]
                low_idx = current_session[session_slice["low"].values.argmin()]
                ranges.append(AsianRange(
                    high=high,
                    low=low,
                    high_idx=high_idx,
                    low_idx=low_idx,
                    range_size=high - low,
                    date=df["time"].iloc[current_session[-1]],
                ))
            current_session = []

    return ranges


def _check_london_sweep(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    asian: AsianRange,
    last_bar: int,
) -> list[LondonSweepPattern]:
    """Check for London sweep of the given Asian range."""
    patterns: list[LondonSweepPattern] = []

    # Find bars in the London sweep window (07:00-10:00 UTC)
    # These should be right after the Asian session ends
    search_start = max(asian.high_idx, asian.low_idx) + 1
    search_end = min(search_start + 15, last_bar + 1)  # ~15 bars max

    swept_high = False
    swept_low = False
    sweep_high_extreme = asian.high
    sweep_low_extreme = asian.low

    for i in range(search_start, search_end):
        bar = df.iloc[i]
        hour = bar["time"].hour

        if not (LONDON_SWEEP_START_HOUR <= hour < LONDON_SWEEP_END_HOUR):
            # Allow one bar before/after for transition
            if hour < LONDON_SWEEP_START_HOUR - 1 or hour >= LONDON_SWEEP_END_HOUR + 1:
                continue

        atr = bar.get("atr", 0)
        if np.isnan(atr) or atr <= 0:
            continue

        # Check for sweep above Asian high
        if bar["high"] > asian.high:
            swept_high = True
            sweep_high_extreme = max(sweep_high_extreme, bar["high"])

            # Check rejection: wick > 1.5x body, close back inside range
            if _is_sweep_rejection(bar, "BEARISH", asian.high, asian.low):
                pattern = LondonSweepPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    asian_high=asian.high,
                    asian_low=asian.low,
                    asian_range=asian.range_size,
                    sweep_bar_idx=i,
                    sweep_extreme=sweep_high_extreme,
                    rejection_close=bar["close"],
                    detected_at=bar["time"] if "time" in df.columns else None,
                )
                pattern.compute_levels(float(atr))
                if pattern.rrr >= config.MIN_RRR_BY_PATTERN.get("LONDON_SWEEP", config.HVF_MIN_RRR):
                    patterns.append(pattern)

        # Check for sweep below Asian low
        if bar["low"] < asian.low:
            swept_low = True
            sweep_low_extreme = min(sweep_low_extreme, bar["low"])

            if _is_sweep_rejection(bar, "BULLISH", asian.high, asian.low):
                pattern = LondonSweepPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    asian_high=asian.high,
                    asian_low=asian.low,
                    asian_range=asian.range_size,
                    sweep_bar_idx=i,
                    sweep_extreme=sweep_low_extreme,
                    rejection_close=bar["close"],
                    detected_at=bar["time"] if "time" in df.columns else None,
                )
                pattern.compute_levels(float(atr))
                if pattern.rrr >= config.MIN_RRR_BY_PATTERN.get("LONDON_SWEEP", config.HVF_MIN_RRR):
                    patterns.append(pattern)

    return patterns


def _is_sweep_rejection(
    bar: pd.Series,
    rejection_type: str,
    asian_high: float,
    asian_low: float,
) -> bool:
    """
    Check if bar is a sweep rejection candle.

    Requirements:
    - Wick > 1.5x body
    - Close back inside Asian range
    """
    body = abs(bar["close"] - bar["open"])
    if body == 0:
        body = 0.00001

    close = bar["close"]

    if rejection_type == "BEARISH":
        # Swept above high, must close back inside range
        upper_wick = bar["high"] - max(bar["open"], bar["close"])
        if upper_wick < 1.5 * body:
            return False
        if close > asian_high:
            return False  # Didn't close back inside
        return True
    else:  # BULLISH
        lower_wick = min(bar["open"], bar["close"]) - bar["low"]
        if lower_wick < 1.5 * body:
            return False
        if close < asian_low:
            return False
        return True


def _get_atr_near(df: pd.DataFrame, bar_idx: int) -> float:
    """Get ATR near a bar index with fallback."""
    idx = min(max(bar_idx, 0), len(df) - 1)
    val = df["atr"].iloc[idx]
    if np.isnan(val):
        valid = df["atr"].dropna()
        return float(valid.iloc[-1]) if len(valid) > 0 else 0.0
    return float(val)


def check_london_sweep_entry_confirmation(
    pattern: LondonSweepPattern,
    latest_bar: pd.Series,
) -> bool:
    """Check if latest bar confirms London Sweep entry."""
    close_price = latest_bar.get("close", None)
    if close_price is None:
        return False

    if pattern.direction == "LONG":
        return float(close_price) > pattern.entry_price
    else:
        return float(close_price) < pattern.entry_price
