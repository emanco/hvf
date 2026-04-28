"""KZ_HUNT trade-management giveback investigation.

Pulls every KZ_HUNT trade since go-live (2026-03-25), reconstructs M5 path,
computes MFE / time-to-MFE / progress to T1, and simulates three alternative
SL-management rules:

  Rule A: Move-to-breakeven at 50% of T1 distance (vs current: only after partial 100% T1).
  Rule B: Trail SL after MFE crosses 1.0x ATR (entry-side ATR), regardless of T1 partial.
  Rule C: Hard time-stop at 4 H1 bars (close at market if still open).

For each rule we replay the M5 path of every live trade and report:
  - SL closures avoided (rule exits BE/profit instead of full SL)
  - TPs missed (false positives — rule exits before T1/T2 that would have hit)
  - Net P&L delta in pips on the SL bucket and across all trades

Read-only. Uses live MT5 (VPS) + sqlite trade_records DB.
"""

import os
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from statistics import mean, median

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")

if not mt5.initialize(path=os.getenv("MT5_PATH")):
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
if not mt5.login(int(os.getenv("MT5_LOGIN")),
                password=os.getenv("MT5_PASSWORD"),
                server=os.getenv("MT5_SERVER")):
    raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

PIP_VALUES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "EURGBP": 0.0001, "EURAUD": 0.0001,
    "USDJPY": 0.01, "GBPJPY": 0.01, "EURJPY": 0.01, "CHFJPY": 0.01,
}

# ─── Pull all KZ_HUNT trades since go-live ─────────────────────────────────
conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()
cur.execute("""
SELECT t.id, t.symbol, t.direction, t.opened_at, t.closed_at,
       t.entry_price, t.stop_loss, t.target_1, t.target_2, t.lot_size,
       t.pnl, t.pnl_pips, t.close_reason, t.partial_closed,
       p.score
FROM trade_records t
LEFT JOIN pattern_records p ON p.id = t.pattern_id
WHERE t.pattern_type = 'KZ_HUNT'
  AND t.opened_at >= '2026-03-25'
  AND t.status IN ('CLOSED', 'PARTIAL')
ORDER BY t.opened_at
""")
rows = cur.fetchall()
conn.close()


def parse_dt(s):
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def fetch_atr_h1(symbol, before_dt, period=14):
    """Compute ATR(14) on H1 from bars before `before_dt`."""
    end = before_dt
    start = end - timedelta(hours=24 * 7)
    bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, start, end)
    if bars is None or len(bars) < period + 1:
        return None
    trs = []
    prev_close = None
    for b in bars:
        if prev_close is None:
            prev_close = b["close"]
            continue
        h, l, pc = b["high"], b["low"], prev_close
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
        prev_close = b["close"]
    if len(trs) < period:
        return None
    # Wilder's smoothing approximation: simple mean of last `period` TRs
    return sum(trs[-period:]) / period


# ─── Per-trade reconstruction ──────────────────────────────────────────────
trades = []
print(f"Reconstructing {len(rows)} KZ_HUNT trades from M5...")

