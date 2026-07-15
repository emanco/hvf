"""
London Breakout — Asian range breakout detector for GBPUSD.

What it ACTUALLY measures (validated 2026-07-02, keep as-is): bars arrive
broker-time-labeled, so `update_asian_bar`'s `hour < 7` gate combined with
the main loop's real-UTC 00-07 feed window accumulates the range over
broker hours 03-06 = roughly UTC 00:00-04:00 (4 bars in summer, 5 in
winter) — NOT the "00:00-07:00 UTC" originally intended. Breakouts are
then detected during real UTC 08:00-13:00.

This accidental geometry was re-validated against three alternatives on
IC H1 data with commission (scripts/lbo_geometry_validation.py, 8.3y):
it is the BEST variant — N=260, PF 1.63, +929p, dd 108p (stable 2023+:
PF 1.62) — while the documented 7-bar UTC range variant is breakeven
(PF 0.99 in 2023+). Do not "fix" the clock handling to match the old
docstring without re-running that comparison.

Original (superseded) claim: PF 1.77, 66% WR, +575p / 8y, 142 trades —
that described broker-hour geometry incl. the Sunday-open gap.
Best on Monday + Tuesday. Range band widened 12-20 -> 10-22 pips
(2026-07-15 equal-risk deep analysis: edge is a broad plateau ~8-25p with
no cliff at 20p; 10-22 dominates 12-20 in both full-history and 2023+
windows — see config.py LONDON_BREAKOUT note).
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from hvf_trader import config

logger = logging.getLogger(__name__)

PIP = config.PIP_VALUES.get("GBPUSD", 0.0001)


@dataclass
class LondonBreakoutSignal:
    """Signal emitted when price breaks the Asian range."""
    symbol: str
    direction: str          # LONG or SHORT
    entry_price: float
    stop_loss: float
    take_profit: float
    asian_high: float
    asian_low: float
    asian_range_pips: float
    score: float = 100.0
    pattern_type: str = "LONDON_BO"


class LondonBreakoutTracker:
    """Tracks the Asian range and detects London breakouts.

    Lifecycle per day:
    1. IDLE -> FORMING at 00:00 UTC (track Asian high/low)
    2. FORMING -> READY at 07:00 UTC (range locked, check filters)
    3. READY -> TRADING at 08:00 UTC (monitor for breakout)
    4. TRADING -> DONE when breakout detected or 13:00 UTC reached
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = "IDLE"
        self.session_date = None
        self.asian_high = 0.0
        self.asian_low = 999.0
        self.asian_range_pips = 0.0
        self.traded_today = False
        self.skipped_reason = None

    def update_asian_bar(self, bar_high: float, bar_low: float,
                         bar_time: pd.Timestamp):
        """Process an H1 bar during Asian session (00:00-07:00 UTC).

        Call this for each new H1 bar. The tracker auto-transitions
        between states based on bar_time.hour.
        """
        hour = bar_time.hour
        date = str(bar_time.date())

        # New day detection
        if date != self.session_date and hour < 7:
            self.reset()
            self.state = "FORMING"
            self.session_date = date
            self.asian_high = bar_high
            self.asian_low = bar_low
            return

        if self.state == "FORMING" and hour < 7:
            self.asian_high = max(self.asian_high, bar_high)
            self.asian_low = min(self.asian_low, bar_low)

    def finalize_range(self, cfg: dict) -> bool:
        """Lock the Asian range at 07:00 UTC and apply filters.

        Args:
            cfg: LONDON_BREAKOUT config dict with min_range, max_range, days.

        Returns:
            True if the session qualifies for trading, False if skipped.
        """
        if self.state != "FORMING":
            return False

        self.asian_range_pips = (self.asian_high - self.asian_low) / PIP

        # Range filter
        if self.asian_range_pips < cfg["min_range_pips"]:
            self.state = "DONE"
            self.skipped_reason = "range {:.0f}p < min {:.0f}p".format(
                self.asian_range_pips, cfg["min_range_pips"])
            return False

        if self.asian_range_pips > cfg["max_range_pips"]:
            self.state = "DONE"
            self.skipped_reason = "range {:.0f}p > max {:.0f}p".format(
                self.asian_range_pips, cfg["max_range_pips"])
            return False

        self.state = "READY"
        logger.info(
            "[LONDON_BO] Range locked: high={:.5f} low={:.5f} range={:.0f}p".format(
                self.asian_high, self.asian_low, self.asian_range_pips))
        return True

    def check_breakout(self, bar: pd.Series, cfg: dict) -> Optional[LondonBreakoutSignal]:
        """Check if the current H1 bar breaks the Asian range.

        Args:
            bar: H1 bar with 'high', 'low', 'close' fields.
            cfg: LONDON_BREAKOUT config dict.

        Returns:
            LondonBreakoutSignal if breakout detected, None otherwise.
        """
        if self.state not in ("READY", "TRADING") or self.traded_today:
            return None

        self.state = "TRADING"

        symbol = cfg["instrument"]
        spread = cfg["spread_pips"] * PIP
        tp_dist = self.asian_range_pips * cfg["tp_multiplier"] * PIP

        # LONG breakout: bar high exceeds Asian high
        if bar["high"] > self.asian_high + spread:
            entry = self.asian_high + spread
            sl = self.asian_low - spread
            tp = entry + tp_dist

            return LondonBreakoutSignal(
                symbol=symbol, direction="LONG",
                entry_price=entry, stop_loss=sl, take_profit=tp,
                asian_high=self.asian_high, asian_low=self.asian_low,
                asian_range_pips=self.asian_range_pips,
            )

        # SHORT breakout: bar low breaks Asian low
        if bar["low"] < self.asian_low - spread:
            entry = self.asian_low - spread
            sl = self.asian_high + spread
            tp = entry - tp_dist

            return LondonBreakoutSignal(
                symbol=symbol, direction="SHORT",
                entry_price=entry, stop_loss=sl, take_profit=tp,
                asian_high=self.asian_high, asian_low=self.asian_low,
                asian_range_pips=self.asian_range_pips,
            )

        return None

    def mark_traded(self):
        self.traded_today = True
        self.state = "DONE"

    def get_pattern_metadata(self) -> str:
        """Return JSON metadata for DB storage."""
        return json.dumps({
            "asian_high": self.asian_high,
            "asian_low": self.asian_low,
            "asian_range_pips": self.asian_range_pips,
            "session_date": self.session_date,
        })
