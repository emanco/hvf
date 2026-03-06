"""
Viper pattern scorer (0-100) — v3 with EMA200 trend + regime filter.

Components:
1. Impulse strength (0-20): how far above 2.5*ATR threshold
2. Retracement quality (0-20): closer to 38.2% fib is ideal
3. RSI confirmation (0-20): RSI strength during retrace
4. MACD alignment (0-15): MACD histogram direction and strength
5. EMA200 trend (0-10): distance from EMA confirms trend strength
6. Session quality (0-15): Kill Zone scoring
7. Regime strength (-15 to +10): EMA slope + DI direction alignment
"""
import numpy as np
import pandas as pd

from hvf_trader.detector.viper_detector import ViperPattern, VIPER_MIN_IMPULSE_ATR
from hvf_trader.detector.pattern_scorer import get_current_kill_zone
from hvf_trader import config


def score_viper(pattern: ViperPattern, df: pd.DataFrame) -> float:
    """Score a validated Viper pattern on 6 components."""
    score = 0.0

    # ─── 1. Impulse Strength (0-20) ───────────────────────────────────
    atr_at_impulse = _safe_atr(df, pattern.impulse_end_idx)
    if atr_at_impulse > 0:
        # How many ATRs is the impulse? 2.0x = 0pts, 4.5x+ = 20pts
        atr_multiple = pattern.impulse_range / atr_at_impulse
        impulse_score = min(20.0, max(0.0, (atr_multiple - VIPER_MIN_IMPULSE_ATR) / 2.5 * 20.0))
    else:
        impulse_score = 0.0
    score += impulse_score

    # ─── 2. Retracement Quality (0-20) ────────────────────────────────
    # Ideal retracement is 38.2% Fibonacci. Score drops as it deviates.
    ideal_fib = 0.382
    fib_deviation = abs(pattern.retrace_fib_level - ideal_fib)
    # Max deviation from ideal within valid range (0.236-0.500) is ~0.146
    retrace_score = max(0.0, 20.0 * (1.0 - fib_deviation / 0.15))
    score += retrace_score

    # ─── 3. RSI Confirmation (0-20) ───────────────────────────────────
    if "rsi" in df.columns:
        rsi_at_retrace = df["rsi"].iloc[min(pattern.retrace_end_idx, len(df) - 1)]
        if not np.isnan(rsi_at_retrace):
            if pattern.direction == "LONG":
                # RSI 55-70 is strong, 50-55 moderate, 45-50 weak
                if rsi_at_retrace >= 60:
                    rsi_score = 20.0
                elif rsi_at_retrace >= 55:
                    rsi_score = 15.0
                elif rsi_at_retrace >= 50:
                    rsi_score = 10.0
                elif rsi_at_retrace >= 45:
                    rsi_score = 5.0
                else:
                    rsi_score = 0.0
            else:
                if rsi_at_retrace <= 40:
                    rsi_score = 20.0
                elif rsi_at_retrace <= 45:
                    rsi_score = 15.0
                elif rsi_at_retrace <= 50:
                    rsi_score = 10.0
                elif rsi_at_retrace <= 55:
                    rsi_score = 5.0
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
                macd_score = min(15.0, abs(hist_val) * 1000 * 15.0)
            elif pattern.direction == "SHORT" and hist_val < 0:
                macd_score = min(15.0, abs(hist_val) * 1000 * 15.0)
            else:
                macd_score = 0.0
        else:
            macd_score = 7.5
    else:
        macd_score = 7.5
    score += min(macd_score, 15.0)

    # ─── 5. EMA200 Trend Strength (0-10) ─────────────────────────────
    ema_score = 0.0
    if "ema_200" in df.columns:
        idx = min(pattern.retrace_end_idx, len(df) - 1)
        ema_val = df["ema_200"].iloc[idx]
        close_val = df["close"].iloc[idx]
        if not np.isnan(ema_val) and atr_at_impulse > 0:
            distance_from_ema = abs(close_val - ema_val) / atr_at_impulse
            if pattern.direction == "LONG" and close_val > ema_val:
                # Further above EMA = stronger trend, cap at 2 ATR distance
                ema_score = min(10.0, distance_from_ema / 2.0 * 10.0)
            elif pattern.direction == "SHORT" and close_val < ema_val:
                ema_score = min(10.0, distance_from_ema / 2.0 * 10.0)
            # Wrong side of EMA: 0 (already filtered in detector, but safety)
    score += ema_score

    # ─── 6. Session Quality (0-15) ────────────────────────────────────
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

    # ─── 7. Regime Strength (-15 to +10) ────────────────────────────────
    regime_score = 0.0
    if "ema_200" in df.columns and len(df) > config.VIPER_REGIME_EMA_LOOKBACK:
        idx = min(pattern.retrace_end_idx, len(df) - 1)
        lookback = config.VIPER_REGIME_EMA_LOOKBACK

        # EMA200 slope over lookback period
        ema_now = df["ema_200"].iloc[idx]
        ema_prev = df["ema_200"].iloc[max(0, idx - lookback)]
        if not np.isnan(ema_now) and not np.isnan(ema_prev) and ema_prev > 0:
            ema_slope = (ema_now - ema_prev) / ema_prev

            # DI direction (if available)
            di_favors_short = True  # Default: neutral
            if "plus_di" in df.columns and "minus_di" in df.columns:
                pdi = df["plus_di"].iloc[idx]
                mdi = df["minus_di"].iloc[idx]
                if not np.isnan(pdi) and not np.isnan(mdi):
                    di_favors_short = mdi > pdi

            # ADX strength
            adx_val = df["adx"].iloc[idx] if "adx" in df.columns else 20.0
            adx_strong = adx_val > config.VIPER_REGIME_ADX_THRESHOLD if not np.isnan(adx_val) else False

            slope_threshold = config.VIPER_REGIME_EMA_SLOPE_THRESHOLD

            if pattern.direction == "SHORT":
                if ema_slope > slope_threshold and not di_favors_short:
                    regime_score = -15.0  # Strong adverse regime
                elif ema_slope > slope_threshold or not di_favors_short:
                    regime_score = -8.0
                elif abs(ema_slope) <= slope_threshold and not adx_strong:
                    regime_score = -3.0   # No clear trend
                elif ema_slope < -slope_threshold and di_favors_short:
                    regime_score = 10.0 if adx_strong else 5.0
                else:
                    regime_score = 0.0
            else:
                # LONG (not currently used, but symmetric for future)
                if ema_slope < -slope_threshold and di_favors_short:
                    regime_score = -15.0
                elif ema_slope < -slope_threshold or di_favors_short:
                    regime_score = -8.0
                elif abs(ema_slope) <= slope_threshold and not adx_strong:
                    regime_score = -3.0
                elif ema_slope > slope_threshold and not di_favors_short:
                    regime_score = 10.0 if adx_strong else 5.0
                else:
                    regime_score = 0.0

    score += regime_score

    return round(min(max(score, 0.0), 100.0), 2)


def _safe_atr(df: pd.DataFrame, bar_index: int) -> float:
    """Get ATR at index with fallback."""
    idx = min(max(bar_index, 0), len(df) - 1)
    val = df["atr"].iloc[idx]
    if np.isnan(val):
        valid = df["atr"].dropna()
        return float(valid.iloc[-1]) if len(valid) > 0 else 0.0
    return float(val)