for r in rows:
    (tid, sym, direction, opened_at, closed_at, entry, sl, tp1, tp2, lots,
     pnl, pp, close_reason, partial_closed, score) = r
    atr_value = None

    pip = PIP_VALUES.get(sym, 0.0001)
    op = parse_dt(opened_at)
    cl = parse_dt(closed_at)
    if op is None:
        continue
    if cl is None:
        cl = op + timedelta(hours=12)  # fallback
    held_h = (cl - op).total_seconds() / 3600

    # SL / T1 / T2 distances in pips
    sl_pips = abs(entry - sl) / pip if sl else 0
    t1_pips = abs(tp1 - entry) / pip if tp1 else 0
    t2_pips = abs(tp2 - entry) / pip if tp2 else 0

    # Lookback ATR_H1 from before entry for rule B
    atr_h1 = atr_value if atr_value else fetch_atr_h1(sym, op)
    atr_pips = (atr_h1 / pip) if atr_h1 else None

    # Pull M5 bars across the trade window, plus a 4h buffer for time-stop sims
    bars = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M5,
                                 op - timedelta(minutes=5),
                                 cl + timedelta(hours=8))
    if bars is None or len(bars) == 0:
        continue
    bars = list(bars)

    # Track MFE, MAE, time-to-MFE, did price reach 50% T1 / T1 / T2 / SL
    mfe_pips = 0.0
    mae_pips = 0.0
    t_to_mfe = None
    reached_50pct_t1_at = None
    reached_t1_at = None
    reached_t2_at = None
    reached_sl_at = None
    half_t1 = entry + (tp1 - entry) * 0.5 if tp1 else None

    for b in bars:
        bt = datetime.fromtimestamp(b["time"], tz=timezone.utc)
        if bt < op:
            continue
        # Only count MFE/MAE for bars within the actual trade window
        # (post-close buffer is kept in _bars for rule sims but excluded here)
        in_trade_window = bt <= cl
        if direction == "LONG":
            high_pips = (b["high"] - entry) / pip
            low_pips  = (b["low"]  - entry) / pip
            if in_trade_window and high_pips > mfe_pips:
                mfe_pips = high_pips
                t_to_mfe = (bt - op).total_seconds() / 60  # minutes
            if in_trade_window and low_pips < mae_pips:
                mae_pips = low_pips
            if in_trade_window and half_t1 is not None and reached_50pct_t1_at is None and b["high"] >= half_t1:
                reached_50pct_t1_at = bt
            if in_trade_window and tp1 is not None and reached_t1_at is None and b["high"] >= tp1:
                reached_t1_at = bt
            if in_trade_window and tp2 is not None and reached_t2_at is None and b["high"] >= tp2:
                reached_t2_at = bt
            if in_trade_window and sl is not None and reached_sl_at is None and b["low"] <= sl:
                reached_sl_at = bt
        else:  # SHORT
            high_pips = (entry - b["low"])  / pip   # favorable for SHORT
            low_pips  = (entry - b["high"]) / pip   # adverse for SHORT
            if in_trade_window and high_pips > mfe_pips:
                mfe_pips = high_pips
                t_to_mfe = (bt - op).total_seconds() / 60
            if in_trade_window and low_pips < mae_pips:
                mae_pips = low_pips
            if in_trade_window and half_t1 is not None and reached_50pct_t1_at is None and b["low"] <= half_t1:
                reached_50pct_t1_at = bt
            if in_trade_window and tp1 is not None and reached_t1_at is None and b["low"] <= tp1:
                reached_t1_at = bt
            if in_trade_window and tp2 is not None and reached_t2_at is None and b["low"] <= tp2:
                reached_t2_at = bt
            if in_trade_window and sl is not None and reached_sl_at is None and b["high"] >= sl:
                reached_sl_at = bt

    # Cap mae for SL-hit trades
    if close_reason == "STOP_LOSS" and abs(mae_pips) > sl_pips:
        mae_pips = -sl_pips

    trades.append({
        "id": tid, "symbol": sym, "direction": direction,
        "opened_at": op, "closed_at": cl, "held_h": held_h,
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
        "sl_pips": sl_pips, "t1_pips": t1_pips, "t2_pips": t2_pips,
        "close_reason": close_reason, "partial_closed": bool(partial_closed),
        "actual_pnl_pips": pp or 0,
        "score": score or 0,
        "atr_pips_h1": atr_pips,
        "mfe_pips": round(mfe_pips, 1), "mae_pips": round(mae_pips, 1),
        "t_to_mfe_min": round(t_to_mfe, 1) if t_to_mfe else None,
        "reached_50pct_t1_at": reached_50pct_t1_at,
        "reached_t1_at": reached_t1_at,
        "reached_t2_at": reached_t2_at,
        "reached_sl_at": reached_sl_at,
        "_bars": bars,  # keep for replay
    })

