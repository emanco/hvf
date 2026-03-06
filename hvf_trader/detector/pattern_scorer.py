"""
8-component HVF pattern scorer (0-100, with KLOS adjustments).
Score >= SCORE_THRESHOLD to arm the pattern.
"""
import logging

import numpy as np
import pandas as pd

from hvf_trader.detector.hvf_detector import HVFPattern
from hvf_trader import config

logger = logging.getLogger(__name__)


def score_pattern(
    pattern: HVFPattern,
    df: pd.DataFrame,
    df_4h: pd.DataFrame = None,
    df_d1: pd.DataFrame = None,
) -> float:
    """
    Score a validated HVF pattern on 8 components.

    Components:
    1. Funnel tightness (0-20)
    2. Volume contraction (0-15)
    3. ATR contraction (0-15)
    4. RRR quality (0-20)
    5. EMA200 prior trend (0-10)
    6. Multi-TF confirmation (0-10)
    7. Session quality (0-10)
    8. KLOS key level confluence (bonus 0-10, penalty -10 to 0)

    Returns:
        Float score clamped to 0-100
    """
    score = 0.0

    # ─── Component 1: Funnel Tightness (0-20) ────────────────────────
    wave1_range = abs(pattern.h1.price - pattern.l1.price)
    wave3_range = abs(pattern.h3.price - pattern.l3.price)

    if wave1_range > 0:
        tightness_ratio = wave3_range / wave1_range
        tightness_ratio = min(max(tightness_ratio, 0.0), 1.0)
        tightness_score = 20.0 * (1.0 - tightness_ratio)
    else:
        tightness_score = 0.0
    score += tightness_score

    # ─── Component 2: Volume Contraction (0-15) ──────────────────────
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    has_volume = vol_col in df.columns

    wave1_start = min(pattern.h1.index, pattern.l1.index)
    wave1_end = max(pattern.h1.index, pattern.l1.index)
    wave3_start = min(pattern.h3.index, pattern.l3.index)
    wave3_end = max(pattern.h3.index, pattern.l3.index)

    if has_volume:
        wave1_vol = _safe_mean(df[vol_col], wave1_start, wave1_end)
        wave3_vol = _safe_mean(df[vol_col], wave3_start, wave3_end)

        if wave1_vol > 0:
            vol_ratio = wave3_vol / wave1_vol
            vol_ratio = min(max(vol_ratio, 0.0), 1.0)
            vol_score = 15.0 * (1.0 - vol_ratio)
        else:
            vol_score = 0.0
    else:
        vol_score = 0.0
    vol_score = min(max(vol_score, 0.0), 15.0)
    score += vol_score

    # ─── Component 3: ATR Contraction (0-15) ─────────────────────────
    if "atr" in df.columns:
        atr_wave1 = _safe_atr_at_pivot(df, wave1_end)
        atr_wave3 = _safe_atr_at_pivot(df, wave3_end)

        if atr_wave1 > 0:
            atr_ratio = atr_wave3 / atr_wave1
            atr_ratio = min(max(atr_ratio, 0.0), 1.0)
            atr_score = 15.0 * (1.0 - atr_ratio)
        else:
            atr_score = 0.0
    else:
        atr_score = 0.0
    atr_score = min(max(atr_score, 0.0), 15.0)
    score += atr_score

    # ─── Component 4: RRR Quality (0-20) ─────────────────────────────
    rrr_score = min(20.0, (pattern.rrr / 4.0) * 20.0)
    rrr_score = max(rrr_score, 0.0)
    score += rrr_score

    # ─── Component 5: EMA200 Prior Trend (0-10) ──────────────────────
    ema_trend_score = _compute_ema200_trend_score(pattern, df)
    score += ema_trend_score

    # ─── Component 6: Multi-TF Confirmation (0-10) ───────────────────
    mtf_score = _compute_multi_tf_score(pattern, df, df_4h)
    score += mtf_score

    # ─── Component 7: Session Quality (0-10) ──────────────────────────
    if pattern.detected_at is not None:
        session_score = _get_session_score(pattern.detected_at)
    else:
        session_score = 0.0
    score += session_score

    # ─── Component 8: KLOS Key Level Confluence (bonus/penalty) ───────
    klos_score = _compute_klos_score(pattern, df, df_4h, df_d1)
    score += klos_score

    return round(min(max(score, 0.0), 100.0), 2)


