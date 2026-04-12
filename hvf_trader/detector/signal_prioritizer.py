"""
Signal Prioritizer — resolves conflicts when multiple patterns fire simultaneously.

Priority order: HVF > Viper > KZ_HUNT > LONDON_SWEEP
Within the same type, highest score wins.
"""
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Priority: lower number = higher priority
PATTERN_PRIORITY = {
    "HVF": 1,
    "VIPER": 2,
    "KZ_HUNT": 3,
    "LONDON_SWEEP": 4,
    "TREND_RIDE": 5,
}


@dataclass
class PrioritizedSignal:
    pattern: Any  # HVFPattern, ViperPattern, KZHuntPattern, or LondonSweepPattern
    pattern_type: str
    symbol: str
    direction: str
    score: float
    priority: int


def prioritize_signals(
    signals: list[dict],
    max_signals_per_symbol: int = 1,
) -> list[PrioritizedSignal]:
    """
    Select the best signal(s) from a pool of candidates.

    Args:
        signals: list of dicts with keys:
            - pattern: the pattern object
            - pattern_type: "HVF", "VIPER", "KZ_HUNT", "LONDON_SWEEP"
            - symbol: instrument symbol
            - direction: "LONG" or "SHORT"
            - score: float 0-100
        max_signals_per_symbol: max concurrent signals per instrument

    Returns:
        Ordered list of PrioritizedSignal, best first
    """
    if not signals:
        return []

    prioritized = []
    for sig in signals:
        ptype = sig["pattern_type"]
        prioritized.append(PrioritizedSignal(
            pattern=sig["pattern"],
            pattern_type=ptype,
            symbol=sig["symbol"],
            direction=sig["direction"],
            score=sig["score"],
            priority=PATTERN_PRIORITY.get(ptype, 99),
        ))

    # Sort by: priority (lower=better), then score (higher=better)
    prioritized.sort(key=lambda s: (s.priority, -s.score))

    # Limit per symbol
    selected: list[PrioritizedSignal] = []
    symbol_counts: dict[str, int] = {}

    for sig in prioritized:
        count = symbol_counts.get(sig.symbol, 0)
        if count < max_signals_per_symbol:
            selected.append(sig)
            symbol_counts[sig.symbol] = count + 1

    if selected:
        logger.debug(
            "Prioritized %d signal(s) from %d candidates: %s",
            len(selected),
            len(signals),
            [(s.pattern_type, s.symbol, s.direction, s.score) for s in selected],
        )

    return selected
