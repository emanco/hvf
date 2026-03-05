"""
Percentage-based zigzag pivot detection.
Replaces scipy.argrelextrema with ATR-adaptive thresholds.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class Pivot:
    index: int          # Bar index in the dataframe
    price: float        # Pivot price (high for H, low for L)
    pivot_type: str     # 'H' or 'L'
    timestamp: pd.Timestamp  # Bar timestamp


def compute_zigzag(df: pd.DataFrame, atr_multiplier: float = 1.5) -> list[Pivot]:
    """
    Walk through OHLCV data bar-by-bar with ATR-adaptive threshold.

    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'tick_volume', 'time']
            and a pre-computed 'atr' column (ATR_14)
        atr_multiplier: Multiplier for ATR-based threshold (from config.ZIGZAG_ATR_MULTIPLIER)

    Returns:
        List of Pivot objects in chronological order

    Algorithm:
    1. For each bar, compute threshold_pct = (atr / close) * 100 * atr_multiplier
    2. Track current direction (UP or DOWN) and current extreme (highest high or lowest low)
    3. When price reverses by >= threshold_pct from the current extreme:
       - Register the previous extreme as a pivot
       - Switch direction
       - Set current extreme to the reversal point
    4. Ensure alternation: H must follow L and vice versa
    """
    if len(df) < 20:
        return []

    if "atr" not in df.columns:
        raise ValueError("DataFrame must contain a pre-computed 'atr' column")

    # Work with numpy arrays for performance
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    atrs = df["atr"].values
    times = df["time"].values if "time" in df.columns else df.index.values

    # Find the first bar where ATR is valid (not NaN)
    start_idx = 0
    for i in range(len(atrs)):
        if not np.isnan(atrs[i]):
            start_idx = i
            break
    else:
        return []

    # Need enough bars after ATR becomes valid
    if (len(df) - start_idx) < 20:
        return []

    pivots: list[Pivot] = []

    # Initialize direction by looking at the first two bars after start
    # to determine whether price is initially moving up or down
    current_high = highs[start_idx]
    current_high_idx = start_idx
    current_low = lows[start_idx]
    current_low_idx = start_idx

    # Determine initial direction from first meaningful move
    direction = _determine_initial_direction(
        highs, lows, closes, atrs, start_idx, atr_multiplier
    )

    # Re-scan from start to find the initial extreme for that direction
    if direction == "UP":
        current_high = highs[start_idx]
        current_high_idx = start_idx
    else:
        current_low = lows[start_idx]
        current_low_idx = start_idx

    for i in range(start_idx + 1, len(df)):
        atr_val = atrs[i]
        close_val = closes[i]

        # Skip bars where ATR is not available
        if np.isnan(atr_val) or close_val == 0:
            continue

        threshold_pct = (atr_val / close_val) * 100.0 * atr_multiplier

        if direction == "UP":
            # Tracking highs -- extend the move upward
            if highs[i] > current_high:
                current_high = highs[i]
                current_high_idx = i

            # Check for reversal downward from the tracked high
            drop_pct = ((current_high - lows[i]) / current_high) * 100.0
            if drop_pct >= threshold_pct:
                # Register the current high as an H pivot
                pivots.append(Pivot(
                    index=current_high_idx,
                    price=current_high,
                    pivot_type="H",
                    timestamp=pd.Timestamp(times[current_high_idx]),
                ))
                # Switch direction to DOWN, start tracking lows
                direction = "DOWN"
                current_low = lows[i]
                current_low_idx = i

        else:  # direction == "DOWN"
            # Tracking lows -- extend the move downward
            if lows[i] < current_low:
                current_low = lows[i]
                current_low_idx = i

            # Check for reversal upward from the tracked low
            if current_low == 0:
                continue
            rise_pct = ((highs[i] - current_low) / current_low) * 100.0
            if rise_pct >= threshold_pct:
                # Register the current low as an L pivot
                pivots.append(Pivot(
                    index=current_low_idx,
                    price=current_low,
                    pivot_type="L",
                    timestamp=pd.Timestamp(times[current_low_idx]),
                ))
                # Switch direction to UP, start tracking highs
                direction = "UP"
                current_high = highs[i]
                current_high_idx = i

    # Enforce strict alternation: remove consecutive same-type pivots
    # keeping the more extreme one in each consecutive run
    pivots = _enforce_alternation(pivots)

    if len(pivots) < 2:
        return []

    return pivots


def _determine_initial_direction(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atrs: np.ndarray,
    start_idx: int,
    atr_multiplier: float,
) -> str:
    """
    Look ahead from start_idx to determine whether the first significant
    move is upward or downward. This sets the initial tracking direction.

    Returns 'UP' or 'DOWN'.
    """
    initial_high = highs[start_idx]
    initial_low = lows[start_idx]

    for i in range(start_idx + 1, len(highs)):
        atr_val = atrs[i]
        close_val = closes[i]
        if np.isnan(atr_val) or close_val == 0:
            continue

        threshold_pct = (atr_val / close_val) * 100.0 * atr_multiplier

        # Check if we moved up significantly from initial low
        if initial_low > 0:
            rise_pct = ((highs[i] - initial_low) / initial_low) * 100.0
            if rise_pct >= threshold_pct:
                # First significant move is UP, so we start tracking upward
                # (we want to find the first H pivot)
                return "UP"

        # Check if we moved down significantly from initial high
        if initial_high > 0:
            drop_pct = ((initial_high - lows[i]) / initial_high) * 100.0
            if drop_pct >= threshold_pct:
                # First significant move is DOWN, so we start tracking downward
                # (we want to find the first L pivot)
                return "DOWN"

        # Update running extremes while no threshold break
        if highs[i] > initial_high:
            initial_high = highs[i]
        if lows[i] < initial_low:
            initial_low = lows[i]

    # Default: assume UP if no significant move detected
    return "UP"


def _enforce_alternation(pivots: list[Pivot]) -> list[Pivot]:
    """
    Ensure strict H-L alternation by resolving consecutive same-type pivots.
    For consecutive H pivots, keep the highest. For consecutive L pivots, keep the lowest.
    """
    if len(pivots) <= 1:
        return pivots

    cleaned: list[Pivot] = [pivots[0]]

    for i in range(1, len(pivots)):
        if pivots[i].pivot_type == cleaned[-1].pivot_type:
            # Same type as previous -- keep the more extreme one
            if pivots[i].pivot_type == "H":
                if pivots[i].price > cleaned[-1].price:
                    cleaned[-1] = pivots[i]
            else:  # "L"
                if pivots[i].price < cleaned[-1].price:
                    cleaned[-1] = pivots[i]
        else:
            cleaned.append(pivots[i])

    return cleaned
