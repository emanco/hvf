"""BTC_DONCHIAN marginal-instrument stop rule — status check.

THE RULE (pre-committed 2026-07-29, before any live fill existed on these
instruments; see CLAUDE.md). Scope: JP225, US500, USTEC only — the three that
fall below the screen's own bar once overnight financing is charged
(`scripts/donchian_financing_rescore.py`). BTCUSD/ETHUSD/XAUUSD are NOT rule-
bound: they passed post-financing, and a false drop there is expensive.

  DROP an instrument on the FIRST of:
    (a) cumulative R <= -3 x sd(R)   [US500 -6.3R, USTEC -6.8R, JP225 -10.8R]
    (b) N >= 25 closed fills AND cumulative R < 0

WHY A SPEND RULE AND NOT AN INFERENCE RULE
  A "drop it once we're confident it loses" rule is impossible here. At ~5-6
  fills/yr, 80% power needs 176 years (US500), 372 (JP225) and 5,916 (USTEC) —
  the near-breakeven ones are the worst, because avgR sits in the denominator.
  So this rule does not attempt to detect a bad edge. It caps what we are
  willing to PAY to keep the experiment running.

  It WILL fire on noise roughly half the time (at n=20 the barrier sits ~0.67
  sd of the cumulative-R distribution, so P(touch) ~ 50% even if each
  instrument performs exactly as backtested). That is deliberate and cheap: the
  expected cost of a false drop is ~0 precisely because these instruments have
  ~0 expected edge (USTEC +0.034R, US500 -0.180R, JP225 +0.229R per trade). The
  asymmetry is the whole design — be trigger-happy where a mistake is free.

  Thresholds are 3 x sd(R) rather than a flat number so each instrument carries
  the same false-fire probability; JP225 swings ~1.7x harder than US500 and
  would otherwise be dropped on ordinary variance.

  Worst-case total spend if all three run to their limit: 23.9R ~= $4,500 at
  0.5% risk on $37.7k, ~12% of the account, over ~4-5 years. Expected outcome
  if the backtests are right is roughly flat (~+$57/yr); the budget is tail
  risk, not the base case. Dial the multiplier if that is too rich — but dial
  it NOW, not after seeing a drawdown.

NOT A DROP TRIGGER: re-run `donchian_financing_rescore.py` on 2027-07-29. These
  instruments fail on the CURRENT rate environment, not on a broken pattern —
  index carry is 8.35%/yr today. If financing falls materially the verdict can
  legitimately reverse, and that is an upgrade path, not goalpost-moving.

NO RE-ADD without a fresh pre-committed screen. "It recovered" is not evidence.

MEASUREMENT HYGIENE
  - Closed trades only, opened_at >= 2026-07-29.
  - `pnl_estimated=1` rows are EXCLUDED until the real deal lands (CLAUDE.md
    DO NOT: never derive a decision from a possibly-estimated PnL).
  - R = pnl / (|entry_price - stop_loss| x lot_size x dpp). `stop_loss` is the
    INITIAL stop; live trailing writes to `trailing_sl`, so the denominator is
    risk-at-entry as intended.
  - Do NOT read these off the strategy scorecard: its `opened_at >=
    PERF_GO_LIVE_DATE` era filter hides strategies that hold longer than the
    era, which is exactly BTC_DONCHIAN (see CLAUDE.md Deferred Work).

Usage (read-only):
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -u -" < scripts/donchian_stop_rule.py
"""
import os
import sqlite3
from datetime import datetime, timezone

import MetaTrader5 as mt5
from dotenv import load_dotenv

DB = r"C:/hvf_trader/hvf_trader.db"
SINCE = "2026-07-29"
PATTERN = "BTC_DONCHIAN"

# sd(R) measured on the post-financing re-score, 2017+ (donchian_financing_rescore.py)
SD_R = {"US500": 2.106, "USTEC": 2.263, "JP225": 3.608}
MULT = 3.0
RULE_BOUND = ("JP225", "US500", "USTEC")
INFO_ONLY = ("BTCUSD", "ETHUSD", "XAUUSD")
MAX_FILLS = 25

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


def dpp(sym):
    info = mt5.symbol_info(sym)
    if info is None or not info.trade_tick_size:
        return None
    return info.trade_tick_value / info.trade_tick_size


conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute(
    """SELECT symbol, entry_price, stop_loss, lot_size, pnl, pnl_estimated,
              opened_at, closed_at, close_reason
       FROM trade_records
       WHERE pattern_type = ? AND status = 'CLOSED' AND opened_at >= ?
       ORDER BY closed_at""", (PATTERN, SINCE))
rows = cur.fetchall()
conn.close()

by = {}
excluded = 0
for (sym, ep, sl, lots, pnl, est, oa, ca, reason) in rows:
    if est:
        excluded += 1
        continue
    d = dpp(sym)
    if d is None or pnl is None or ep is None or sl is None or not lots:
        excluded += 1
        continue
    risk = abs(ep - sl) * lots * d
    if risk <= 0:
        excluded += 1
        continue
    by.setdefault(sym, []).append(pnl / risk)

print("=" * 74)
print("BTC_DONCHIAN STOP RULE — status as of %s"
      % datetime.now(timezone.utc).date())
print("closed fills since %s, estimated-PnL rows excluded (%d skipped)"
      % (SINCE, excluded))
print("=" * 74)

print("\nRULE-BOUND (drop at cum R <= -%.0f x sd, or N>=%d with cum R < 0)"
      % (MULT, MAX_FILLS))
print("  %-8s %4s %9s %11s %9s   %s"
      % ("sym", "N", "cum R", "threshold", "cum $*", "status"))
any_fire = False
for sym in RULE_BOUND:
    R = by.get(sym, [])
    cum = sum(R)
    thr = -MULT * SD_R[sym]
    hit_a = cum <= thr
    hit_b = len(R) >= MAX_FILLS and cum < 0
    fire = hit_a or hit_b
    any_fire = any_fire or fire
    status = ("DROP — %s" % ("cum R breached" if hit_a else "N>=%d, cum R<0" % MAX_FILLS)) \
        if fire else ("hold (%.0f%% of budget spent)"
                      % (100 * min(1.0, max(0.0, cum / thr)) if cum < 0 else 0.0))
    print("  %-8s %4d %+9.2f %+11.2f %+9.0f   %s"
          % (sym, len(R), cum, thr, cum * 188.50, status))

print("\nINFORMATION ONLY (passed post-financing; NOT rule-bound)")
for sym in INFO_ONLY:
    R = by.get(sym, [])
    print("  %-8s %4d %+9.2f" % (sym, len(R), sum(R)))

print("\n  * cum $ is indicative only: R is booked against risk-at-entry, and")
print("    per-trade dollar risk rescales with equity (the $30k deposit on")
print("    2026-07-29 moved 0.5% from $38.50 to $188.50 per trade).")
if any_fire:
    print("\n  >>> AT LEAST ONE INSTRUMENT HAS TRIGGERED. Remove it from")
    print("      config.BTC_DONCHIAN['instances'], deploy, and do NOT re-add")
    print("      without a fresh pre-committed screen.")
mt5.shutdown()