def _compute_klos_score(
    pattern: HVFPattern,
    df: pd.DataFrame,
    df_4h: pd.DataFrame = None,
    df_d1: pd.DataFrame = None,
) -> float:
    """
    KLOS scoring: confluence bonus (0-10) and rejection penalty (-10 to 0).
    """
    try:
        from hvf_trader.detector.klos import (
            identify_key_levels,
            score_klos_confluence,
            score_klos_rejection,
            check_target_obstruction,
        )
    except ImportError:
        return 0.0

    # Get current ATR at the pattern's last pivot
    last_pivot_idx = (
        pattern.l3.index if pattern.direction == "LONG" else pattern.h3.index
    )
    current_atr = _safe_atr_at_pivot(df, last_pivot_idx) if "atr" in df.columns else 0.0
    if current_atr <= 0:
        return 0.0

    key_levels_4h = []
    key_levels_d1 = []

    if df_4h is not None and "atr" in df_4h.columns:
        key_levels_4h = identify_key_levels(
            df_4h, "H4", n_pivots=config.KLOS_4H_PIVOT_COUNT
        )
    if df_d1 is not None and "atr" in df_d1.columns:
        key_levels_d1 = identify_key_levels(
            df_d1, "D1", n_pivots=config.KLOS_D1_PIVOT_COUNT
        )

    if not key_levels_4h and not key_levels_d1:
        return 0.0

    confluence = score_klos_confluence(
        pattern.entry_price, pattern.direction,
        key_levels_4h, key_levels_d1, current_atr,
    )
    rejection = score_klos_rejection(
        pattern.entry_price, pattern.direction,
        key_levels_4h, key_levels_d1, current_atr,
    )

    # Log target obstruction warning (metadata only)
    obstruction = check_target_obstruction(
        pattern.entry_price, pattern.target_2, pattern.direction,
        key_levels_4h, key_levels_d1, current_atr,
    )
    if obstruction:
        logger.debug("KLOS %s %s: %s", pattern.symbol, pattern.direction, obstruction)

    return confluence + rejection


def _compute_ema200_trend_score(pattern: HVFPattern, df: pd.DataFrame) -> float:
    """
    Score EMA200 prior trend alignment.
    10 if price clearly on correct side of EMA200.
    5 if near EMA200 (within 0.5%).
    0 if on wrong side.
    """
    if "ema_200" not in df.columns or pattern.h1.index >= len(df):
        return 5.0  # Neutral when no data

    ema_at_h1 = df["ema_200"].iloc[pattern.h1.index]
    if np.isnan(ema_at_h1) or ema_at_h1 == 0:
        return 5.0

    if pattern.direction == "LONG":
        distance_pct = ((pattern.h1.price - ema_at_h1) / ema_at_h1) * 100.0
    else:
        # For SHORT: h1 should be below EMA200 for bearish trend alignment
        distance_pct = ((ema_at_h1 - pattern.h1.price) / ema_at_h1) * 100.0

    if distance_pct > 0.5:
        return 10.0  # Clearly on correct side
    elif distance_pct > -0.5:
        return 5.0   # Near EMA — neutral
    else:
        return 0.0   # Wrong side


def _safe_mean(series: pd.Series, start_idx: int, end_idx: int) -> float:
    """Compute mean of a series slice, handling boundary conditions."""
    start = max(0, start_idx)
    end = min(len(series), end_idx + 1)
    if start >= end:
        return 0.0
    segment = series.iloc[start:end]
    valid = segment.dropna()
    return float(valid.mean()) if len(valid) > 0 else 0.0


