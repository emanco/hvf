"""
Trend Ride scorer (0-100).

Components:
1. ADX strength (0-25): stronger trend = better signal
2. DI spread (0-20): wider gap between +DI and -DI = stronger directionality
3. EMA200 alignment (0-20): distance from EMA confirms trend
4. Volume confirmation (0-15): breakout bar volume vs average
5. Kill Zone timing (0-20): London/NY overlap = best liquidity
"""
import numpy as np
import pandas as pd

from hvf_trader.detector.trend_ride_detector import TrendRidePattern
from hvf_trader.detector.pattern_scorer import get_current_kill_zone
from hvf_trader import config


def score_trend_ride(pattern: TrendRidePattern, df: pd.DataFrame) -> float:
    """Score a validated Trend Ride breakout pattern on 5 components."""
    score = 0.0
    idx = pattern.breakout_bar_idx
    if idx in df.index:
        bar = df.loc[idx]
    else:
        bar = df.iloc[-1]
        idx = df.index[-1]

    # ─── 1. ADX Strength (0-25) ──────────────────────────────────────
    adx = bar.get("adx", 0)
    if not np.isnan(adx):
        # ADX 20 = minimum (score 0), ADX 40+ = full marks
        adx_score = min(25.0, max(0.0, (adx - 20.0) / 20.0 * 25.0))
    else:
        adx_score = 0.0
    score += adx_score

    # ─── 2. DI Spread (0-20) ─────────────────────────────────────────
    plus_di = bar.get("plus_di", 0)
    minus_di = bar.get("minus_di", 0)
    if not (np.isnan(plus_di) or np.isnan(minus_di)):
        if pattern.direction == "LONG":
            di_spread = plus_di - minus_di
        else:
            di_spread = minus_di - plus_di
        # DI spread of 10+ = full marks
        di_score = min(20.0, max(0.0, di_spread / 10.0 * 20.0))
    else:
        di_score = 0.0
    score += di_score

    # ─── 3. EMA200 Alignment (0-20) ──────────────────────────────────
    if "ema_200" in df.columns:
        ema = df["ema_200"].loc[idx] if idx in df.index else df["ema_200"].iloc[-1]
        close = bar["close"]
        if not np.isnan(ema) and ema > 0:
            distance_pct = abs((close - ema) / ema) * 100.0
            if pattern.direction == "LONG" and close > ema:
                # Further above EMA = stronger uptrend (up to 2% distance)
                ema_score = min(20.0, distance_pct / 2.0 * 20.0)
            elif pattern.direction == "SHORT" and close < ema:
                ema_score = min(20.0, distance_pct / 2.0 * 20.0)
            else:
                ema_score = 0.0
        else:
            ema_score = 10.0
    else:
        ema_score = 10.0
    score += ema_score

    # ─── 4. Volume Confirmation (0-15) ───────────────────────────────
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    if vol_col in df.columns:
        bar_vol = bar[vol_col]
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

    # ─── 5. Kill Zone Timing (0-20) ──────────────────────────────────
    if pattern.detected_at is not None:
        kz = get_current_kill_zone(pattern.detected_at.hour)
        if kz == "ny_morning":
            kz_score = 20.0  # London-NY overlap = strongest trends
        elif kz == "london":
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
