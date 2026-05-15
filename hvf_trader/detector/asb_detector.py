"""Asian Session Breakout (ASB) detector.

Strategy:
  - Identify the Asian session high/low (00:00-07:00 UTC).
  - Apply range filter: 0.4 × ADR(14) <= range <= 1.0 × ADR(14).
  - Place BUY_STOP at range_high + buffer, SELL_STOP at range_low - buffer.
  - Buffer = max(2 pips, 0.10 × range).
  - SL = opposite range edge (NOT mid-range — preserves natural R:R).
  - TP = 1.0 × range from entry (1R target).
  - Time-stop: force-close any open ASB position at 20:00 UTC.

Backtested PF 1.40 over 8 months on GBPJPY + EURJPY (see
backtests/run_asb_validation.py). EURJPY drag is small enough to keep,
GBPUSD was decisively losing (PF 0.58) and is excluded.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from hvf_trader import config


@dataclass
class AsianRange:
    symbol: str
    date_utc: datetime           # UTC midnight of the session date
    high: float
    low: float
    range_pips: float
    adr_pips: float
    long_stop: float             # price level for BUY_STOP
    short_stop: float            # price level for SELL_STOP
    long_sl: float
    long_tp: float
    short_sl: float
    short_tp: float
    buffer_pips: float


def _pip(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def compute_adr14(df_h1: pd.DataFrame) -> Optional[float]:
    """Return the most-recent 14-day Wilder-smoothed average daily range (price units)."""
    if "time" not in df_h1.columns:
        return None
    d = df_h1.set_index("time").resample("1D").agg({
        "high": "max", "low": "min",
    }).dropna()
    if len(d) < 14:
        return None
    daily_range = d["high"] - d["low"]
    adr = daily_range.ewm(alpha=1 / 14, adjust=False).mean()
    return float(adr.iloc[-1])


def compute_asian_range(
    symbol: str,
    df_h1: pd.DataFrame,
    now_utc: datetime,
) -> Optional[AsianRange]:
    """Compute the Asian session range for the current UTC date.

    df_h1: at least the last 30 days of H1 bars. Used for both the Asian
    high/low (today's 00-07 UTC bars) and the ADR(14) filter (prior days).

    Returns None if:
      - Insufficient data
      - Asian range fails the ADR filter (too tight OR too wide)
    """
    if df_h1 is None or df_h1.empty or "time" not in df_h1.columns:
        return None

    # Asian window for today: today's bars where 0 <= hour < 7
    today = pd.Timestamp(now_utc.date(), tz="UTC")
    end = today + pd.Timedelta(hours=7)
    asian = df_h1[(df_h1["time"] >= today) & (df_h1["time"] < end)]
    if len(asian) < 4:  # need most of the session
        return None

    high = float(asian["high"].max())
    low = float(asian["low"].min())
    if high <= low:
        return None

    pip = _pip(symbol)
    range_pips = (high - low) / pip

    # ADR filter — exclude today's bars to avoid lookahead bias.
    prior = df_h1[df_h1["time"] < today]
    adr_price = compute_adr14(prior)
    if adr_price is None or adr_price <= 0:
        return None
    adr_pips = adr_price / pip

    cfg = config.ASIAN_SESSION_BREAKOUT
    if range_pips < cfg["min_range_pct_adr"] * adr_pips:
        return None
    if range_pips > cfg["max_range_pct_adr"] * adr_pips:
        return None

    buffer_pips = max(cfg["min_buffer_pips"], cfg["buffer_pct_range"] * range_pips)
    long_stop = high + buffer_pips * pip
    short_stop = low - buffer_pips * pip

    # SL = opposite range edge - that's the lossy side of the breakout.
    # For LONG entry (BUY_STOP at high+buffer): SL at low-buffer.
    # For SHORT entry (SELL_STOP at low-buffer): SL at high+buffer.
    long_sl = short_stop
    short_sl = long_stop

    # TP = 1× range from entry (1R target).
    long_tp = long_stop + range_pips * pip
    short_tp = short_stop - range_pips * pip

    return AsianRange(
        symbol=symbol,
        date_utc=today.to_pydatetime(),
        high=high, low=low,
        range_pips=range_pips, adr_pips=adr_pips,
        long_stop=long_stop, short_stop=short_stop,
        long_sl=long_sl, long_tp=long_tp,
        short_sl=short_sl, short_tp=short_tp,
        buffer_pips=buffer_pips,
    )
