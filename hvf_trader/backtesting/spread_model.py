"""Per-symbol, per-hour spread model for realistic backtesting.

Replaces the legacy flat 1.5p assumption that inflated backtest PF on
cross pairs (real Asian/rollover spreads on EURAUD/CHFJPY can be
3-5x London-session levels).

Two data sources, in priority:
1. CSV file at `backtests/data/spreads.csv` with columns
   `symbol,hour_utc,median_pips,p95_pips`. Caller can produce this
   from broker tick history via a sampler script.
2. Hard-coded defaults (this module) — sensible estimates derived from
   IC Markets demo observation. Use these only until the CSV is populated.

Public API:
    get_spread_pips(symbol, hour_utc, percentile="median") -> float
    apply_slippage_pips(rng=None, mean=0.5, std=0.3, clip=(0.0, 2.0)) -> float
"""
from __future__ import annotations

import csv
import logging
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults: realistic estimates per-symbol for the three coarse regimes
# (London session 7-15 UTC, NY session 13-21 UTC, Asian/rollover 21-7 UTC).
# Tuned to be conservative — better to over-estimate spread in backtest
# than under-estimate and fool yourself.
#
# Format: symbol -> {regime: median_pips}
# Regimes: "LONDON" (7-15 UTC), "NY" (15-21 UTC), "ASIAN" (21-7 UTC),
# "ROLLOVER" (21-23 UTC — explicit overlay for the worst hour).
_SPREAD_DEFAULTS: dict[str, dict[str, float]] = {
    # Majors — tight London/NY, wider Asian
    "EURUSD":  {"LONDON": 0.8, "NY": 0.9, "ASIAN": 1.4, "ROLLOVER": 2.0},
    "GBPUSD":  {"LONDON": 1.0, "NY": 1.2, "ASIAN": 1.8, "ROLLOVER": 2.5},
    "USDCHF":  {"LONDON": 1.0, "NY": 1.2, "ASIAN": 1.7, "ROLLOVER": 2.3},
    "USDJPY":  {"LONDON": 0.9, "NY": 1.0, "ASIAN": 1.3, "ROLLOVER": 1.8},
    "NZDUSD":  {"LONDON": 1.2, "NY": 1.4, "ASIAN": 1.8, "ROLLOVER": 2.5},
    "AUDUSD":  {"LONDON": 1.0, "NY": 1.2, "ASIAN": 1.5, "ROLLOVER": 2.2},
    # EUR-crosses — wider all sessions
    "EURGBP":  {"LONDON": 1.2, "NY": 1.4, "ASIAN": 2.2, "ROLLOVER": 3.5},
    "EURAUD":  {"LONDON": 1.8, "NY": 2.2, "ASIAN": 3.5, "ROLLOVER": 5.0},
    "EURJPY":  {"LONDON": 1.3, "NY": 1.5, "ASIAN": 2.2, "ROLLOVER": 3.0},
    "EURCHF":  {"LONDON": 1.5, "NY": 1.8, "ASIAN": 2.5, "ROLLOVER": 3.5},
    # JPY-crosses
    "GBPJPY":  {"LONDON": 1.8, "NY": 2.2, "ASIAN": 3.0, "ROLLOVER": 4.5},
    "CHFJPY":  {"LONDON": 1.6, "NY": 1.9, "ASIAN": 2.8, "ROLLOVER": 4.0},
    "AUDJPY":  {"LONDON": 1.5, "NY": 1.8, "ASIAN": 2.5, "ROLLOVER": 3.5},
    "NZDJPY":  {"LONDON": 1.6, "NY": 1.9, "ASIAN": 2.8, "ROLLOVER": 4.0},
    # Commodity crosses
    "AUDNZD":  {"LONDON": 2.0, "NY": 2.3, "ASIAN": 3.5, "ROLLOVER": 5.5},
    "AUDCAD":  {"LONDON": 1.8, "NY": 2.0, "ASIAN": 3.2, "ROLLOVER": 5.0},
}

