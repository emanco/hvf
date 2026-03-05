"""
London Sweep scorer (0-100).

Components:
1. Sweep depth (0-25): how far past Asian extreme the sweep went
2. Rejection quality (0-25): wick-to-body ratio and close position
3. Asian range quality (0-20): range size relative to ATR
4. Volume spike (0-15): sweep bar volume vs average
5. Time precision (0-15): how close to London open the sweep occurred
"""
import numpy as np
import pandas as pd

from hvf_trader.detector.london_sweep_detector import LondonSweepPattern
from hvf_trader import config


def score_london_sweep(pattern: LondonSweepPattern, df: pd.DataFrame) -> float:
    """Score a validated London Sweep pattern on 5 components."""
    score = 0.0
    idx = min(pattern.sweep_bar_idx, len(df) - 1)
    bar = df.iloc[idx]

    # ─── 1. Sweep Depth (0-25) ────────────────────────────────────────
    atr = bar.get("atr", 0)
    if not np.isnan(atr) and atr > 0:
        if pattern.direction == "LONG":
            sweep_depth = pattern.asian_low - pattern.sweep_extreme
        else:
            sweep_depth = pattern.sweep_extreme - pattern.asian_high

        # Ideal sweep depth: 0.3-1.0x ATR. Too shallow = weak, too deep = momentum
        depth_atr = sweep_depth / atr if atr > 0 else 0
        if 0.3 <= depth_atr <= 1.0:
            sweep_score = 25.0
        elif 0.1 <= depth_atr < 0.3:
            sweep_score = 15.0
        elif 1.0 < depth_atr <= 2.0:
            sweep_score = 10.0
        else:
            sweep_score = 0.0
    else:
        sweep_score = 12.5
    score += sweep_score

    # ─── 2. Rejection Quality (0-25) ──────────────────────────────────
    body = abs(bar["close"] - bar["open"])
    if body == 0:
        body = 0.00001

    if pattern.direction == "LONG":
        wick = min(bar["open"], bar["close"]) - bar["low"]
        # How far inside the range did it close? (closer to middle = better)
        range_position = (bar["close"] - pattern.asian_low) / pattern.asian_range if pattern.asian_range > 0 else 0
    else:
        wick = bar["high"] - max(bar["open"], bar["close"])
        range_position = (pattern.asian_high - bar["close"]) / pattern.asian_range if pattern.asian_range > 0 else 0

    wick_ratio = wick / body
    # 1.5x = minimum, 3x+ = full marks
    wick_score = min(15.0, max(0.0, (wick_ratio - 1.5) / 1.5 * 15.0))
    # Close position bonus (0-10): further inside range = better
    position_score = min(10.0, range_position * 10.0)
    score += wick_score + position_score

    # ─── 3. Asian Range Quality (0-20) ────────────────────────────────
    if not np.isnan(atr) and atr > 0:
        range_atr = pattern.asian_range / atr
        # Ideal: 0.5-2.0x ATR
        if 0.5 <= range_atr <= 2.0:
            range_score = 20.0
        elif 0.3 <= range_atr < 0.5:
            range_score = 10.0
        elif 2.0 < range_atr <= 3.0:
            range_score = 10.0
        else:
            range_score = 0.0
    else:
        range_score = 10.0
    score += range_score

    # ─── 4. Volume Spike (0-15) ───────────────────────────────────────
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    if vol_col in df.columns:
        bar_vol = bar[vol_col]
        avg_vol = df[vol_col].iloc[max(0, idx - 20):idx].mean() if idx > 1 else 0
        if avg_vol > 0 and not np.isnan(bar_vol):
            vol_ratio = bar_vol / avg_vol
            if vol_ratio >= 2.0:
                vol_score = 15.0
            elif vol_ratio >= 1.5:
                vol_score = 10.0
            elif vol_ratio >= 1.2:
                vol_score = 5.0
            else:
                vol_score = 0.0
        else:
            vol_score = 7.5
    else:
        vol_score = 7.5
    score += vol_score

    # ─── 5. Time Precision (0-15) ─────────────────────────────────────
    if pattern.detected_at is not None:
        hour = pattern.detected_at.hour
        # 07:00-08:00 = best (first hour of London), 08:00-09:00 = good
        if 7 <= hour < 8:
            time_score = 15.0
        elif 8 <= hour < 9:
            time_score = 12.0
        elif 9 <= hour < 10:
            time_score = 8.0
        elif 6 <= hour < 7:
            time_score = 5.0  # Slightly early
        else:
            time_score = 0.0
    else:
        time_score = 0.0
    score += time_score

    return round(min(max(score, 0.0), 100.0), 2)
