"""
Viper pattern scorer (0-100).

Components:
1. Impulse strength (0-25): how far above 2*ATR threshold
2. Retracement quality (0-25): closer to 38.2% fib is ideal
3. RSI confirmation (0-20): RSI strength during retrace
4. MACD alignment (0-15): MACD histogram direction
5. Session quality (0-15): Kill Zone scoring
"""
import numpy as np
import pandas as pd

from hvf_trader.detector.viper_detector import ViperPattern
from hvf_trader.detector.pattern_scorer import get_current_kill_zone
from hvf_trader import config


def score_viper(pattern: ViperPattern, df: pd.DataFrame) -> float:
    """Score a validated Viper pattern on 5 components."""
    score = 0.0

    # ─── 1. Impulse Strength (0-25) ───────────────────────────────────
    atr_at_impulse = _safe_atr(df, pattern.impulse_end_idx)
    if atr_at_impulse > 0:
        # How many ATRs is the impulse? 2x = 0pts, 4x+ = 25pts
        atr_multiple = pattern.impulse_range / atr_at_impulse
        impulse_score = min(25.0, max(0.0, (atr_multiple - 2.0) / 2.0 * 25.0))
    else:
        impulse_score = 0.0
    score += impulse_score

    # ─── 2. Retracement Quality (0-25) ────────────────────────────────
    # Ideal retracement is 38.2% Fibonacci. Score drops as it deviates.
    ideal_fib = 0.382
    fib_deviation = abs(pattern.retrace_fib_level - ideal_fib)
    # Max deviation from ideal within valid range (0.236-0.618) is ~0.236
    retrace_score = max(0.0, 25.0 * (1.0 - fib_deviation / 0.236))
    score += retrace_score

    # ─── 3. RSI Confirmation (0-20) ───────────────────────────────────
    if "rsi" in df.columns:
        rsi_at_retrace = df["rsi"].iloc[min(pattern.retrace_end_idx, len(df) - 1)]
        if not np.isnan(rsi_at_retrace):
            if pattern.direction == "LONG":
                # RSI 50-70 is strong, 40-50 is moderate
                if rsi_at_retrace >= 60:
                    rsi_score = 20.0
                elif rsi_at_retrace >= 50:
                    rsi_score = 15.0
                elif rsi_at_retrace >= 40:
                    rsi_score = 8.0
                else:
                    rsi_score = 0.0
            else:
                if rsi_at_retrace <= 40:
                    rsi_score = 20.0
                elif rsi_at_retrace <= 50:
                    rsi_score = 15.0
                elif rsi_at_retrace <= 60:
                    rsi_score = 8.0
                else:
                    rsi_score = 0.0
        else:
            rsi_score = 10.0  # Neutral
    else:
        rsi_score = 10.0
    score += rsi_score

    # ─── 4. MACD Alignment (0-15) ─────────────────────────────────────
    if "macd_hist" in df.columns:
        hist_val = df["macd_hist"].iloc[min(pattern.retrace_end_idx, len(df) - 1)]
        if not np.isnan(hist_val):
            if pattern.direction == "LONG" and hist_val > 0:
                macd_score = min(15.0, abs(hist_val) * 1000 * 15.0)  # Scale
            elif pattern.direction == "SHORT" and hist_val < 0:
                macd_score = min(15.0, abs(hist_val) * 1000 * 15.0)
            else:
                macd_score = 0.0
        else:
            macd_score = 7.5
    else:
        macd_score = 7.5
    score += min(macd_score, 15.0)

    # ─── 5. Session Quality (0-15) ────────────────────────────────────
    if pattern.detected_at is not None:
        kz = get_current_kill_zone(pattern.detected_at.hour)
        if kz == "ny_morning":
            session_score = 15.0
        elif kz == "london":
            session_score = 12.0
        elif kz == "ny_evening":
            session_score = 8.0
        elif kz == "asian":
            session_score = 4.0
        else:
            session_score = 0.0
    else:
        session_score = 0.0
    score += session_score

    return round(min(max(score, 0.0), 100.0), 2)


def _safe_atr(df: pd.DataFrame, bar_index: int) -> float:
    """Get ATR at index with fallback."""
    idx = min(max(bar_index, 0), len(df) - 1)
    val = df["atr"].iloc[idx]
    if np.isnan(val):
        valid = df["atr"].dropna()
        return float(valid.iloc[-1]) if len(valid) > 0 else 0.0
    return float(val)