# Fallback for symbols not in the table
_FALLBACK = {"LONDON": 1.5, "NY": 1.8, "ASIAN": 2.8, "ROLLOVER": 4.0}

# CSV cache: symbol -> {hour_utc -> (median, p95)}
_csv_cache: Optional[dict[str, dict[int, tuple[float, float]]]] = None
_csv_loaded = False


def _hour_to_regime(hour_utc: int) -> str:
    """Classify a UTC hour into one of the spread regimes."""
    if 21 <= hour_utc < 23:
        return "ROLLOVER"
    if 7 <= hour_utc < 15:
        return "LONDON"
    if 15 <= hour_utc < 21:
        return "NY"
    return "ASIAN"


def _load_csv_if_present(csv_path: Path) -> None:
    """Attempt to load the spread CSV. Idempotent; quiet on missing file."""
    global _csv_cache, _csv_loaded
    if _csv_loaded:
        return
    _csv_loaded = True
    if not csv_path.exists():
        logger.info(
            "spread_model: no CSV at %s — using hard-coded defaults", csv_path,
        )
        return
    cache: dict[str, dict[int, tuple[float, float]]] = {}
    try:
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                sym = row["symbol"]
                hr = int(row["hour_utc"])
                med = float(row["median_pips"])
                p95 = float(row.get("p95_pips") or med)
                cache.setdefault(sym, {})[hr] = (med, p95)
    except Exception as e:
        logger.warning("spread_model: failed to load CSV %s: %s", csv_path, e)
        return
    _csv_cache = cache
    logger.info(
        "spread_model: loaded CSV from %s (%d symbols, %d total entries)",
        csv_path, len(cache), sum(len(v) for v in cache.values()),
    )


def get_spread_pips(
    symbol: str,
    hour_utc: int,
    percentile: str = "median",
    csv_path: Optional[Path] = None,
) -> float:
    """Return the spread (in pips) for a given symbol and UTC hour.

    Falls back to per-regime defaults if no CSV entry exists.

    Args:
        symbol: e.g. "EURUSD".
        hour_utc: 0-23.
        percentile: "median" or "p95". p95 is useful for stress tests.
        csv_path: Optional explicit path to the spread CSV. If None,
            uses the default `backtests/data/spreads.csv`.
    """
    if csv_path is None:
        try:
            from hvf_trader import config
            csv_path = config.BASE_DIR.parent / "backtests" / "data" / "spreads.csv"
        except Exception:
            csv_path = Path("backtests/data/spreads.csv")
    _load_csv_if_present(csv_path)

    if _csv_cache and symbol in _csv_cache:
        per_hr = _csv_cache[symbol]
        if hour_utc in per_hr:
            med, p95 = per_hr[hour_utc]
            return p95 if percentile == "p95" else med

    table = _SPREAD_DEFAULTS.get(symbol, _FALLBACK)
    regime = _hour_to_regime(hour_utc)
    base = table.get(regime, _FALLBACK[regime])
    if percentile == "p95":
        # Heuristic: p95 ≈ 1.6x median on top of crosses/rollover
        return base * 1.6
    return base


def apply_slippage_pips(
    rng: Optional[random.Random] = None,
    mean: float = 0.5,
    std: float = 0.3,
    clip: tuple[float, float] = (0.0, 2.0),
) -> float:
    """Sample a slippage value in pips from a clipped gaussian.

    Default mean=0.5p, std=0.3p, clipped to [0, 2]. Slippage is *adverse*
    by sign convention — the engine applies it as worse fill price for
    the trade direction.
    """
    r = rng or random
    raw = r.gauss(mean, std)
    return max(clip[0], min(clip[1], raw))


# Convenience constants for sensitivity-test runs
SLIPPAGE_SENSITIVITY_PIPS = (0.0, 0.5, 1.0, 2.0)