print(f"Reconstructed {len(trades)} trades.")
sl_trades = [t for t in trades if t["close_reason"] == "STOP_LOSS"]
print(f"  STOP_LOSS: {len(sl_trades)}")
print(f"  TAKE_PROFIT/TP/etc: {len([t for t in trades if t['close_reason'] in ('TAKE_PROFIT', 'TARGET_1', 'TARGET_2', 'BREAKEVEN_SL', 'TRAILING_STOP', 'INVALIDATION', 'TIME_EXIT')])}")

# ─── Question 2: MFE bucket breakdown for the 16 mfe>5p SL trades ─────────
print()
print("=" * 90)
print("MFE BUCKETS — STOP_LOSS TRADES")
print("=" * 90)
buckets = [(0, 5), (5, 10), (10, 20), (20, 50), (50, 999)]
for lo, hi in buckets:
    in_b = [t for t in sl_trades if lo <= t["mfe_pips"] < hi]
    print(f"  MFE {lo:>3}-{hi:<3}p: {len(in_b):2d} trades", end="")
    if in_b:
        avg_t1_progress = mean(t["mfe_pips"] / t["t1_pips"] * 100 if t["t1_pips"] else 0 for t in in_b)
        n_50pct = sum(1 for t in in_b if t["reached_50pct_t1_at"] is not None)
        n_t1    = sum(1 for t in in_b if t["reached_t1_at"] is not None)
        print(f"  avgT1Progress={avg_t1_progress:.0f}%  reached50%T1={n_50pct}  reachedT1={n_t1}")
    else:
        print()

print()
print("=" * 90)
print("DETAIL — SL TRADES WITH MFE > 5p (the 'giveback' bucket)")
print("=" * 90)
print(f"{'ID':>4} {'SYM':<7} {'DIR':<5} {'SL_p':>5} {'T1_p':>5} {'MFE':>5} "
      f"{'T1prog%':>7} {'50%T1':>6} {'T1':>4} {'tMFE_m':>7} {'Held_h':>7}")
print("-" * 90)
giveback = sorted(
    [t for t in sl_trades if t["mfe_pips"] > 5],
    key=lambda t: -t["mfe_pips"],
)
for t in giveback:
    t1prog = t["mfe_pips"] / t["t1_pips"] * 100 if t["t1_pips"] else 0
    h50 = "Y" if t["reached_50pct_t1_at"] else "N"
    h1  = "Y" if t["reached_t1_at"] else "N"
    print(f"{t['id']:>4} {t['symbol']:<7} {t['direction']:<5} "
          f"{t['sl_pips']:>5.1f} {t['t1_pips']:>5.1f} {t['mfe_pips']:>5.1f} "
          f"{t1prog:>6.0f}% {h50:>6} {h1:>4} "
          f"{t['t_to_mfe_min'] or 0:>7.1f} {t['held_h']:>7.2f}")

