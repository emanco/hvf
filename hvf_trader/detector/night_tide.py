"""
Night Tide — Quiet-Hours BB+RSI mean reversion on cross pairs.

Trade window: 22:00-01:00 UTC during NY DST (March-November), 23:00-01:00 UTC
during NY EST (November-March). The hour right after NY close has a daily-
rollover spread spike (10-20× normal) on cross pairs — we skip it.

Pairs: AUDNZD, NZDCAD, AUDCAD, EURCHF (M15).
Entry: M15 close pierces a Bollinger Band AND RSI is at the matching extreme.
       LONG  if close < BB_lower AND RSI < 30 → buy at close, TP = BB_mid, SL = -12p
       SHORT if close > BB_upper AND RSI > 70 → sell at close, TP = BB_mid, SL = +12p
Exit:  Broker-side TP/SL, or force-close after 4 hours (16 M15 bars).

Backtest 2022-04 → 2026-04 (4 yrs): n=1253 WR=76% PF=3.17 +7782p DD=79p.
Window-handling comparison validated `dynamic` (skip rollover hour by season)
as best of 4 alternatives (baseline / dynamic / skip30 / spread_filter).

IC-native reality check (2026-07-02): the backtest above ran on Dukascopy
data, whose feed produces ~4x more signals than IC Markets' own M15 feed
(~50/mo vs ~13.5/mo across the 4 pairs, same detector, same months — stable
since 2022, not a regime effect). Realistic live expectation on IC: PF
~1.3-1.5, ~60% WR, ~6-11 fills/mo portfolio-wide, max DD ~80p. Note also
that live evaluates each bar once at its OPEN (forming stub), not at close —
that variant is the profitable one on IC's feed; see
_scan_night_tide_instrument and scripts/nt_ic_feed_diag.py. EURCHF produces
near-zero setups on IC's feed since 2025-10 — keep it, but expect silence.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from hvf_trader import config

logger = logging.getLogger(__name__)


BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 70


@dataclass
class NightTideSignal:
    symbol: str
    direction: str          # LONG or SHORT
    entry_price: float
    stop_loss: float
    take_profit: float      # BB middle band at entry bar
    bb_upper: float
    bb_lower: float
    bb_mid: float
    rsi: float
    pattern_type: str = "NIGHT_TIDE"


def _is_us_dst(dt: datetime) -> bool:
    """US DST runs from 2nd Sunday of March 02:00 to 1st Sunday of November 02:00."""
    y = dt.year
    march = pd.Timestamp(f"{y}-03-01")
    march_2nd_sun = march + pd.Timedelta(days=(6 - march.weekday()) % 7) + pd.Timedelta(weeks=1)
    nov = pd.Timestamp(f"{y}-11-01")
    nov_1st_sun = nov + pd.Timedelta(days=(6 - nov.weekday()) % 7)
    march_2nd_sun = march_2nd_sun.replace(hour=2).tz_localize("UTC")
    nov_1st_sun = nov_1st_sun.replace(hour=2).tz_localize("UTC")
    dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return march_2nd_sun <= pd.Timestamp(dt_utc) < nov_1st_sun


def in_trading_window(now: datetime) -> bool:
    """Trade window: 22:00-01:00 UTC in summer, 23:00-01:00 UTC in winter.

    The NY-rollover spread spike sits at 21:00 UTC during DST and 22:00 UTC
    during EST. We always skip the rollover hour.

    If config.NIGHT_TIDE.test_mode is set, the window check is bypassed so we
    can validate the pipework with a live trade outside normal hours.
    """
    if config.NIGHT_TIDE.get("test_mode"):
        return True
    h = now.hour
    if _is_us_dst(now):
        return h >= 22 or h < 1   # Summer: 22-01
    return h >= 23 or h < 1       # Winter: 23-01


def in_force_close_window(now: datetime) -> bool:
    """Outside the trading window — close any held position.

    Test-mode bypasses force-close so a manually-induced trade isn't
    immediately killed by the window check on next scan.
    """
    if config.NIGHT_TIDE.get("test_mode"):
        return False
    return not in_trading_window(now)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add BB(20,2) + RSI(14) using SMA-based RSI to match backtest."""
    closes = df["close"]
    df = df.copy()
    df["bb_mid"] = closes.rolling(BB_PERIOD).mean()
    bb_std = closes.rolling(BB_PERIOD).std()
    df["bb_upper"] = df["bb_mid"] + BB_STD * bb_std
    df["bb_lower"] = df["bb_mid"] - BB_STD * bb_std
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, 1e-9)
    df["nt_rsi"] = 100 - 100 / (1 + rs)
    return df


def detect_signal(df: pd.DataFrame, symbol: str, cfg: dict) -> Optional[NightTideSignal]:
    """Look at the last completed M15 bar; emit signal if BB+RSI conditions align.

    Returns None if not enough history, no setup, or TP-distance too small to
    overcome spread.
    """
    if len(df) < BB_PERIOD + 2:
        return None

    bar = df.iloc[-1]
    if pd.isna(bar.get("bb_mid")) or pd.isna(bar.get("nt_rsi")):
        return None

    pip = config.PIP_VALUES.get(symbol, 0.0001)
    sl_pips = cfg["stop_pips"]
    spread_buffer = cfg.get("spread_buffer_pips", 2.0)
    bb_mid = float(bar["bb_mid"])
    bb_upper = float(bar["bb_upper"])
    bb_lower = float(bar["bb_lower"])
    rsi = float(bar["nt_rsi"])
    close = float(bar["close"])

    direction = None
    # Test mode: relax thresholds so we can fire a live trade for pipework
    # validation. Any close above mid → SHORT; below → LONG.
    if cfg.get("test_mode"):
        if close < bb_mid:
            direction = "LONG"
            entry = close
            tp = bb_mid
            sl = entry - sl_pips * pip
            if (tp - entry) / pip < spread_buffer + 1:
                return None
        else:
            direction = "SHORT"
            entry = close
            tp = bb_mid
            sl = entry + sl_pips * pip
            if (entry - tp) / pip < spread_buffer + 1:
                return None
    elif close < bb_lower and rsi < RSI_LOWER:
        direction = "LONG"
        entry = close
        tp = bb_mid
        sl = entry - sl_pips * pip
        # Skip if TP distance < spread + buffer (would lock in loss)
        if (tp - entry) / pip < spread_buffer + 1:
            return None
    elif close > bb_upper and rsi > RSI_UPPER:
        direction = "SHORT"
        entry = close
        tp = bb_mid
        sl = entry + sl_pips * pip
        if (entry - tp) / pip < spread_buffer + 1:
            return None
    else:
        return None

    return NightTideSignal(
        symbol=symbol, direction=direction,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        bb_upper=bb_upper, bb_lower=bb_lower, bb_mid=bb_mid,
        rsi=rsi,
    )


def signal_metadata(sig: NightTideSignal) -> str:
    return json.dumps({
        "bb_upper": sig.bb_upper,
        "bb_lower": sig.bb_lower,
        "bb_mid": sig.bb_mid,
        "rsi": sig.rsi,
    })
