"""
HVF 6-rule validation with 5 additional filters.
Scans zigzag pivots for valid Hunt Volatility Funnel patterns.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from hvf_trader.detector.zigzag import Pivot, compute_zigzag
from hvf_trader import config


@dataclass
class HVFPattern:
    symbol: str
    timeframe: str
    direction: str            # 'LONG' or 'SHORT'
    h1: Pivot
    l1: Pivot
    h2: Pivot
    l2: Pivot
    h3: Pivot
    l3: Pivot

    # Computed on creation
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    midpoint: float = 0.0
    full_range: float = 0.0
    rrr: float = 0.0

    # Detection metadata
    detected_at: Optional[pd.Timestamp] = None
    score: float = 0.0
    status: str = "DETECTED"  # DETECTED -> ARMED -> TRIGGERED/EXPIRED/INVALIDATED

    def compute_levels(self, current_atr: float):
        """Calculate entry, SL, targets, RRR based on HVF theory."""
        pip_value = config.PIP_VALUES.get(self.symbol, 0.0001)
        buffer = config.HVF_ENTRY_BUFFER_PIPS * pip_value

        if self.direction == "LONG":
            self.entry_price = self.h3.price + buffer
            self.stop_loss = self.l3.price - (config.HVF_ATR_STOP_MULT * current_atr)
            self.midpoint = (self.h3.price + self.l3.price) / 2
            self.full_range = self.h1.price - self.l1.price
            self.target_1 = self.midpoint + (self.full_range * config.TARGET_1_MULT)
            self.target_2 = self.midpoint + (self.full_range * config.TARGET_2_MULT)
        else:  # SHORT
            self.entry_price = self.l3.price - buffer
            self.stop_loss = self.h3.price + (config.HVF_ATR_STOP_MULT * current_atr)
            self.midpoint = (self.h3.price + self.l3.price) / 2
            self.full_range = self.h1.price - self.l1.price
            self.target_1 = self.midpoint - (self.full_range * config.TARGET_1_MULT)
            self.target_2 = self.midpoint - (self.full_range * config.TARGET_2_MULT)

        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_2 - self.entry_price)
        self.rrr = reward / risk if risk > 0 else 0.0


def detect_hvf_patterns(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    pivots: list[Pivot] = None,
    df_4h: pd.DataFrame = None,
) -> list[HVFPattern]:
    """
    Scan pivots for valid HVF patterns.

    Args:
        df: 1H OHLCV DataFrame with 'atr', 'ema_200', 'adx' columns
        symbol: instrument symbol
        timeframe: e.g. 'H1'
        pivots: pre-computed zigzag pivots (if None, compute from df)
        df_4h: 4H DataFrame with 'ema_200' for multi-TF confirmation

    Returns:
        List of valid HVFPattern objects sorted by score descending
    """
    if pivots is None:
        pivots = compute_zigzag(df, atr_multiplier=config.ZIGZAG_ATR_MULTIPLIER)

    if len(pivots) < 6:
        return []

    patterns: list[HVFPattern] = []

    # Slide a window of 6 consecutive pivots
    for i in range(len(pivots) - 5):
        window = pivots[i : i + 6]

        # Try BULLISH configuration: H, L, H, L, H, L
        if (
            window[0].pivot_type == "H"
            and window[1].pivot_type == "L"
            and window[2].pivot_type == "H"
            and window[3].pivot_type == "L"
            and window[4].pivot_type == "H"
            and window[5].pivot_type == "L"
        ):
            h1, l1, h2, l2, h3, l3 = window
            if _validate_pattern(h1, l1, h2, l2, h3, l3, "LONG", df, df_4h):
                pattern = HVFPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    h1=h1, l1=l1, h2=h2, l2=l2, h3=h3, l3=l3,
                    detected_at=l3.timestamp,
                )
                current_atr = _get_atr_at_index(df, l3.index)
                pattern.compute_levels(current_atr)
                if pattern.rrr >= config.HVF_MIN_RRR:
                    patterns.append(pattern)

        # Try BEARISH configuration: L, H, L, H, L, H
        if (
            window[0].pivot_type == "L"
            and window[1].pivot_type == "H"
            and window[2].pivot_type == "L"
            and window[3].pivot_type == "H"
            and window[4].pivot_type == "L"
            and window[5].pivot_type == "H"
        ):
            l1, h1, l2, h2, l3, h3 = window
            if _validate_pattern(h1, l1, h2, l2, h3, l3, "SHORT", df, df_4h):
                pattern = HVFPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    h1=h1, l1=l1, h2=h2, l2=l2, h3=h3, l3=l3,
                    detected_at=h3.timestamp,
                )
                current_atr = _get_atr_at_index(df, h3.index)
                pattern.compute_levels(current_atr)
                if pattern.rrr >= config.HVF_MIN_RRR:
                    patterns.append(pattern)

    # Sort by most recent detection first (patterns near the end of data are most actionable)
    patterns.sort(
        key=lambda p: p.detected_at if p.detected_at is not None else pd.Timestamp.min,
        reverse=True,
    )

    return patterns


def _get_atr_at_index(df: pd.DataFrame, bar_index: int) -> float:
    """Safely retrieve ATR value at a given bar index."""
    if bar_index < len(df):
        val = df["atr"].iloc[bar_index]
        if not np.isnan(val):
            return float(val)
    # Fallback: use the last valid ATR value
    valid_atrs = df["atr"].dropna()
    if len(valid_atrs) > 0:
        return float(valid_atrs.iloc[-1])
    return 0.0


def _get_avg_volume_in_range(df: pd.DataFrame, start_idx: int, end_idx: int) -> float:
    """Calculate average tick_volume between two bar indices (inclusive)."""
    start = max(0, start_idx)
    end = min(len(df), end_idx + 1)
    if start >= end:
        return 0.0
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    if vol_col not in df.columns:
        return 0.0
    segment = df[vol_col].iloc[start:end]
    return float(segment.mean()) if len(segment) > 0 else 0.0


def _validate_pattern(
    h1: Pivot, l1: Pivot, h2: Pivot, l2: Pivot, h3: Pivot, l3: Pivot,
    direction: str,
    df: pd.DataFrame,
    df_4h: pd.DataFrame = None,
) -> bool:
    """
    Apply 6 HVF rules + 5 additional filters.
    Returns True only if ALL checks pass.
    """
    # ─── 6 HVF Rules ─────────────────────────────

    # Rule 1: Descending highs (bullish) or ascending highs (bearish)
    if direction == "LONG":
        # Bullish funnel: highs descend (converging from top)
        if not (h1.price > h2.price > h3.price):
            return False
    else:
        # Bearish funnel: highs ascend (expanding from bottom perspective,
        # but the funnel converges so lows ascend toward highs)
        if not (h1.price < h2.price < h3.price):
            return False

    # Rule 2: Ascending lows (bullish) or descending lows (bearish)
    if direction == "LONG":
        # Bullish funnel: lows ascend (converging from bottom)
        if not (l1.price < l2.price < l3.price):
            return False
    else:
        # Bearish funnel: lows descend (converging from top)
        if not (l1.price > l2.price > l3.price):
            return False

    # Rule 3: Chronological ordering (pivots arrive in temporal order)
    all_pivots_ordered = [h1, l1, h2, l2, h3, l3]
    # For bullish: H1, L1, H2, L2, H3, L3 with interleaved timing
    # For bearish: L1, H1, L2, H2, L3, H3 with interleaved timing
    # Since pivots come from zigzag they should already alternate,
    # but we verify chronological index ordering of the wave pairs
    if direction == "LONG":
        # The original pivot order from zigzag is H1, L1, H2, L2, H3, L3
        if not (h1.index < l1.index < h2.index < l2.index < h3.index < l3.index):
            return False
    else:
        # The original pivot order from zigzag is L1, H1, L2, H2, L3, H3
        if not (l1.index < h1.index < l2.index < h2.index < l3.index < h3.index):
            return False

    # Rule 4: Convergence -- wave ranges must decrease
    wave1_range = abs(h1.price - l1.price)
    wave2_range = abs(h2.price - l2.price)
    wave3_range = abs(h3.price - l3.price)

    if not (wave1_range > wave2_range > wave3_range):
        return False

    # Rule 5: Prior trend -- EMA200 confirmation at the start of the pattern
    if "ema_200" in df.columns and h1.index < len(df):
        ema_at_h1 = df["ema_200"].iloc[h1.index]
        if not np.isnan(ema_at_h1):
            if direction == "LONG":
                # Bullish: price should have been above EMA200 (prior uptrend
                # that is now consolidating into the funnel)
                if h1.price < ema_at_h1:
                    return False
            else:
                # Bearish: price should have been below EMA200 (prior downtrend)
                if l1.price > ema_at_h1:
                    return False

    # Rule 6: Volume contraction -- average volume in Wave3 zone < Wave1 zone
    wave1_start = min(h1.index, l1.index)
    wave1_end = max(h1.index, l1.index)
    wave3_start = min(h3.index, l3.index)
    wave3_end = max(h3.index, l3.index)

    avg_vol_wave1 = _get_avg_volume_in_range(df, wave1_start, wave1_end)
    avg_vol_wave3 = _get_avg_volume_in_range(df, wave3_start, wave3_end)

    if avg_vol_wave1 > 0 and avg_vol_wave3 >= avg_vol_wave1:
        return False

    # ─── 5 Additional Filters ────────────────────

    # Filter 1: Wave 1 minimum range must exceed WAVE1_MIN_ATR_MULT * ATR14
    atr_at_h1 = _get_atr_at_index(df, h1.index)
    if atr_at_h1 > 0:
        if wave1_range < config.WAVE1_MIN_ATR_MULT * atr_at_h1:
            return False

    # Filter 2: Time proportionality -- Wave3 duration <= WAVE3_MAX_DURATION_MULT * Wave1 duration
    wave1_duration = wave1_end - wave1_start
    wave3_duration = wave3_end - wave3_start

    if wave1_duration > 0:
        if wave3_duration > config.WAVE3_MAX_DURATION_MULT * wave1_duration:
            return False

    # Filter 3: Trend strength -- ADX > ADX_MIN_TREND at the pattern zone
    if "adx" in df.columns:
        # Use ADX at the midpoint of the pattern for representative trend strength
        pattern_mid_idx = (h1.index + l3.index) // 2 if direction == "LONG" else (l1.index + h3.index) // 2
        pattern_mid_idx = min(pattern_mid_idx, len(df) - 1)
        adx_val = df["adx"].iloc[pattern_mid_idx]
        if not np.isnan(adx_val):
            if adx_val < config.ADX_MIN_TREND:
                return False

    # Filter 4: 4H trend confirmation (if df_4h provided)
    if df_4h is not None and "ema_200" in df_4h.columns and len(df_4h) > 0:
        # Find the 4H bar closest to the pattern's last pivot
        last_pivot_idx = l3.index if direction == "LONG" else h3.index
        if last_pivot_idx < len(df) and "time" in df.columns:
            pattern_time = df["time"].iloc[last_pivot_idx]
            # Find the 4H bar at or before this timestamp
            if "time" in df_4h.columns:
                mask = df_4h["time"] <= pattern_time
                if mask.any():
                    closest_4h_idx = df_4h.loc[mask].index[-1]
                    ema_4h = df_4h["ema_200"].iloc[closest_4h_idx]
                    close_4h = df_4h["close"].iloc[closest_4h_idx]
                    if not np.isnan(ema_4h):
                        if direction == "LONG" and close_4h < ema_4h:
                            return False
                        if direction == "SHORT" and close_4h > ema_4h:
                            return False

    # Filter 5: Stale pattern -- pattern should not be older than PATTERN_EXPIRY_BARS
    last_bar_idx = len(df) - 1
    last_pivot_bar = l3.index if direction == "LONG" else h3.index
    bars_since_pattern = last_bar_idx - last_pivot_bar

    if bars_since_pattern > config.PATTERN_EXPIRY_BARS:
        return False

    return True


def check_entry_confirmation(
    pattern: HVFPattern,
    latest_bar: pd.Series,
    volume_20_avg: float,
) -> bool:
    """
    Check if the latest 1H candle CLOSE confirms entry.

    Confirmed entry (LONG):
    - Candle CLOSED above H3 + buffer
    - Volume on that candle > VOLUME_SPIKE_MULT * 20-bar avg volume

    Confirmed entry (SHORT):
    - Candle CLOSED below L3 - buffer
    - Volume on that candle > VOLUME_SPIKE_MULT * 20-bar avg volume
    """
    close_price = latest_bar.get("close", None)
    if close_price is None:
        return False

    vol_col = "tick_volume" if "tick_volume" in latest_bar.index else "volume"
    bar_volume = latest_bar.get(vol_col, 0)

    # Volume confirmation: bar volume must exceed spike threshold
    if volume_20_avg > 0:
        if bar_volume < config.VOLUME_SPIKE_MULT * volume_20_avg:
            return False
    else:
        # If we have no volume baseline, skip volume check rather than
        # blocking all entries
        pass

    pip_value = config.PIP_VALUES.get(pattern.symbol, 0.0001)
    buffer = config.HVF_ENTRY_BUFFER_PIPS * pip_value

    if pattern.direction == "LONG":
        # Candle must close above H3 + buffer
        threshold = pattern.h3.price + buffer
        return float(close_price) > threshold

    else:  # SHORT
        # Candle must close below L3 - buffer
        threshold = pattern.l3.price - buffer
        return float(close_price) < threshold