# ─── Rule simulator ──────────────────────────────────────────────────────
def simulate(trade, rule):
    """Replay a trade's M5 path under an alternative SL rule.

    rule: dict with keys
        be_at_pct: float | None  — move SL → entry when MFE >= this fraction of T1
        trail_after_atr: float | None — when MFE >= N * ATR_H1, start trailing
                          remaining position at trail_atr_mult * ATR_H1
        trail_atr_mult: float
        time_stop_h: int | None — close at market after this many H1 bars
                     (4 = 240 minutes from entry)
        partial_close_pct: float — defaults to 0.60

    Returns dict: outcome, pnl_pips
        outcome ∈ {"T2_FULL", "T1_PARTIAL_THEN_BE", "T1_PARTIAL_THEN_TRAIL_PROFIT",
                   "T1_PARTIAL_THEN_BE_HIT", "BE_AVOID_SL", "TRAIL_AVOID_SL",
                   "TIME_STOP", "STOP_LOSS"}
    """
    direction = trade["direction"]
    entry = trade["entry"]
    sl = trade["sl"]
    tp1 = trade["tp1"]
    tp2 = trade["tp2"]
    op = trade["opened_at"]
    pip = PIP_VALUES.get(trade["symbol"], 0.0001)
    atr_h1 = trade["atr_pips_h1"]   # in pips
    sl_pips = trade["sl_pips"]
    pcp = rule.get("partial_close_pct", 0.60)

    # State
    sl_curr = sl
    partial_done = False
    trailing_active = False
    extreme_since = None   # highest (LONG) / lowest (SHORT) seen since trail activation
    pnl_pips = 0.0          # realized P&L from partial closes
    half_t1 = entry + (tp1 - entry) * 0.5 if tp1 else None

    # MFE tracking for be_at_pct trigger
    mfe_pips_running = 0.0

    # Time stop
    time_stop_h = rule.get("time_stop_h")
    time_stop_ts = (op + timedelta(hours=time_stop_h)) if time_stop_h else None

    for b in trade["_bars"]:
        bt = datetime.fromtimestamp(b["time"], tz=timezone.utc)
        if bt < op:
            continue
        bh, bl = b["high"], b["low"]

        # Update running MFE within this bar (use favorable extreme of bar)
        if direction == "LONG":
            bar_fav = (bh - entry) / pip
            bar_adv = (bl - entry) / pip
        else:
            bar_fav = (entry - bl) / pip
            bar_adv = (entry - bh) / pip

        # Per-bar order of events (assume worst-case for our trade):
        #   1. Check SL hit (use adverse extreme first)
        #   2. Check TP / partial / BE / trail movements
        # For BE moves: move BEFORE checking SL again, so a tagging move
        # that triggers BE on the same bar lets the trade exit at BE not SL.

        # Time stop fires at bar containing time_stop_ts
        if time_stop_ts and bt >= time_stop_ts:
            # Close at bar open
            if direction == "LONG":
                close_p = (b["open"] - entry) / pip
            else:
                close_p = (entry - b["open"]) / pip
            if partial_done:
                pnl_pips += close_p * (1 - pcp)
                return {"outcome": "TIME_STOP_AFTER_PARTIAL", "pnl_pips": pnl_pips}
            return {"outcome": "TIME_STOP", "pnl_pips": close_p}

        # Check rule-A breakeven trigger (MFE crosses pct of T1)
        be_at_pct = rule.get("be_at_pct")
        if be_at_pct is not None and not partial_done and tp1 is not None:
            t1_pips_total = abs(tp1 - entry) / pip
            trigger_pips = t1_pips_total * be_at_pct
            if bar_fav >= trigger_pips:
                # Move SL to entry (BE)
                if (direction == "LONG" and sl_curr < entry) or \
                   (direction == "SHORT" and sl_curr > entry):
                    sl_curr = entry

        # Check rule-B trail trigger (MFE >= N * ATR_H1)
        trail_after_atr = rule.get("trail_after_atr")
        trail_atr_mult = rule.get("trail_atr_mult", 1.0)
        if trail_after_atr is not None and atr_h1 is not None and not trailing_active:
            if bar_fav >= trail_after_atr * atr_h1:
                trailing_active = True
                extreme_since = bh if direction == "LONG" else bl
                # Move SL to entry as initial trail anchor
                if (direction == "LONG" and sl_curr < entry) or \
                   (direction == "SHORT" and sl_curr > entry):
                    sl_curr = entry

        # If trailing active, update trailing SL using bar extreme
        if trailing_active and atr_h1 is not None:
            if direction == "LONG":
                if bh > extreme_since:
                    extreme_since = bh
                new_sl = extreme_since - trail_atr_mult * atr_h1 * pip
                if new_sl > sl_curr:
                    sl_curr = new_sl
            else:
                if bl < extreme_since:
                    extreme_since = bl
                new_sl = extreme_since + trail_atr_mult * atr_h1 * pip
                if new_sl < sl_curr:
                    sl_curr = new_sl

        # Now check for SL hit using bar's adverse extreme
        if direction == "LONG":
            if bl <= sl_curr:
                # SL hit. Compute pnl
                exit_pips = (sl_curr - entry) / pip
                if partial_done:
                    pnl_pips += exit_pips * (1 - pcp)
                    return {
                        "outcome": "T1_PARTIAL_THEN_TRAIL_OR_BE",
                        "pnl_pips": pnl_pips,
                    }
                # Pure SL exit, but if sl_curr > sl (original) → BE/trail saved us
                if sl_curr > sl + 1e-9:
                    return {"outcome": "BE_OR_TRAIL_AVOID_SL", "pnl_pips": exit_pips}
                return {"outcome": "STOP_LOSS", "pnl_pips": exit_pips}
        else:
            if bh >= sl_curr:
                exit_pips = (entry - sl_curr) / pip
                if partial_done:
                    pnl_pips += exit_pips * (1 - pcp)
                    return {
                        "outcome": "T1_PARTIAL_THEN_TRAIL_OR_BE",
                        "pnl_pips": pnl_pips,
                    }
                if sl_curr < sl - 1e-9:
                    return {"outcome": "BE_OR_TRAIL_AVOID_SL", "pnl_pips": exit_pips}
                return {"outcome": "STOP_LOSS", "pnl_pips": exit_pips}

        # Check T1
        if not partial_done and tp1 is not None:
            t1_hit = (direction == "LONG" and bh >= tp1) or \
                     (direction == "SHORT" and bl <= tp1)
            if t1_hit:
                t1_pips = abs(tp1 - entry) / pip
                pnl_pips += t1_pips * pcp
                partial_done = True
                # Move SL to BE (matches current production rule)
                if (direction == "LONG" and sl_curr < entry) or \
                   (direction == "SHORT" and sl_curr > entry):
                    sl_curr = entry
                # Activate trailing on remainder if rule wants it (production: yes)
                if not trailing_active and atr_h1 is not None:
                    trailing_active = True
                    extreme_since = bh if direction == "LONG" else bl

        # Check T2
        if tp2 is not None:
            t2_hit = (direction == "LONG" and bh >= tp2) or \
                     (direction == "SHORT" and bl <= tp2)
            if t2_hit:
                t2_pips = abs(tp2 - entry) / pip
                if partial_done:
                    pnl_pips += t2_pips * (1 - pcp)
                else:
                    pnl_pips += t2_pips
                return {"outcome": "TARGET_2", "pnl_pips": pnl_pips}

    # Bars exhausted — close at last bar's close price
    last = trade["_bars"][-1]
    if direction == "LONG":
        exit_pips = (last["close"] - entry) / pip
    else:
        exit_pips = (entry - last["close"]) / pip
    if partial_done:
        pnl_pips += exit_pips * (1 - pcp)
        return {"outcome": "EOF_AFTER_PARTIAL", "pnl_pips": pnl_pips}
    return {"outcome": "EOF", "pnl_pips": exit_pips}


