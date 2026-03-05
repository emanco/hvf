"""
KLOS (Key Levels of Significance) — multi-timeframe key level identification.

Identifies swing highs/lows from 4H and Daily zigzag to provide:
  1. Confluence scoring bonus (0-10) when entry aligns with key levels
  2. Target obstruction warnings when S/R sits between entry and target
  3. Rejection penalty (-10) when key level opposes the entry
"""
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from hvf_trader.detector.zigzag import compute_zigzag, Pivot
from hvf_trader import config

logger = logging.getLogger(__name__)


@dataclass
class KeyLevel:
    price: float
    timeframe: str  # "H4" or "D1"
    level_type: str  # "RESISTANCE" or "SUPPORT"
    strength: int  # Number of touches / confirmations


def identify_key_levels(
    df: pd.DataFrame,
    timeframe: str,
    n_pivots: int = 50,
    atr_multiplier: float = None,
) -> list[KeyLevel]:
    """
    Identify key S/R levels from zigzag pivots on a given timeframe.

    Args:
        df: OHLCV DataFrame with 'atr' column
        timeframe: "H4" or "D1"
        n_pivots: Max recent pivots to consider
        atr_multiplier: Zigzag sensitivity (defaults to config value)

    Returns:
        List of KeyLevel objects sorted by price
    """
    if df is None or df.empty or "atr" not in df.columns:
        return []

    if atr_multiplier is None:
        atr_multiplier = config.ZIGZAG_ATR_MULTIPLIER

    pivots = compute_zigzag(df, atr_multiplier)
    if len(pivots) < 2:
        return []

    # Take the most recent N pivots
    recent = pivots[-n_pivots:] if len(pivots) > n_pivots else pivots

    levels: list[KeyLevel] = []
    for p in recent:
        level_type = "RESISTANCE" if p.pivot_type == "H" else "SUPPORT"
        levels.append(KeyLevel(
            price=p.price,
            timeframe=timeframe,
            level_type=level_type,
            strength=1,
        ))

    # Cluster nearby levels (within 0.3 * ATR) and merge
    if len(levels) < 2:
        return levels

    last_atr = df["atr"].dropna().iloc[-1] if len(df["atr"].dropna()) > 0 else 0
    if last_atr <= 0:
        return levels

    cluster_dist = config.KLOS_CLUSTER_ATR_MULT * last_atr
    levels.sort(key=lambda lv: lv.price)
    merged: list[KeyLevel] = [levels[0]]

    for lv in levels[1:]:
        if abs(lv.price - merged[-1].price) <= cluster_dist:
            # Merge: keep average price, sum strength, prefer higher timeframe
            merged[-1] = KeyLevel(
                price=(merged[-1].price + lv.price) / 2,
                timeframe=max(merged[-1].timeframe, lv.timeframe),
                level_type=merged[-1].level_type,
                strength=merged[-1].strength + lv.strength,
            )
        else:
            merged.append(lv)

    return merged


def score_klos_confluence(
    entry_price: float,
    direction: str,
    key_levels_4h: list[KeyLevel],
    key_levels_d1: list[KeyLevel],
    current_atr: float,
) -> float:
    """
    Score confluence with key levels (0-10).

    +5 if entry aligns with a 4H key level (within KLOS_PROXIMITY_ATR_MULT * ATR).
    +5 if entry aligns with a Daily key level.

    "Aligns" means: for LONG, entry is near a SUPPORT level.
    For SHORT, entry is near a RESISTANCE level.
    """
    if current_atr <= 0:
        return 0.0

    proximity = config.KLOS_PROXIMITY_ATR_MULT * current_atr
    score = 0.0

    target_type = "SUPPORT" if direction == "LONG" else "RESISTANCE"

    for lv in key_levels_4h:
        if lv.level_type == target_type and abs(entry_price - lv.price) <= proximity:
            score += 5.0
            break

    for lv in key_levels_d1:
        if lv.level_type == target_type and abs(entry_price - lv.price) <= proximity:
            score += 5.0
            break

    return score


def score_klos_rejection(
    entry_price: float,
    direction: str,
    key_levels_4h: list[KeyLevel],
    key_levels_d1: list[KeyLevel],
    current_atr: float,
) -> float:
    """
    Penalty when a key level opposes the entry (-10 to 0).

    If a RESISTANCE level sits just above entry for LONG (within 0.5 * ATR),
    or a SUPPORT level sits just below entry for SHORT, penalise -10.
    """
    if current_atr <= 0:
        return 0.0

    rejection_dist = config.KLOS_REJECTION_ATR_MULT * current_atr
    all_levels = key_levels_4h + key_levels_d1

    opposing_type = "RESISTANCE" if direction == "LONG" else "SUPPORT"

    for lv in all_levels:
        if lv.level_type != opposing_type:
            continue
        if direction == "LONG":
            # Resistance just above entry = bad
            if 0 < (lv.price - entry_price) <= rejection_dist:
                return -10.0
        else:
            # Support just below entry = bad
            if 0 < (entry_price - lv.price) <= rejection_dist:
                return -10.0

    return 0.0


def check_target_obstruction(
    entry_price: float,
    target_2: float,
    direction: str,
    key_levels_4h: list[KeyLevel],
    key_levels_d1: list[KeyLevel],
    current_atr: float,
) -> str | None:
    """
    Check if a key S/R level sits between entry and target_2.

    Returns a warning string if obstructed, None otherwise.
    This is metadata-only in v1 — no auto-adjustment.
    """
    if current_atr <= 0:
        return None

    all_levels = key_levels_4h + key_levels_d1
    proximity = config.KLOS_CLUSTER_ATR_MULT * current_atr

    for lv in all_levels:
        if direction == "LONG" and lv.level_type == "RESISTANCE":
            if entry_price < lv.price < target_2:
                return (
                    f"KLOS warning: {lv.timeframe} resistance at {lv.price:.5f} "
                    f"(strength={lv.strength}) between entry and target_2"
                )
        elif direction == "SHORT" and lv.level_type == "SUPPORT":
            if target_2 < lv.price < entry_price:
                return (
                    f"KLOS warning: {lv.timeframe} support at {lv.price:.5f} "
                    f"(strength={lv.strength}) between entry and target_2"
                )

    return None
