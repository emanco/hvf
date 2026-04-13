"""
Wedge Pattern Detector — converging trendline breakout patterns.

Detects rising wedges (bearish) and falling wedges (bullish) on D1 data
using swing point identification + trendline fitting via linear regression.

Based on Francis Hunt's measured-move methodology:
  - Target projected from midpoint of last swing pair (not breakout point)
  - Widest oscillation = the measured move distance
  - T1 at 50%, T2 at 100% of measured move
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from hvf_trader import config

logger = logging.getLogger(__name__)


@dataclass
class WedgePattern:
    symbol: str
    timeframe: str
    direction: str              # Expected breakout: 'LONG' (falling wedge) or 'SHORT' (rising wedge)
    wedge_type: str             # 'RISING_WEDGE' or 'FALLING_WEDGE'

    # Trendline parameters (price = slope * bar_index + intercept)
    upper_slope: float = 0.0
    upper_intercept: float = 0.0
    upper_r_squared: float = 0.0
    lower_slope: float = 0.0
    lower_intercept: float = 0.0
    lower_r_squared: float = 0.0

    # Touch points: list of (bar_index, price) tuples
    upper_touches: list = field(default_factory=list)
    lower_touches: list = field(default_factory=list)

    # Pattern boundaries (bar indices in the detection DataFrame)
    start_index: int = 0
    end_index: int = 0
    apex_index: float = 0.0     # Projected trendline intersection

    # Widest range at pattern start (the "measured move" distance)
    widest_range: float = 0.0

    # Trade levels (computed after breakout detection)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    midpoint: float = 0.0
    rrr: float = 0.0

    # Metadata
    detected_at: Optional[pd.Timestamp] = None
    score: float = 0.0
    status: str = "DETECTED"
    pattern_type: str = "WEDGE"

    def compute_levels(self, current_atr: float):
        """Calculate entry, SL, targets using Hunt's midpoint method."""
        if not self.upper_touches or not self.lower_touches:
            return

        # Midpoint of last swing high and last swing low (Hunt's method)
        last_high = self.upper_touches[-1][1]
        last_low = self.lower_touches[-1][1]
        self.midpoint = (last_high + last_low) / 2

        atr_buffer = config.WEDGE_SL_ATR_MULT * current_atr

        if self.direction == "LONG":
            # Falling wedge breakout upward
            self.entry_price = last_high  # Break above upper trendline
            self.stop_loss = last_low - atr_buffer
            self.target_1 = self.midpoint + (self.widest_range * config.WEDGE_TARGET_1_MULT)
            self.target_2 = self.midpoint + (self.widest_range * config.WEDGE_TARGET_2_MULT)
        else:
            # Rising wedge breakout downward
            self.entry_price = last_low  # Break below lower trendline
            self.stop_loss = last_high + atr_buffer
            self.target_1 = self.midpoint - (self.widest_range * config.WEDGE_TARGET_1_MULT)
            self.target_2 = self.midpoint - (self.widest_range * config.WEDGE_TARGET_2_MULT)

        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_2 - self.entry_price)
        self.rrr = reward / risk if risk > 0 else 0.0


def find_swing_points(
    df: pd.DataFrame,
    lookback: int = 5,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Find swing highs and swing lows using N-bar lookback.

    A swing high at bar i: high[i] > max(high[i-N:i]) AND high[i] >= max(high[i+1:i+N+1])
    A swing low at bar i:  low[i]  < min(low[i-N:i])  AND low[i]  <= min(low[i+1:i+N+1])

    Returns:
        (swing_highs, swing_lows) — each is list of (bar_index, price)
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    swing_highs = []
    swing_lows = []

    for i in range(lookback, n - lookback):
        # Swing high
        left_max = np.max(highs[i - lookback:i])
        right_max = np.max(highs[i + 1:i + lookback + 1])
        if highs[i] > left_max and highs[i] >= right_max:
            swing_highs.append((i, float(highs[i])))

        # Swing low
        left_min = np.min(lows[i - lookback:i])
        right_min = np.min(lows[i + 1:i + lookback + 1])
        if lows[i] < left_min and lows[i] <= right_min:
            swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


def _fit_trendline(points: list[tuple[int, float]]) -> tuple[float, float, float]:
    """
    Fit a linear regression trendline to (index, price) points.

    Returns:
        (slope, intercept, r_squared)
    """
    if len(points) < 2:
        return 0.0, 0.0, 0.0

    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)

    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    r_squared = r_value ** 2

    return slope, intercept, r_squared


