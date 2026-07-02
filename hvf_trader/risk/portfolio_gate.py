"""Portfolio-level entry gate shared by all strategy execution paths.

2026-07-02 audit finding: the 8-gate RiskManager guards only the retired
KZ_HUNT code paths — the live strategies executed with no aggregate
control at all (no concurrency cap, no margin check, no exposure limit,
and resting pending orders invisible to everything). This module is the
minimal shared gate called by every strategy right before it places
orders:

  - total bot positions cap (and positions+pendings cap — pendings count)
  - free-margin floor
  - generous per-currency leg cap (forex symbols only)

All counts come from BROKER state (positions_get/orders_get filtered to
the bot's magic numbers), not the DB, so untracked/orphan orders still
count. Checks run under a lock with a short-lived reservation held while
the caller places its orders, so two scanner threads can't both pass the
last slot (the TOCTOU race flagged in the audit).

Deliberately PERMISSIVE — demo/validation phase (user call, 2026-07-02):
limits are sized so normal operation never touches them; they exist to
stop runaway states, not to shape the portfolio. Tighten before real
money. Fail-open: a flaky broker query must not block trading.
"""
import logging
import threading
from contextlib import contextmanager

from hvf_trader import config

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

_lock = threading.Lock()
_reservations = 0


def _currencies(symbol: str) -> set:
    """Currency legs of a standard 6-letter forex symbol; empty for
    crypto/index symbols (no currency-exposure semantics)."""
    if len(symbol) == 6 and symbol.isalpha():
        return {symbol[:3].upper(), symbol[3:].upper()}
    return set()


def _evaluate(symbol, n_positions, n_pendings, n_reserved,
              free_margin, equity, currency_counts, cfg):
    """Pure decision logic (unit-tested separately). Returns (allowed, reason)."""
    if n_positions + n_reserved >= cfg["max_positions"]:
        return False, (f"positions {n_positions}+{n_reserved} in-flight >= "
                       f"cap {cfg['max_positions']}")
    total = n_positions + n_pendings + n_reserved
    if total >= cfg["max_total_exposures"]:
        return False, (f"positions+pendings {total} >= cap "
                       f"{cfg['max_total_exposures']}")
    if equity > 0:
        free_pct = free_margin / equity * 100.0
        if free_pct < cfg["min_free_margin_pct"]:
            return False, (f"free margin {free_pct:.0f}% < floor "
                           f"{cfg['min_free_margin_pct']:.0f}%")
    for ccy in _currencies(symbol):
        if currency_counts.get(ccy, 0) >= cfg["max_per_currency"]:
            return False, (f"{ccy} legs {currency_counts[ccy]} >= cap "
                           f"{cfg['max_per_currency']}")
    return True, "ok"


@contextmanager
def reserve(symbol: str, slots: int = 1):
    """Check the gate and hold `slots` reservations while the caller places
    its order(s). Yields (allowed, reason).

    Usage:
        with portfolio_gate.reserve(sym) as (ok, reason):
            if not ok:
                ...log/alert...
                return
            ...size and place orders...
    """
    global _reservations
    cfg = getattr(config, "PORTFOLIO_GATE", None)
    if not cfg or not cfg.get("enabled", True) or not MT5_AVAILABLE:
        yield True, "gate disabled"
        return

    allowed, reason, reserved = True, "ok", False
    with _lock:
        try:
            positions = [p for p in (mt5.positions_get() or ())
                         if p.magic in config.BOT_MAGICS]
            orders = [o for o in (mt5.orders_get() or ())
                      if o.magic in config.BOT_MAGICS]
            acct = mt5.account_info()
            if acct is None:
                raise RuntimeError("account_info() returned None")
            ccy_counts = {}
            for p in positions:
                for c in _currencies(p.symbol):
                    ccy_counts[c] = ccy_counts.get(c, 0) + 1
            allowed, reason = _evaluate(
                symbol, len(positions), len(orders), _reservations,
                acct.margin_free, acct.equity, ccy_counts, cfg,
            )
        except Exception as e:
            # Fail-open by design (see module docstring).
            allowed, reason = True, f"broker query failed, fail-open: {e}"
            logger.warning("[PORTFOLIO_GATE] %s", reason)
        if allowed:
            _reservations += slots
            reserved = True

    if not allowed:
        logger.warning("[PORTFOLIO_GATE] %s blocked: %s", symbol, reason)
        yield False, reason
        return
    try:
        yield True, reason
    finally:
        if reserved:
            with _lock:
                _reservations -= slots
