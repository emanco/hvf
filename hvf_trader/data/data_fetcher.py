"""
Fetch OHLCV from MT5 and compute technical indicators (ATR, EMA, ADX).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from hvf_trader import config


# ─── MT5 Timeframe Mapping ──────────────────────────────────────────────────
TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1 if MT5_AVAILABLE else 1,
    "M5": mt5.TIMEFRAME_M5 if MT5_AVAILABLE else 5,
    "M15": mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15,
    "M30": mt5.TIMEFRAME_M30 if MT5_AVAILABLE else 30,
    "H1": mt5.TIMEFRAME_H1 if MT5_AVAILABLE else 16385,
    "H4": mt5.TIMEFRAME_H4 if MT5_AVAILABLE else 16388,
    "D1": mt5.TIMEFRAME_D1 if MT5_AVAILABLE else 16408,
    "W1": mt5.TIMEFRAME_W1 if MT5_AVAILABLE else 32769,
}


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "H1",
    bars: int = 500,
    from_date: Optional[datetime] = None,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data from MT5.

    Args:
        symbol: e.g. "EURUSD"
        timeframe: e.g. "H1", "H4"
        bars: number of bars to fetch
        from_date: specific start date (if None, fetch latest N bars)

    Returns:
        DataFrame with columns: time, open, high, low, close, tick_volume, spread, real_volume
        Index is integer (not datetime). 'time' column is pd.Timestamp.
        Returns None on failure.
    """
    if not MT5_AVAILABLE:
        logger.error("MT5 not available")
        return None

    tf_mt5 = TIMEFRAME_MAP.get(timeframe)
    if tf_mt5 is None:
        logger.error("Unknown timeframe: %s", timeframe)
        return None

    if from_date is not None:
        if from_date.tzinfo is None:
            from_date = from_date.replace(tzinfo=timezone.utc)
        rates = mt5.copy_rates_from(symbol, tf_mt5, from_date, bars)
    else:
        rates = mt5.copy_rates_from_pos(symbol, tf_mt5, 0, bars)

    if rates is None or len(rates) == 0:
        error = mt5.last_error()
        logger.error(
            "Failed to fetch OHLCV for %s %s: %s", symbol, timeframe, error
        )
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

    logger.debug(
        "Fetched %d bars for %s %s (latest: %s)",
        len(df),
        symbol,
        timeframe,
        df["time"].iloc[-1],
    )
    return df


def add_indicators(
    df: pd.DataFrame,
    atr_period: Optional[int] = None,
    ema_period: Optional[int] = None,
    adx_period: Optional[int] = None,
) -> pd.DataFrame:
    """
    Add technical indicators to OHLCV DataFrame.

    Adds columns: 'atr', 'ema_200', 'adx'.
    Uses pure numpy/pandas calculations -- no pandas-ta dependency.

    Returns the DataFrame with new columns added (modifies in place and returns).
    """
    if atr_period is None:
        atr_period = config.ATR_PERIOD
    if ema_period is None:
        ema_period = config.EMA_PERIOD
    if adx_period is None:
        adx_period = config.ADX_PERIOD

    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    # ─── ATR ─────────────────────────────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's smoothing is equivalent to ewm with alpha = 1/period
    df["atr"] = true_range.ewm(alpha=1.0 / atr_period, adjust=False).mean()

    # ─── EMA ─────────────────────────────────────────────────────────────────
    df["ema_200"] = close.ewm(span=ema_period, adjust=False).mean()

    # ─── ADX ─────────────────────────────────────────────────────────────────
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    # Directional Movement
    up_move = high - prev_high
    down_move = prev_low - low

    # +DM: positive when up_move > down_move AND up_move > 0
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    # -DM: positive when down_move > up_move AND down_move > 0
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    # Smooth with Wilder's method (alpha = 1/period)
    alpha = 1.0 / adx_period
    smoothed_tr = true_range.ewm(alpha=alpha, adjust=False).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=alpha, adjust=False).mean()

    # Directional Indicators
    plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
    minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

    # DX and ADX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()

    # Avoid division by zero
    dx = pd.Series(
        np.where(di_sum > 0, 100.0 * di_diff / di_sum, 0.0),
        index=df.index,
    )

    df["adx"] = dx.ewm(alpha=alpha, adjust=False).mean()

    # ─── RSI ───────────────────────────────────────────────────────────────────
    rsi_period = config.RSI_PERIOD if hasattr(config, "RSI_PERIOD") else 14
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # ─── MACD ──────────────────────────────────────────────────────────────────
    macd_fast = config.MACD_FAST if hasattr(config, "MACD_FAST") else 12
    macd_slow = config.MACD_SLOW if hasattr(config, "MACD_SLOW") else 26
    macd_signal_period = config.MACD_SIGNAL if hasattr(config, "MACD_SIGNAL") else 9
    ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
    ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=macd_signal_period, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    return df


def fetch_and_prepare(
    symbol: str,
    timeframe: str = "H1",
    bars: int = 500,
) -> Optional[pd.DataFrame]:
    """Convenience: fetch OHLCV + add all indicators."""
    df = fetch_ohlcv(symbol, timeframe, bars)
    if df is None or df.empty:
        return None
    return add_indicators(df)


def get_volume_average(df: pd.DataFrame, period: int = 20) -> float:
    """Get the rolling average of tick_volume for the last N bars."""
    if len(df) < period:
        return float(df["tick_volume"].mean())
    return float(df["tick_volume"].iloc[-period:].mean())
