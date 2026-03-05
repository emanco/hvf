"""
6-component pattern scorer (0-100).
Score >= 70 to arm the pattern.
"""
import numpy as np
import pandas as pd

from hvf_trader.detector.hvf_detector import HVFPattern
from hvf_trader import config


def score_pattern(
    pattern: HVFPattern,
    df: pd.DataFrame,
    df_4h: pd.DataFrame = None,
) -> float:
    """
    Score a validated HVF pattern on 6 components.

    Components:
    1. Funnel tightness (0-25):  25 * (1 - (h3-l3)/(h1-l1))
    2. Volume contraction (0-20): 20 * (1 - wave3_avg_vol/wave1_avg_vol), clamped 0-20
    3. ATR contraction (0-20): 20 * (1 - atr_at_wave3/atr_at_wave1), clamped 0-20
    4. RRR quality (0-20): min(20, (rrr / 10) * 20) -- 10:1+ gets full marks
    5. Multi-TF confirmation (0-10): 10 if 4H trend agrees, 5 if neutral, 0 if against
    6. Session quality (0-5): 5 London/NY overlap, 3 London or NY, 1 Asian, 0 off-hours

    Returns:
        Float score 0-100
    """
    score = 0.0

    # ─── Component 1: Funnel Tightness (0-25) ────────────────────────
    wave1_range = abs(pattern.h1.price - pattern.l1.price)
    wave3_range = abs(pattern.h3.price - pattern.l3.price)

    if wave1_range > 0:
        tightness_ratio = wave3_range / wave1_range
        # Clamp ratio to [0, 1] before computing score
        tightness_ratio = min(max(tightness_ratio, 0.0), 1.0)
        tightness_score = 25.0 * (1.0 - tightness_ratio)
    else:
        tightness_score = 0.0
    score += tightness_score

    # ─── Component 2: Volume Contraction (0-20) ──────────────────────
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
            vol_score = 20.0 * (1.0 - vol_ratio)
        else:
            vol_score = 0.0
    else:
        vol_score = 0.0
    vol_score = min(max(vol_score, 0.0), 20.0)
    score += vol_score

    # ─── Component 3: ATR Contraction (0-20) ─────────────────────────
    if "atr" in df.columns:
        atr_wave1 = _safe_atr_at_pivot(df, wave1_end)
        atr_wave3 = _safe_atr_at_pivot(df, wave3_end)

        if atr_wave1 > 0:
            atr_ratio = atr_wave3 / atr_wave1
            atr_ratio = min(max(atr_ratio, 0.0), 1.0)
            atr_score = 20.0 * (1.0 - atr_ratio)
        else:
            atr_score = 0.0
    else:
        atr_score = 0.0
    atr_score = min(max(atr_score, 0.0), 20.0)
    score += atr_score

    # ─── Component 4: RRR Quality (0-20) ─────────────────────────────
    rrr_score = min(20.0, (pattern.rrr / 10.0) * 20.0)
    rrr_score = max(rrr_score, 0.0)
    score += rrr_score

    # ─── Component 5: Multi-TF Confirmation (0-10) ───────────────────
    mtf_score = _compute_multi_tf_score(pattern, df, df_4h)
    score += mtf_score

    # ─── Component 6: Session Quality (0-5) ──────────────────────────
    if pattern.detected_at is not None:
        session_score = _get_session_score(pattern.detected_at)
    else:
        session_score = 0.0
    score += session_score

    return round(score, 2)


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
    """Score based on trading session at pattern detection time."""
    hour = timestamp.hour  # UTC

    london_ny_overlap = config.NY_OPEN <= hour < config.LONDON_CLOSE  # 13-16 UTC
    london = config.LONDON_OPEN <= hour < config.LONDON_CLOSE
    ny = config.NY_OPEN <= hour < config.NY_CLOSE
    asian = config.ASIAN_OPEN <= hour < config.ASIAN_CLOSE

    if london_ny_overlap:
        return 5.0
    elif london or ny:
        return 3.0
    elif asian:
        return 1.0
    return 0.0
