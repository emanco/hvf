"""Quantum London detector — faithful FF mean-reversion (thread #743125).

Strategy: capture daily open at 22:00 UTC, then for the next ~22 hours
(until 21:00 UTC the following day), watch for any tick crossing N pips
from the open. Fade the move (LONG below, SHORT above), small reversion TP,
wide SL.

Note on naming: this module replaced the prior "Quantum London" grid-EA
attempt with the canonical FF Simple Mean Reversion logic from thread
#743125 (Alphaomega). The QUANTUM_LONDON name is kept for continuity
with the project's naming and DB pattern_type history; the mechanics
are pure mean-reversion, not the older grid/martingale variant.
"""
from dataclasses import dataclass


@dataclass
class QLSignal:
    symbol: str
    direction: str          # LONG or SHORT
    entry_price: float      # the trigger price (limit-order target)
    take_profit: float
    stop_loss: float
    session_open: float
    trigger_pips: float


class QLTracker:
    """State: IDLE -> TRADING -> DONE.

    Lifecycle:
    - IDLE: no session active. Wait for capture hour.
    - TRADING: daily open captured, watching for trigger.
    - DONE: trade fired (mark_traded) OR force-exit time reached. Wait for reset.

    Reset happens during the brief idle window between force-exit (21:00 UTC)
    and the next capture (22:00 UTC).
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = "IDLE"
        self.session_open = 0.0
        self.session_date = None
        self.traded_today = False

    def start_session(self, session_open: float, session_date: str):
        """Called at 22:00 UTC capture each weekday."""
        self.reset()
        self.state = "TRADING"
        self.session_open = session_open
        self.session_date = session_date

    def check_trigger(
        self,
        bid: float,
        ask: float,
        pip_value: float,
        trigger_pips: float,
        target_pips: float,
        stop_pips: float,
        symbol: str,
    ):
        """Return QLSignal if a trigger is crossed, else None.

        Entry price is the TRIGGER LEVEL (not the live ask/bid). The bot
        places a limit order at that exact price. This is the canonical
        FF entry — entering at trigger means TP/SL are computed from the
        intended price, matching the backtest geometry exactly.
        """
        if self.state != "TRADING" or self.traded_today:
            return None

        long_trigger = self.session_open - trigger_pips * pip_value
        short_trigger = self.session_open + trigger_pips * pip_value

        if bid <= long_trigger:
            entry = long_trigger
            return QLSignal(
                symbol=symbol, direction="LONG",
                entry_price=entry,
                take_profit=entry + target_pips * pip_value,
                stop_loss=entry - stop_pips * pip_value,
                session_open=self.session_open,
                trigger_pips=trigger_pips,
            )
        if ask >= short_trigger:
            entry = short_trigger
            return QLSignal(
                symbol=symbol, direction="SHORT",
                entry_price=entry,
                take_profit=entry - target_pips * pip_value,
                stop_loss=entry + stop_pips * pip_value,
                session_open=self.session_open,
                trigger_pips=trigger_pips,
            )
        return None

    def mark_traded(self):
        """One trade per session — block re-entries."""
        self.traded_today = True
        self.state = "DONE"