# Baseline: production behavior — no rule changes (just T1/T2 + initial SL)
def baseline(trade):
    return simulate(trade, {})


def summarize_rule(name, results, baselines, all_trades):
    """Print summary for one rule."""
    sl_avoided = 0
    tp_missed = 0
    delta_total = 0.0
    delta_sl_bucket = 0.0
    for t, r, base in zip(all_trades, results, baselines):
        delta = r["pnl_pips"] - base["pnl_pips"]
        delta_total += delta
        if t["close_reason"] == "STOP_LOSS":
            delta_sl_bucket += delta
        # SL avoided: baseline was full SL, rule got better
        if base["outcome"] == "STOP_LOSS" and r["outcome"] != "STOP_LOSS":
            sl_avoided += 1
        # TP missed: baseline reached TARGET_1/TARGET_2, rule didn't
        if base["outcome"] == "TARGET_2" and r["outcome"] != "TARGET_2":
            tp_missed += 1

    print()
    print("=" * 90)
    print(f"RULE: {name}")
    print("=" * 90)
    print(f"  SL closures avoided     : {sl_avoided}")
    print(f"  TPs missed (T2 lost)    : {tp_missed}")
    print(f"  Net P&L delta (all)     : {delta_total:+.1f} pips")
    print(f"  Net P&L delta (SL only) : {delta_sl_bucket:+.1f} pips")

    # Outcome distribution
    by_outcome = defaultdict(int)
    for r in results:
        by_outcome[r["outcome"]] += 1
    print(f"  Outcome distribution    : {dict(sorted(by_outcome.items(), key=lambda x: -x[1]))}")