def _find_trendline_touches(
    points: list[tuple[int, float]],
    slope: float,
    intercept: float,
    tolerance_pct: float = 0.003,
) -> list[tuple[int, float]]:
    """
    Find which swing points are within tolerance of the trendline.

    Args:
        tolerance_pct: Maximum distance as fraction of price (0.3% default).
    """
    touches = []
    for idx, price in points:
        trendline_price = slope * idx + intercept
        if price == 0:
            continue
        distance_pct = abs(price - trendline_price) / price
        if distance_pct <= tolerance_pct:
            touches.append((idx, price))
    return touches


def _classify_wedge(upper_slope: float, lower_slope: float) -> Optional[str]:
    """
    Classify wedge type based on trendline slopes.

    Rising wedge:  both slopes positive, lower slope steeper (converging)
    Falling wedge: both slopes negative, upper slope steeper/more negative (converging)
    """
    if upper_slope > 0 and lower_slope > 0:
        if lower_slope > upper_slope:
            return "RISING_WEDGE"
        return None  # Expanding or parallel

    if upper_slope < 0 and lower_slope < 0:
        if abs(upper_slope) > abs(lower_slope):
            return "FALLING_WEDGE"
        return None  # Expanding or parallel

    # One positive, one negative = symmetrical triangle (handled by HVF detector)
    return None


def _deduplicate_patterns(patterns: list[WedgePattern]) -> list[WedgePattern]:
    """Remove overlapping patterns, keeping the highest quality one."""
    if len(patterns) <= 1:
        return patterns

    # Sort by combined R-squared descending
    patterns.sort(
        key=lambda p: (p.upper_r_squared + p.lower_r_squared) / 2,
        reverse=True,
    )

    kept = []
    for p in patterns:
        overlaps = False
        for k in kept:
            overlap_start = max(p.start_index, k.start_index)
            overlap_end = min(p.end_index, k.end_index)
            if overlap_end > overlap_start:
                p_duration = p.end_index - p.start_index
                if p_duration > 0:
                    overlap_pct = (overlap_end - overlap_start) / p_duration
                    if overlap_pct > 0.5:
                        overlaps = True
                        break
        if not overlaps:
            kept.append(p)

    return kept