def _safe_atr_at_pivot(df: pd.DataFrame, bar_index: int) -> float:
    """Get ATR value at a specific bar index, with safe fallback."""
    idx = min(bar_index, len(df) - 1)
    idx = max(idx, 0)
    val = df["atr"].iloc[idx]
    if np.isnan(val):
        # Walk backward to find the nearest valid ATR
        for j in range(idx - 1, -1, -1):
            v = df["atr"].iloc[j]
            if not np.isnan(v):
                return float(v)
        return 0.0
    return float(val)


def _compute_multi_tf_score(
    pattern: HVFPattern,
    df: pd.DataFrame,
    df_4h: pd.DataFrame = None,
) -> float:
    """
    Score multi-timeframe alignment.
    10 if 4H trend agrees with pattern direction.
    5 if neutral (no clear trend or no 4H data).
    0 if 4H trend opposes pattern direction.
    """
    if df_4h is None or "ema_200" not in df_4h.columns or len(df_4h) == 0:
        return 5.0  # Neutral when no 4H data available

    # Find the 4H bar closest to the pattern's last pivot
    last_pivot_idx = (
        pattern.l3.index if pattern.direction == "LONG" else pattern.h3.index
    )

    if "time" in df.columns and "time" in df_4h.columns and last_pivot_idx < len(df):
        pattern_time = df["time"].iloc[last_pivot_idx]
        mask = df_4h["time"] <= pattern_time
        if not mask.any():
            return 5.0

        closest_4h_pos = df_4h.loc[mask].index[-1]
        ema_4h = df_4h["ema_200"].iloc[closest_4h_pos]
        close_4h = df_4h["close"].iloc[closest_4h_pos]

        if np.isnan(ema_4h):
            return 5.0

        # Compute relative position: how far price is from EMA as a percentage
        ema_distance_pct = ((close_4h - ema_4h) / ema_4h) * 100.0

        if pattern.direction == "LONG":
            if ema_distance_pct > 0.5:
                return 10.0   # Clearly above EMA -- agrees with LONG
            elif ema_distance_pct < -0.5:
                return 0.0    # Clearly below EMA -- opposes LONG
            else:
                return 5.0    # Near EMA -- neutral
        else:  # SHORT
            if ema_distance_pct < -0.5:
                return 10.0   # Clearly below EMA -- agrees with SHORT
            elif ema_distance_pct > 0.5:
                return 0.0    # Clearly above EMA -- opposes SHORT
            else:
                return 5.0    # Near EMA -- neutral
    else:
        # Fallback: use last available 4H bar
        ema_4h = df_4h["ema_200"].iloc[-1]
        close_4h = df_4h["close"].iloc[-1]

        if np.isnan(ema_4h):
            return 5.0

        if pattern.direction == "LONG":
            return 10.0 if close_4h > ema_4h else 0.0
        else:
            return 10.0 if close_4h < ema_4h else 0.0


def _get_session_score(timestamp: pd.Timestamp) -> float:
    """Score based on Kill Zone at pattern detection time."""
    hour = timestamp.hour  # UTC

    # Kill Zone scoring (higher granularity than simple session)
    kz = get_current_kill_zone(hour)
    if kz == "ny_morning":
        return 10.0  # London-NY overlap = highest liquidity
    elif kz == "london":
        return 8.0
    elif kz == "ny_evening":
        return 6.0
    elif kz == "asian":
        return 3.0

    # Outside KZ: check broad sessions
    london = config.LONDON_OPEN <= hour < config.LONDON_CLOSE
    ny = config.NY_OPEN <= hour < config.NY_CLOSE
    if london or ny:
        return 4.0
    return 0.0


def get_current_kill_zone(hour: int) -> str | None:
    """Return the name of the current Kill Zone for a UTC hour, or None."""
    for kz_name, (start, end) in config.KILL_ZONES_UTC.items():
        if start <= hour <= end:
            return kz_name
    return None
