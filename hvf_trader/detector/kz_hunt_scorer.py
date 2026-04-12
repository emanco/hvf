"""
Kill Zone Hunt scorer (0-100).

Components:
1. Rejection quality (0-25): wick-to-body ratio
2. KZ range quality (0-20): range relative to ATR
3. EMA200 alignment (0-20): distance from EMA in correct direction
4. Volume confirmation (0-15): rejection bar volume vs average
5. Kill Zone timing (0-20): which KZ and proximity to extreme
"""
import numpy as np
import pandas as pd

from hvf_trader.detector.kz_hunt_detector import KZHuntPattern
from hvf_trader.detector.pattern_scorer import get_current_kill_zone
from hvf_trader import config


def score_kz_hunt(pattern: KZHuntPattern, df: pd.DataFrame) -> float:
    """Score a validated KZ Hunt pattern on 5 components."""
    score = 0.0
    idx = pattern.rejection_bar_idx
    if idx in df.index:
        bar = df.loc[idx]
    else:
        bar = df.iloc[-1]  # fallback: last bar in window
        idx = df.index[-1]

    # ─── 1. Rejection Quality (0-25) ──────────────────────────────────
    body = abs(bar["close"] - bar["open"])
    if body == 0:
        body = 0.00001

    if pattern.direction == "LONG":
        wick = min(bar["open"], bar["close"]) - bar["low"]
    else:
        wick = bar["high"] - max(bar["open"], bar["close"])

    wick_ratio = wick / body
    # 2x = minimum, 4x+ = full marks
    rejection_score = min(25.0, max(0.0, (wick_ratio - 2.0) / 2.0 * 25.0))
    score += rejection_score

    # ─── 2. KZ Range Quality (0-20) ───────────────────────────────────
    atr = bar.get("atr", 0)
    if not np.isnan(atr) and atr > 0:
        range_atr = pattern.kz_range / atr
        # Ideal range is 1-3x ATR. Too narrow (< 0.5x) or too wide (> 5x) = poor
        if 1.0 <= range_atr <= 3.0:
            range_score = 20.0
        elif 0.5 <= range_atr < 1.0:
            range_score = 10.0
        elif 3.0 < range_atr <= 5.0:
            range_score = 10.0
        else:
            range_score = 0.0
    else:
        range_score = 10.0
    score += range_score

    # ─── 3. EMA200 Alignment (0-20) ───────────────────────────────────
    if "ema_200" in df.columns:
        ema = df["ema_200"].loc[idx] if idx in df.index else df["ema_200"].iloc[-1]
        close = bar["close"]
        if not np.isnan(ema) and ema > 0:
            distance_pct = ((close - ema) / ema) * 100.0
            if pattern.direction == "LONG":
                if distance_pct > 0.5:
                    ema_score = 20.0
                elif distance_pct > -0.5:
                    ema_score = 10.0
                else:
                    ema_score = 0.0
            else:
                if distance_pct < -0.5:
                    ema_score = 20.0
                elif distance_pct < 0.5:
                    ema_score = 10.0
                else:
                    ema_score = 0.0
        else:
            ema_score = 10.0
    else:
        ema_score = 10.0
    score += ema_score

    # ─── 4. Volume Confirmation (0-15) ────────────────────────────────
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    if vol_col in df.columns:
        bar_vol = bar[vol_col]
        # Use label-based position for volume average window
        idx_pos = df.index.get_loc(idx) if idx in df.index else len(df) - 1
        avg_vol = df[vol_col].iloc[max(0, idx_pos - 20):idx_pos].mean() if idx_pos > 1 else 0
        if avg_vol > 0 and not np.isnan(bar_vol):
            vol_ratio = bar_vol / avg_vol
            if vol_ratio >= 1.5:
                vol_score = 15.0
            elif vol_ratio >= 1.2:
                vol_score = 10.0
            elif vol_ratio >= 1.0:
                vol_score = 5.0
            else:
                vol_score = 0.0
        else:
            vol_score = 7.5
    else:
        vol_score = 7.5
    score += vol_score

    # ─── 5. Kill Zone Timing (0-20) ───────────────────────────────────
    if pattern.detected_at is not None:
        kz = get_current_kill_zone(pattern.detected_at.hour)
        if kz == pattern.kz_name:
            kz_score = 20.0  # Rejection happened during same KZ = strongest
        elif kz in ("london", "ny_morning"):
            kz_score = 15.0
        elif kz == "ny_evening":
            kz_score = 10.0
        elif kz == "asian":
            kz_score = 5.0
        else:
            kz_score = 0.0
    else:
        kz_score = 0.0
    score += kz_score

    return round(min(max(score, 0.0), 100.0), 2)
