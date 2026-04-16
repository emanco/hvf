"""
Asian Gravity — Session-open gravity detector for EURGBP.

Tracks the Asian session open price and formation range.
During quiet nights (range < max_range), detects when price drifts
below the session open by trigger_pips and signals a LONG entry.

The edge: on quiet EURGBP nights, both EUR and GBP are asleep.
A 3-pip drift from the open always reverts by at least 2 pips.
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class AsianGravitySignal:
    """Entry signal emitted when gravity trigger is hit."""
    symbol: str
    direction: str          # Always "LONG" for now
    entry_price: float
    stop_loss: float
    take_profit: float
    session_open: float
    session_range_pips: float
    session_date: str
    trigger_pips: float
    spread_pips: float


class AsianGravityTracker:
    """Tracks Asian session state: IDLE → FORMING → TRADING → DONE.

    Formation phase (00:00-02:00 UTC): measures range from M15 bars.
    Trading phase (02:00-06:00 UTC): monitors live ticks for trigger.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset to idle state for a new session."""
        self.state = "IDLE"
        self.session_date = None
        self.session_open = 0.0
        self.formation_high = 0.0
        self.formation_low = 0.0
        self.range_pips = 0.0
        self.traded_today = False
        self.skipped_reason = None

    def start_session(self, bar_open: float, bar_high: float,
                      bar_low: float, date: str):
        """Start a new formation phase at 00:00 UTC."""
        self.reset()
        self.state = "FORMING"
        self.session_date = date
        self.session_open = bar_open
        self.formation_high = bar_high
        self.formation_low = bar_low

    def update_formation(self, bar_high: float, bar_low: float):
        """Update formation range with a new M15 bar (00:00-02:00)."""
        if self.state != "FORMING":
            return
        self.formation_high = max(self.formation_high, bar_high)
        self.formation_low = min(self.formation_low, bar_low)

    def finalize_formation(self, pip_value: float, max_range_pips: float):
        """Transition from FORMING to TRADING at 02:00 UTC.

        Computes formation range and applies the range filter.

        Args:
            pip_value: Price per pip for the instrument.
            max_range_pips: Skip session if range exceeds this.
        """
        if self.state != "FORMING":
            return

        self.range_pips = (self.formation_high - self.formation_low) / pip_value

        if self.range_pips > max_range_pips:
            self.state = "DONE"
            self.skipped_reason = f"range {self.range_pips:.1f}p > {max_range_pips}p"
            logger.info(
                f"[ASIAN_GRAVITY] Session {self.session_date} skipped: "
                f"{self.skipped_reason}"
            )
        elif self.range_pips < 1:
            self.state = "DONE"
            self.skipped_reason = f"range {self.range_pips:.1f}p too small"
        else:
            self.state = "TRADING"
            logger.info(
                f"[ASIAN_GRAVITY] Session {self.session_date} TRADING: "
                f"open={self.session_open:.5f}, range={self.range_pips:.1f}p"
            )

    def check_trigger(self, bid: float, ask: float, pip_value: float,
                      trigger_pips: float, target_pips: float,
                      stop_pips: float, max_spread_pips: float,
                      symbol: str,
                      direction: str = "LONG") -> AsianGravitySignal | None:
        """Check if the live tick triggers an entry.

        Args:
            bid: Current bid price.
            ask: Current ask price.
            pip_value: Price per pip.
            trigger_pips: Distance from session open to trigger entry.
            target_pips: TP distance from entry.
            stop_pips: SL distance from entry.
            max_spread_pips: Maximum allowed spread.
            symbol: Instrument symbol.
            direction: "LONG" (buy dips) or "SHORT" (sell rallies).

        Returns:
            AsianGravitySignal if triggered, None otherwise.
        """
        if self.state != "TRADING" or self.traded_today:
            return None

        # Check spread first
        spread_pips = (ask - bid) / pip_value
        if spread_pips > max_spread_pips:
            return None

        if direction == "BOTH":
            # Mean-reversion: check both directions, enter whichever triggers
            long_trigger = self.session_open - trigger_pips * pip_value
            short_trigger = self.session_open + trigger_pips * pip_value
            if bid <= long_trigger:
                direction = "LONG"
            elif ask >= short_trigger:
                direction = "SHORT"
            else:
                return None

        if direction == "LONG":
            trigger_price = self.session_open - trigger_pips * pip_value
            if bid > trigger_price:
                return None
            entry_price = ask  # buying at ask
            take_profit = entry_price + target_pips * pip_value
            stop_loss = entry_price - stop_pips * pip_value
        else:  # SHORT
            trigger_price = self.session_open + trigger_pips * pip_value
            if ask < trigger_price:
                return None
            entry_price = bid  # selling at bid
            take_profit = entry_price - target_pips * pip_value
            stop_loss = entry_price + stop_pips * pip_value

        return AsianGravitySignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            session_open=self.session_open,
            session_range_pips=self.range_pips,
            session_date=self.session_date,
            trigger_pips=trigger_pips,
            spread_pips=spread_pips,
        )

    def mark_traded(self):
        """Mark this session as traded (no re-entries)."""
        self.traded_today = True
        self.state = "DONE"