def detect_wedge_patterns(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "D1",
) -> list[WedgePattern]:
    """
    Detect wedge patterns in OHLCV data.

    Uses swing point identification + trendline fitting to find converging
    same-direction trendline pairs. Designed primarily for D1 data.

    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'tick_volume', 'time']
            and pre-computed 'atr' column
        symbol: instrument symbol
        timeframe: detection timeframe (e.g. 'D1')

    Returns:
        List of WedgePattern objects, deduplicated and with levels computed
    """
    min_touches = config.WEDGE_MIN_TOUCHES
    min_bars = config.WEDGE_MIN_BARS
    max_bars = config.WEDGE_MAX_BARS
    lookback = config.WEDGE_SWING_LOOKBACK
    min_r2 = config.WEDGE_MIN_R_SQUARED
    convergence_min = config.WEDGE_CONVERGENCE_MIN

    if len(df) < min_bars + 2 * lookback:
        return []

    swing_highs, swing_lows = find_swing_points(df, lookback=lookback)

    if len(swing_highs) < min_touches or len(swing_lows) < min_touches:
        return []

    patterns = []

    # Sliding window over swing high groups
    for start_h in range(len(swing_highs) - min_touches + 1):
        for end_h in range(start_h + min_touches - 1, min(start_h + 8, len(swing_highs))):
            h_points = swing_highs[start_h:end_h + 1]
            h_start_idx = h_points[0][0]
            h_end_idx = h_points[-1][0]

            duration = h_end_idx - h_start_idx
            if duration < min_bars or duration > max_bars:
                continue

            # Find swing lows within the same time window (with slight margin)
            margin = lookback
            l_points = [
                (idx, price) for idx, price in swing_lows
                if (h_start_idx - margin) <= idx <= (h_end_idx + margin)
            ]
            if len(l_points) < min_touches:
                continue

            # Fit trendlines
            h_slope, h_intercept, h_r2 = _fit_trendline(h_points)
            l_slope, l_intercept, l_r2 = _fit_trendline(l_points)

            if h_r2 < min_r2 or l_r2 < min_r2:
                continue

            # Check convergence
            range_at_start = (h_slope * h_start_idx + h_intercept) - \
                             (l_slope * h_start_idx + l_intercept)
            range_at_end = (h_slope * h_end_idx + h_intercept) - \
                           (l_slope * h_end_idx + l_intercept)

            if range_at_start <= 0 or range_at_end <= 0:
                continue  # Trendlines crossed — invalid

            convergence_pct = 1.0 - (range_at_end / range_at_start)
            if convergence_pct < convergence_min:
                continue

            # Classify
            wedge_type = _classify_wedge(h_slope, l_slope)
            if wedge_type is None:
                continue

            # Calculate apex
            slope_diff = h_slope - l_slope
            if abs(slope_diff) > 1e-10:
                apex_index = (l_intercept - h_intercept) / slope_diff
            else:
                apex_index = float(h_end_idx + duration)

            # Validate touch points with tolerance
            avg_price = df["close"].iloc[h_start_idx:h_end_idx + 1].mean()
            # Scale tolerance: 0.3% for forex, wider for metals
            tolerance = 0.003 if avg_price < 100 else 0.005
            upper_touches = _find_trendline_touches(h_points, h_slope, h_intercept, tolerance)
            lower_touches = _find_trendline_touches(l_points, l_slope, l_intercept, tolerance)

            if len(upper_touches) < min_touches or len(lower_touches) < min_touches:
                continue

            # Direction
            direction = "SHORT" if wedge_type == "RISING_WEDGE" else "LONG"

            # Get ATR at pattern end for level computation
            atr_col = "atr"
            if atr_col in df.columns and h_end_idx < len(df):
                current_atr = df[atr_col].iloc[min(h_end_idx, len(df) - 1)]
                if np.isnan(current_atr):
                    current_atr = df[atr_col].dropna().iloc[-1] if not df[atr_col].dropna().empty else 0
            else:
                current_atr = 0

            wedge = WedgePattern(
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                wedge_type=wedge_type,
                upper_slope=h_slope,
                upper_intercept=h_intercept,
                upper_r_squared=h_r2,
                lower_slope=l_slope,
                lower_intercept=l_intercept,
                lower_r_squared=l_r2,
                upper_touches=upper_touches,
                lower_touches=lower_touches,
                start_index=h_start_idx,
                end_index=h_end_idx,
                apex_index=apex_index,
                widest_range=range_at_start,
                detected_at=pd.Timestamp(df["time"].iloc[h_end_idx]) if "time" in df.columns else None,
            )

            # Compute trade levels
            if current_atr > 0:
                wedge.compute_levels(current_atr)

            patterns.append(wedge)

    patterns = _deduplicate_patterns(patterns)

    logger.debug(
        "Wedge scan %s (%s): %d swing highs, %d swing lows, %d patterns found",
        symbol, timeframe, len(swing_highs), len(swing_lows), len(patterns),
    )

    return patterns


def check_wedge_breakout(
    wedge: WedgePattern,
    bar: pd.Series,
    bar_index: int,
    current_atr: float,
) -> bool:
    """
    Check if the given bar breaks out of the wedge in the expected direction.

    Breakout requires:
    1. Close beyond the trendline boundary by at least WEDGE_BREAKOUT_ATR_BUFFER * ATR
    2. Breakout direction matches wedge expectation
    """
    close = float(bar["close"])
    buffer = config.WEDGE_BREAKOUT_ATR_BUFFER * current_atr

    if wedge.direction == "LONG":
        # Falling wedge: expect upward breakout through upper trendline
        upper_line = wedge.upper_slope * bar_index + wedge.upper_intercept
        return close > upper_line + buffer
    else:
        # Rising wedge: expect downward breakout through lower trendline
        lower_line = wedge.lower_slope * bar_index + wedge.lower_intercept
        return close < lower_line - buffer


def check_wedge_entry_confirmation(
    pattern: WedgePattern,
    latest_bar: pd.Series,
) -> bool:
    """
    Check if latest bar confirms wedge entry.
    Same logic as KZ_HUNT: close past entry price.
    """
    close_price = latest_bar.get("close", None)
    if close_price is None:
        return False

    if pattern.direction == "LONG":
        return float(close_price) > pattern.entry_price
    else:
        return float(close_price) < pattern.entry_price
