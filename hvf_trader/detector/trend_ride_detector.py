"""
Trend Ride Detector — ADX-filtered Donchian channel breakout.

Structurally anti-correlated with KZ_HUNT: profits when price trends
through session extremes (exactly when KZ_HUNT gets invalidated).

Rules:
1. ADX(14) > 20 (trending market)
2. Close above 55-bar Donchian high (LONG) or below Donchian low (SHORT)
3. DI alignment: +DI > -DI for LONG, -DI > +DI for SHORT
4. EMA200 alignment: price > EMA for LONG, price < EMA for SHORT
5. Session filter: London or NY kill zones only
"""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from hvf_trader import config

logger = logging.getLogger(__name__)


@dataclass
class TrendRidePattern:
    symbol: str
    timeframe: str
    direction: str  # 'LONG' or 'SHORT'

    # Donchian context
    donchian_high: float
    donchian_low: float
    breakout_bar_idx: int
    breakout_price: float  # Close of breakout candle

    # Trade levels
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    rrr: float = 0.0

    # Metadata
    detected_at: Optional[pd.Timestamp] = None
    score: float = 0.0
    status: str = "DETECTED"
    pattern_type: str = "TREND_RIDE"

    def compute_levels(self, current_atr: float):
        """Calculate entry, SL, targets from breakout price + ATR."""
        sl_mult = config.TREND_RIDE_ATR_SL_MULT
        t1_mult = config.TREND_RIDE_T1_ATR_MULT
        t2_mult = config.TREND_RIDE_T2_ATR_MULT

        if self.direction == "LONG":
            self.entry_price = self.breakout_price
            self.stop_loss = self.entry_price - sl_mult * current_atr
            self.target_1 = self.entry_price + t1_mult * current_atr
            self.target_2 = self.entry_price + t2_mult * current_atr
        else:
            self.entry_price = self.breakout_price
            self.stop_loss = self.entry_price + sl_mult * current_atr
            self.target_1 = self.entry_price - t1_mult * current_atr
            self.target_2 = self.entry_price - t2_mult * current_atr

        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_2 - self.entry_price)
        self.rrr = reward / risk if risk > 0 else 0.0


def detect_trend_ride_patterns(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> list[TrendRidePattern]:
    """
    Scan for ADX-filtered Donchian channel breakouts.

    Only looks at the LAST completed bar in the DataFrame.
    Returns 0 or 1 patterns (one direction per scan).
    """
    if len(df) < config.DONCHIAN_PERIOD + 10:
        return []
    if "atr" not in df.columns or "donchian_high" not in df.columns:
        return []

    patterns: list[TrendRidePattern] = []
    last_idx = df.index[-1]
    bar = df.loc[last_idx] if last_idx in df.index else df.iloc[-1]

    # ─── ADX filter ──────────────────────────────────────────────────
    adx = bar.get("adx", 0)
    if np.isnan(adx) or adx < config.TREND_RIDE_ADX_MIN:
        return []

    # ─── Session filter (London or NY kill zones only) ───────────────
    if "time" in df.columns:
        hour = bar["time"].hour
        in_kz = any(
            start <= hour <= end
            for start, end in config.KILL_ZONES_UTC.values()
        )
        if not in_kz:
            return []

    # ─── Required indicators ─────────────────────────────────────────
    close = bar["close"]
    donchian_high = bar.get("donchian_high", None)
    donchian_low = bar.get("donchian_low", None)
    atr = bar.get("atr", 0)
    ema = bar.get("ema_200", None)
    plus_di = bar.get("plus_di", 0)
    minus_di = bar.get("minus_di", 0)

    if any(v is None or (isinstance(v, float) and np.isnan(v))
           for v in [donchian_high, donchian_low, atr, ema]):
        return []
    if atr <= 0:
        return []

    # ─── LONG: close > Donchian high, +DI > -DI, price > EMA200 ────
    if close > donchian_high and plus_di > minus_di and close > ema:
        pattern = TrendRidePattern(
            symbol=symbol,
            timeframe=timeframe,
            direction="LONG",
            donchian_high=donchian_high,
            donchian_low=donchian_low,
            breakout_bar_idx=last_idx,
            breakout_price=close,
            detected_at=bar["time"] if "time" in df.columns else None,
        )
        pattern.compute_levels(float(atr))
        min_rrr = config.MIN_RRR_BY_PATTERN.get("TREND_RIDE", config.HVF_MIN_RRR)
        if pattern.rrr >= min_rrr:
            patterns.append(pattern)

    # ─── SHORT: close < Donchian low, -DI > +DI, price < EMA200 ────
    if close < donchian_low and minus_di > plus_di and close < ema:
        pattern = TrendRidePattern(
            symbol=symbol,
            timeframe=timeframe,
            direction="SHORT",
            donchian_high=donchian_high,
            donchian_low=donchian_low,
            breakout_bar_idx=last_idx,
            breakout_price=close,
            detected_at=bar["time"] if "time" in df.columns else None,
        )
        pattern.compute_levels(float(atr))
        min_rrr = config.MIN_RRR_BY_PATTERN.get("TREND_RIDE", config.HVF_MIN_RRR)
        if pattern.rrr >= min_rrr:
            patterns.append(pattern)

    return patterns


def check_trend_ride_entry_confirmation(
    pattern: TrendRidePattern,
    latest_bar: pd.Series,
) -> bool:
    """Check if latest bar confirms Trend Ride entry (continuation past breakout)."""
    close_price = latest_bar.get("close", None)
    if close_price is None:
        return False

    if pattern.direction == "LONG":
        return float(close_price) > pattern.entry_price
    else:
        return float(close_price) < pattern.entry_price
