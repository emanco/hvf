"""
Wedge Pattern Scorer — quality assessment 0-100.

7 components:
  1. Trendline fit (R-squared)      0-20
  2. Touch count                     0-15
  3. Convergence quality             0-15
  4. Volume contraction              0-15
  5. RSI divergence                  0-15
  6. Duration appropriateness        0-10
  7. EMA200 trend alignment          0-10
                                    ──────
                                     0-100
"""
import logging

import numpy as np
import pandas as pd

from hvf_trader.detector.wedge_detector import WedgePattern

logger = logging.getLogger(__name__)


def score_wedge(
    wedge: WedgePattern,
    df: pd.DataFrame,
) -> float:
    """
    Score wedge quality from 0 to 100.

    Args:
        wedge: detected WedgePattern
        df: OHLCV DataFrame with indicators (atr, ema_200, rsi, tick_volume)

    Returns:
        Score 0-100
    """
    score = 0.0

    # 1. Trendline fit quality (0-20)
    avg_r2 = (wedge.upper_r_squared + wedge.lower_r_squared) / 2
    if avg_r2 >= 0.95:
        score += 20
    elif avg_r2 >= 0.90:
        score += 15
    elif avg_r2 >= 0.85:
        score += 10
    elif avg_r2 >= 0.80:
        score += 5

    # 2. Touch count (0-15)
    min_touches = min(len(wedge.upper_touches), len(wedge.lower_touches))
    if min_touches >= 5:
        score += 15
    elif min_touches >= 4:
        score += 12
    elif min_touches >= 3:
        score += 8

    # 3. Convergence quality (0-15)
    if wedge.widest_range > 0:
        range_at_end = (wedge.upper_slope * wedge.end_index + wedge.upper_intercept) - \
                       (wedge.lower_slope * wedge.end_index + wedge.lower_intercept)
        convergence_pct = 1.0 - (range_at_end / wedge.widest_range)
    else:
        convergence_pct = 0

    if convergence_pct >= 0.70:
        score += 15
    elif convergence_pct >= 0.50:
        score += 10
    elif convergence_pct >= 0.30:
        score += 5

    # 4. Volume contraction (0-15)
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    if vol_col in df.columns:
        mid_idx = (wedge.start_index + wedge.end_index) // 2
        # Clamp to valid range
        s_idx = max(0, wedge.start_index)
        e_idx = min(len(df), wedge.end_index + 1)
        m_idx = max(s_idx + 1, mid_idx)

        first_half_vol = df[vol_col].iloc[s_idx:m_idx].mean()
        second_half_vol = df[vol_col].iloc[m_idx:e_idx].mean()

        if first_half_vol > 0:
            vol_ratio = second_half_vol / first_half_vol
            if vol_ratio < 0.70:
                score += 15  # Strong volume contraction
            elif vol_ratio < 0.85:
                score += 10
            elif vol_ratio < 1.0:
                score += 5

    # 5. RSI divergence (0-15)
    if "rsi" in df.columns:
        score += _score_rsi_divergence(wedge, df)

    # 6. Duration appropriateness (0-10)
    duration = wedge.end_index - wedge.start_index
    # Sweet spot for D1: 20-80 bars (1-4 months)
    if 20 <= duration <= 80:
        score += 10
    elif 15 <= duration < 20 or 80 < duration <= 120:
        score += 5

    # 7. EMA200 trend alignment (0-10)
    if "ema_200" in df.columns:
        ema_idx = min(wedge.end_index, len(df) - 1)
        ema_val = df["ema_200"].iloc[ema_idx]
        close_val = df["close"].iloc[ema_idx]

        if not np.isnan(ema_val):
            if wedge.direction == "LONG" and close_val > ema_val:
                score += 10  # Bullish breakout above EMA200 — trend aligned
            elif wedge.direction == "SHORT" and close_val < ema_val:
                score += 10  # Bearish breakout below EMA200
            elif wedge.direction == "LONG" and close_val < ema_val:
                score += 3   # Counter-trend — lower confidence
            elif wedge.direction == "SHORT" and close_val > ema_val:
                score += 3

    final = min(score, 100.0)

    logger.debug(
        "Wedge score %s %s %s: %.0f (R2=%.2f touches=%d conv=%.0f%%)",
        wedge.symbol, wedge.wedge_type, wedge.direction, final,
        avg_r2, min_touches, convergence_pct * 100,
    )

    return final


def _score_rsi_divergence(wedge: WedgePattern, df: pd.DataFrame) -> float:
    """
    Check for RSI divergence that confirms the expected breakout direction.

    Rising wedge + bearish RSI divergence (price higher highs, RSI lower highs) = bearish confirm
    Falling wedge + bullish RSI divergence (price lower lows, RSI higher lows) = bullish confirm
    """
    if wedge.wedge_type == "RISING_WEDGE":
        touches = wedge.upper_touches
        if len(touches) < 2:
            return 0.0

        prev_idx, prev_price = touches[-2]
        last_idx, last_price = touches[-1]

        if prev_idx >= len(df) or last_idx >= len(df):
            return 0.0

        rsi_prev = df["rsi"].iloc[prev_idx]
        rsi_last = df["rsi"].iloc[last_idx]

        if np.isnan(rsi_prev) or np.isnan(rsi_last):
            return 0.0

        # Price making higher highs but RSI making lower highs = bearish divergence
        if last_price > prev_price and rsi_last < rsi_prev:
            return 15.0

    elif wedge.wedge_type == "FALLING_WEDGE":
        touches = wedge.lower_touches
        if len(touches) < 2:
            return 0.0

        prev_idx, prev_price = touches[-2]
        last_idx, last_price = touches[-1]

        if prev_idx >= len(df) or last_idx >= len(df):
            return 0.0

        rsi_prev = df["rsi"].iloc[prev_idx]
        rsi_last = df["rsi"].iloc[last_idx]

        if np.isnan(rsi_prev) or np.isnan(rsi_last):
            return 0.0

        # Price making lower lows but RSI making higher lows = bullish divergence
        if last_price < prev_price and rsi_last > rsi_prev:
            return 15.0

    return 0.0