# ─── Run baseline + 3 candidate rules + combos ─────────────────────────────
print()
print("Running rule simulations on all", len(trades), "trades...")
baselines = [baseline(t) for t in trades]

rules = {
    "Baseline (production: T1 partial + BE + 1.0×ATR trail on remainder)": {},
    "Rule A: BE at 50% of T1 distance":
        {"be_at_pct": 0.50},
    "Rule A2: BE at 33% of T1":
        {"be_at_pct": 0.33},
    "Rule A3: BE at 67% of T1":
        {"be_at_pct": 0.67},
    "Rule B: Trail at 1.0×ATR after MFE>=1.0×ATR":
        {"trail_after_atr": 1.0, "trail_atr_mult": 1.0},
    "Rule B2: Trail at 1.5×ATR after MFE>=1.5×ATR":
        {"trail_after_atr": 1.5, "trail_atr_mult": 1.5},
    "Rule C: Hard time-stop at 4 H1 bars":
        {"time_stop_h": 4},
    "Rule C2: Hard time-stop at 6 H1 bars":
        {"time_stop_h": 6},
    "Rule C3: Hard time-stop at 8 H1 bars":
        {"time_stop_h": 8},
    "Combo A+C: BE at 50% T1 + 6h time-stop":
        {"be_at_pct": 0.50, "time_stop_h": 6},
    "Combo A+B: BE at 50% T1 + Trail 1.0×ATR after MFE>=1.0×ATR":
        {"be_at_pct": 0.50, "trail_after_atr": 1.0, "trail_atr_mult": 1.0},
}

for name, rule in rules.items():
    results = [simulate(t, rule) for t in trades]
    if not rule:
        # Baseline — still print summary
        summarize_rule(name, results, baselines, trades)
    else:
        summarize_rule(name, results, baselines, trades)

# ─── SL bucket per-rule deep dive ──────────────────────────────────────────
print()
print("=" * 90)
print("PER-TRADE OUTCOMES on the 16 high-MFE SL trades (MFE>5p)")
print("=" * 90)

high_mfe = [t for t in sl_trades if t["mfe_pips"] > 5]
high_mfe_idx = [trades.index(t) for t in high_mfe]

# Show each high-mfe trade's outcome under every rule
header_rules = list(rules.keys())
short_names = {
    "Baseline (production: T1 partial + BE + 1.0×ATR trail on remainder)": "Base",
    "Rule A: BE at 50% of T1 distance": "A_BE50",
    "Rule A2: BE at 33% of T1": "A_BE33",
    "Rule A3: BE at 67% of T1": "A_BE67",
    "Rule B: Trail at 1.0×ATR after MFE>=1.0×ATR": "B_Trail",
    "Rule B2: Trail at 1.5×ATR after MFE>=1.5×ATR": "B2_Trail",
    "Rule C: Hard time-stop at 4 H1 bars": "C_4h",
    "Rule C2: Hard time-stop at 6 H1 bars": "C_6h",
    "Rule C3: Hard time-stop at 8 H1 bars": "C_8h",
    "Combo A+C: BE at 50% T1 + 6h time-stop": "AC_combo",
    "Combo A+B: BE at 50% T1 + Trail 1.0×ATR after MFE>=1.0×ATR": "AB_combo",
}
abbr = [short_names[k] for k in header_rules]

print(f"{'ID':>4} {'SYM':<7} {'MFE':>5} {'SLp':>5} ", end="")
for a in abbr:
    print(f"{a:>10}", end="")
print()
for idx, t in zip(high_mfe_idx, high_mfe):
    print(f"{t['id']:>4} {t['symbol']:<7} {t['mfe_pips']:>5.1f} {t['sl_pips']:>5.1f} ", end="")
    for name in header_rules:
        rule = rules[name]
        r = simulate(t, rule)
        pnl = r["pnl_pips"]
        print(f"{pnl:>+10.1f}", end="")
    print()

mt5.shutdown()
print()
print("Done.")
