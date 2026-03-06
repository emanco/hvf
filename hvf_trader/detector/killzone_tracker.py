"""
Kill Zone Tracker — tracks high/low of each Kill Zone session.

Maintains running KZ extremes during active sessions and locks
them when the session ends, providing key levels for KZ Hunt detection.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from hvf_trader import config

logger = logging.getLogger(__name__)


@dataclass
class KZLevels:
    """Locked Kill Zone high/low after session ends."""
    kz_name: str
    high: float
    low: float
    high_idx: int
    low_idx: int
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    bar_count: int = 0


class KillZoneTracker:
    """
    Tracks Kill Zone session extremes bar-by-bar.

    Usage:
        tracker = KillZoneTracker()
        for each bar:
            tracker.update(bar_time, bar_high, bar_low, bar_idx)
            levels = tracker.get_completed_kz()
    """

    def __init__(self):
        # Active KZ being tracked: kz_name -> {high, low, high_idx, low_idx, start_time, bars}
        self._active: dict[str, dict] = {}
        # Completed KZ levels (most recent per KZ name)
        self._completed: dict[str, KZLevels] = {}
        self._last_hour: int = -1

    def update(
        self,
        bar_time: pd.Timestamp,
        bar_high: float,
        bar_low: float,
        bar_idx: int,
    ):
        """Process a new bar, updating active KZ tracking."""
        hour = bar_time.hour

        for kz_name, (kz_start, kz_end) in config.KILL_ZONES_UTC.items():
            in_kz = kz_start <= hour <= kz_end

            if in_kz:
                if kz_name not in self._active:
                    # KZ just started
                    self._active[kz_name] = {
                        "high": bar_high,
                        "low": bar_low,
                        "high_idx": bar_idx,
                        "low_idx": bar_idx,
                        "start_time": bar_time,
                        "bars": 1,
                    }
                else:
                    # Update running extremes
                    kz = self._active[kz_name]
                    kz["bars"] += 1
                    if bar_high > kz["high"]:
                        kz["high"] = bar_high
                        kz["high_idx"] = bar_idx
                    if bar_low < kz["low"]:
                        kz["low"] = bar_low
                        kz["low_idx"] = bar_idx
            else:
                # KZ ended — lock levels
                if kz_name in self._active:
                    kz = self._active.pop(kz_name)
                    self._completed[kz_name] = KZLevels(
                        kz_name=kz_name,
                        high=kz["high"],
                        low=kz["low"],
                        high_idx=kz["high_idx"],
                        low_idx=kz["low_idx"],
                        start_time=kz["start_time"],
                        end_time=bar_time,
                        bar_count=kz["bars"],
                    )

        self._last_hour = hour

    def get_completed_kz(self, kz_name: str = None) -> Optional[KZLevels]:
        """Get the most recently completed KZ levels."""
        if kz_name:
            return self._completed.get(kz_name)
        # Return the most recently completed
        if not self._completed:
            return None
        return max(self._completed.values(), key=lambda kz: kz.end_time)

    def get_all_completed(self) -> dict[str, KZLevels]:
        """Get all completed KZ levels."""
        return dict(self._completed)

    def reset(self):
        """Reset tracker state (for backtesting between runs)."""
        self._active.clear()
        self._completed.clear()
        self._last_hour = -1


def build_kz_levels_from_history(
    df: pd.DataFrame,
    lookback_bars: int = 200,
) -> dict[str, KZLevels]:
    """
    Build KZ levels from historical data for backtest initialization.

    Walks through the last `lookback_bars` bars to build KZ history.
    """
    tracker = KillZoneTracker()
    start = max(0, len(df) - lookback_bars)

    for i in range(start, len(df)):
        bar = df.iloc[i]
        bar_time = bar["time"] if "time" in df.columns else pd.Timestamp.now()
        tracker.update(bar_time, bar["high"], bar["low"], i)

    return tracker.get_all_completed()
