"""Pair-extension screen for ASB (and, disabled, LONDON_BO) — pre-registered.

═══ WHY THIS FILE WAS REWRITTEN (2026-07-28) ═══
The original screen was CONTAMINATED and its output void. It shipped two
independent fill fictions, and its ASB numbers (GBPJPY 5.81, EURUSD 3.69,
USDJPY ...) are reproduced *exactly* by `scripts/asb_fill_audit.py` as that
audit's naive row — i.e. the screen inherited both bugs wholesale. USDJPY and
EURUSD were added to live ASB on those numbers and dropped again 2026-07-28.

  Fiction 1 — blind-gap fill. The range ends at true UTC ~04:00 but the bracket
  is armed at 07:00. On days price has already traded through a stop level by
  07:00 that pending stop is UN-PLACEABLE live (IC retcode 10015), yet the old
  code filled it at the level anyway. Win rate is unaffected — only the payoff
  degrades — so this is invisible in every surface metric. It manufactured
  LONDON_BO's entire PF 1.63.

  Fiction 2 — stop-modify through market. The old BE12 model was
  `eff_sl = entry_px if bar.hour >= be_h else sl_px`, unconditional. MT5 rejects
  an SL through the market (retcode 10016), so on exactly the underwater trades
  BE12 was meant to save, the modify FAILS. The sim booked a free ~-0.1R
  scratch; live keeps the original stop. ~60% of the sim's BE exits were
  impossible. This alone was worth 4x on GBPJPY (PF 5.40 -> 1.36).

Both are now modelled honestly, by porting the audited `simulate()` from
`scripts/asb_fill_audit.py` verbatim rather than re-deriving it. The port is
verified end-to-end by the INCUMBENT SANITY ROW (see below) — if GBPJPY stops
reproducing the audit, the harness is wrong and every other row is void.

═══ HARNESS SANITY (non-negotiable) ═══
GBPJPY carries vol-scale factor 1.00 by construction, so its screen params are
identical to the audit's hand-set ones. It MUST reproduce `asb_fill_audit.py`
row E ("+honest BE12") on PF *and* N, in both periods and both cost columns —
see SANITY below. This is asserted at runtime and a mismatch aborts with a
non-zero exit: a screen that cannot reproduce a known-good number cannot be
trusted on an unknown one. (It has already earned its keep — it caught that the
"1.13" quoted in CLAUDE.md is a FULL-period figure, not the 2023+ one.)

═══ COSTS ═══
Absolute thresholds scale by relative volatility (pair median ADR vs GBPJPY),
so there is zero per-pair tuning. Spread: the recorded per-bar `spread` field
medians to ~0 on IC raw pricing (a known cost trap), so every verdict is taken
on the FLOORED-spread column; the recorded-spread column is printed alongside
as the optimistic bound. Commission uses the audit's measured per-pair values
where they exist and is otherwise derived from the broker's own tick value.

═══ PASS BAR (pre-committed, RECALIBRATED 2026-07-28) ═══
The old bar (2023+ PF >= 1.4, yearly avgR > 0, test PF >= 1.2) was calibrated
against inflated numbers, where clearing PF 1.4 was trivial. On honest fills the
LIVE INCUMBENT scores ~1.13-1.36 and would FAIL its own screen. The bar is
therefore reset to bracket the incumbent rather than the fiction:

    (1) 2023+ PF >= 1.25 on FLOORED spread
    (2) avgR > 0 in each of 2023, 2024, 2025
    (3) train (<2025) avgR > 0 AND test (2025+) avgR > 0
    (4) N >= 60 since 2023

(3) is avgR-based, not PF-based: at ~2.6 fills/mo a 2025+ test leg is N~40 and a
PF threshold there is noise. The bar is stated here BEFORE any candidate is run
and must not be moved to admit one.

Read-only. Run:
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/pair_extension_screen.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()

RUN_LBO = False   # LONDON_BO retired 2026-07-28 ("do not rebuild"). See bottom.

SPLIT = datetime(2025, 1, 1).date()
FULL_YEARS = (2023, 2024, 2025)

# Pass bar — pre-committed, see module docstring.
BAR_PF23 = 1.25
BAR_MIN_N = 60

# ASB geometry, mirroring config.ASIAN_SESSION_BREAKOUT (deploy == screen).
ASB_PAIRS = ["GBPJPY", "EURUSD", "USDJPY", "AUDJPY"]
INCUMBENT = "GBPJPY"
MIN_PCT, MAX_PCT = 0.4, 1.0
BUF_PCT = 0.10
TP_MULT = 1.0
SKIP_WD = (4, 5, 6)          # true-UTC Fri/Sat/Sun
BE_HOUR = 12                 # true UTC, deployed 2026-07-15
EOD_HOUR = 20                # true UTC
# GBPJPY-absolute bases; every other pair vol-scales off these.
MIN_BUF_BASE = 2.0
TREND_THR_BASE = 30.0
SP_FLOOR_BASE = 1.5

# Measured commissions (pips) from scripts/asb_fill_audit.py. Kept verbatim for
# the audited pairs so the sanity row reproduces bit-for-bit; anything else is
# derived from the broker tick value below.
COMM_MEASURED = {"GBPJPY": 1.00, "USDJPY": 1.05, "EURUSD": 0.70}
COMM_ROUND_TRIP_USD = 7.0    # IC raw: $3.50/side/lot

# What the incumbent must reproduce — taken directly from a live re-run of
# scripts/asb_fill_audit.py (row E "+honest BE12", and its floored-spread
# sensitivity block), NOT from prose. Both periods are pinned because the two
# columns are easy to confuse: CLAUDE.md quotes GBPJPY as "1.36 (1.13 floored)"
# but 1.36 is the 2023+ figure and 1.13 is the FULL-period one — the like-for-
# like floored pair is 1.20 -> 1.13 (FULL) and 1.36 -> 1.28 (2023+).
# (col, period, PF, N)
SANITY = [
    ("honest",  "FULL",  1.20, 116),
    ("honest",  "2023+", 1.36, 109),
    ("floored", "FULL",  1.13, 116),
    ("floored", "2023+", 1.28, 109),
]
SANITY_TOL = 0.02


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def pip_of(sym):
    return 0.01 if "JPY" in sym else 0.0001


def comm_of(sym, pip):
    """Commission in pips. Prefer the audit's measured value; else derive from
    the broker's own tick economics so a new pair isn't charged a made-up cost."""
    if sym in COMM_MEASURED:
        return COMM_MEASURED[sym]
    info = mt5.symbol_info(sym)
    if info is None or not info.trade_tick_value or not info.trade_tick_size:
        return 1.0 if "JPY" in sym else 0.7
    pip_value = info.trade_tick_value * (pip / info.trade_tick_size)
    if pip_value <= 0:
        return 1.0 if "JPY" in sym else 0.7
    return COMM_ROUND_TRIP_USD / pip_value


def load(sym):
    m15 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 99000))
    h1 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000))
    if m15 is None or len(m15) < 20000:
        return None, None
    for df in (m15, h1):
        df["bt"] = pd.to_datetime(df["time"], unit="s")   # broker-labelled
    m15["bdate"] = m15["bt"].dt.date
    m15["bh"] = m15["bt"].dt.hour
    return m15, h1.sort_values("bt").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Ported verbatim from scripts/asb_fill_audit.py::simulate (the audited model).
# Do not "simplify" the arm-check or the BE arming — both encode broker
# rejections that the naive version silently transacts through.
#
#   be12: None      no breakeven overlay at all
#         "naive"   THE FICTION — SL teleports to entry at BE_HOUR. Kept only
#                   so the contaminated original can be reproduced on demand.
#         "honest"  SL moves to entry only once price trades back through it
#                   (i.e. only when MT5 would actually accept the modify).
#         "cut"     unvalidated candidate: market-close an underwater trade at
#                   BE_HOUR. Always fillable, unlike an SL through market.
#   arm_check: drop pending legs that were un-placeable at window open (10015).
#   gap_fill:  a bar OPENING beyond a stop fills at that open, not at the level.
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sym, m15, h1, cfg, be12, arm_check, gap_fill, sp_floor=False):
    PIP = cfg["pip"]
    daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
    daily["rng"] = daily["hi"] - daily["lo"]
    ddates = list(daily.index)
    by_date = {d: g.sort_values("bt").reset_index(drop=True)
               for d, g in m15.groupby("bdate")}

    trades, blocked = [], {"long": 0, "short": 0, "days": 0}
    for di, D in enumerate(ddates):
        g = by_date[D]
        rep = datetime(D.year, D.month, D.day, 7, tzinfo=timezone.utc)
        off = eu_dst_offset(rep)
        if rep.weekday() in SKIP_WD:
            continue
        asian = g[(g["bh"] >= 0) & (g["bh"] < 7)]
        if len(asian) < 16:
            continue
        hi, lo = float(asian["high"].max()), float(asian["low"].min())
        rng_p = (hi - lo) / PIP
        prior = [d for d in ddates[max(0, di - 45):di]][-30:]
        rngs = daily.loc[prior, "rng"].dropna()
        if len(rngs) < 14:
            continue
        adr_p = float(rngs.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]) / PIP
        if not (MIN_PCT * adr_p <= rng_p <= MAX_PCT * adr_p):
            continue
        buf = max(cfg["min_buf"], BUF_PCT * rng_p)
        long_stop = hi + buf * PIP
        short_stop = lo - buf * PIP

        cap_bt = pd.Timestamp(datetime(D.year, D.month, D.day, 7 + off))
        hh = h1[h1["bt"] < cap_bt]
        if len(hh) < 200:
            continue
        closes = hh["close"].tail(719).tolist()
        form = h1[h1["bt"] == cap_bt]
        closes.append(float(form["open"].iloc[0]) if len(form) else closes[-1])
        ema = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1]
        diff_p = (closes[-1] - ema) / PIP
        place_long, place_short = True, True
        if diff_p > cfg["trend_thr"]:
            place_short = False
        elif diff_p < -cfg["trend_thr"]:
            place_long = False

        win = g[(g["bh"] >= 7 + off) & (g["bh"] < 11 + off)]
        if win.empty:
            continue
        win = win.reset_index(drop=True)

        # --- arm-check: could the pending stop legally be placed at 07:00? ---
        ref = float(win.iloc[0]["open"])
        bl = ref >= long_stop
        bs = ref <= short_stop
        if bl or bs:
            blocked["days"] += 1
            blocked["long"] += int(bl and place_long)
            blocked["short"] += int(bs and place_short)
        if arm_check:
            if bl:
                place_long = False
            if bs:
                place_short = False
        if not (place_long or place_short):
            continue

        risk_p = rng_p + 2 * buf
        entry_i = direction = None
        for i in range(len(win)):
            b = win.iloc[i]
            lt = place_long and b["high"] >= long_stop
            st = place_short and b["low"] <= short_stop
            if lt and st:
                entry_i, direction = i, "BOTH"
                break
            if lt:
                entry_i, direction = i, "LONG"
                break
            if st:
                entry_i, direction = i, "SHORT"
                break
        if entry_i is None:
            continue

        eb = win.iloc[entry_i]
        sp = float(eb["spread"]) / 10.0
        if sp_floor:
            sp = max(sp, cfg["sp_floor"])
        cost = sp + cfg["comm"]

        if direction == "BOTH":
            trades.append(dict(date=D, year=D.year, dir=direction,
                               pnl=-risk_p - cost, risk=risk_p + cost,
                               reason="SPAN_SL", blocked=(bl or bs), uw=False))
            continue

        if direction == "LONG":
            entry = (max(long_stop, float(eb["open"]))
                     if gap_fill and float(eb["open"]) > long_stop else long_stop)
            sl, tp = short_stop, long_stop + rng_p * TP_MULT * PIP
        else:
            entry = (min(short_stop, float(eb["open"]))
                     if gap_fill and float(eb["open"]) < short_stop else short_stop)
            sl, tp = long_stop, short_stop - rng_p * TP_MULT * PIP

        after = g[(g["bt"] >= eb["bt"]) & (g["bh"] < EOD_HOUR + off)].reset_index(drop=True)
        pnl = reason = None
        be_armed = False
        underwater_at_be = None
        for j in range(len(after)):
            b = after.iloc[j]
            in_be = b["bh"] >= BE_HOUR + off
            if in_be and underwater_at_be is None:
                underwater_at_be = (float(b["open"]) < entry if direction == "LONG"
                                    else float(b["open"]) > entry)
            if be12 == "cut" and in_be and underwater_at_be and not be_armed:
                o = float(b["open"])
                raw = (o - entry) if direction == "LONG" else (entry - o)
                pnl, reason = raw / PIP - cost, "CUT"
                break
            if be12 == "naive":
                cur_sl = entry if in_be else sl
            elif be12 in ("honest", "cut"):
                cur_sl = entry if be_armed else sl
            else:
                cur_sl = sl
            if direction == "LONG":
                if b["low"] <= cur_sl:
                    pnl = (cur_sl - entry) / PIP - cost
                    reason = "BE" if cur_sl == entry and be12 else "SL"
                    break
                if b["high"] >= tp:
                    pnl, reason = (tp - entry) / PIP - cost, "TP"
                    break
            else:
                if b["high"] >= cur_sl:
                    pnl = (entry - cur_sl) / PIP - cost
                    reason = "BE" if cur_sl == entry and be12 else "SL"
                    break
                if b["low"] <= tp:
                    pnl, reason = (entry - tp) / PIP - cost, "TP"
                    break
            # honest BE: the modify only succeeds once price is back at/through
            # entry (MT5 rejects SL-above-market for a long, 10016). Arm at the
            # END of the touching bar so no same-bar scratch is fabricated.
            if be12 in ("honest", "cut") and in_be and not be_armed:
                if (direction == "LONG" and float(b["high"]) >= entry) or \
                   (direction == "SHORT" and float(b["low"]) <= entry):
                    be_armed = True
        if pnl is None:
            last_c = float(after.iloc[-1]["close"]) if len(after) else entry
            raw = (last_c - entry) if direction == "LONG" else (entry - last_c)
            pnl, reason = raw / PIP - cost, "EOD"

        trades.append(dict(date=D, year=D.year, dir=direction, pnl=pnl,
                           risk=risk_p + cost, reason=reason,
                           blocked=(bl or bs), uw=bool(underwater_at_be)))
    return trades, blocked


# ─── reporting ───────────────────────────────────────────────────────────────
def stats(trades, year_min=None, year_eq=None, before=None, since=None):
    t = trades
    if year_min is not None:
        t = [x for x in t if x["year"] >= year_min]
    if year_eq is not None:
        t = [x for x in t if x["year"] == year_eq]
    if before is not None:
        t = [x for x in t if x["date"] < before]
    if since is not None:
        t = [x for x in t if x["date"] >= since]
    if len(t) < 5:
        return None
    R = np.array([x["pnl"] / x["risk"] for x in t])
    gp = R[R > 0].sum()
    gl = abs(R[R <= 0].sum()) or 1e-9
    eq = np.cumsum(R)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return dict(N=len(R), WR=(R > 0).mean() * 100, PF=gp / gl, avgR=R.mean(),
                totR=R.sum(), ddR=dd)


def fmt(s, label):
    if s is None:
        return f"{label:<22} (too few trades)"
    return (f"{label:<22} N={s['N']:>4} WR={s['WR']:>3.0f}% PF={s['PF']:>5.2f} "
            f"avgR={s['avgR']:>+6.3f} totR={s['totR']:>+7.1f} ddR={s['ddR']:>5.1f}")


def verdict(trades, label):
    """Judged on the FLOORED-spread trade list. See pass bar in the docstring."""
    s23 = stats(trades, year_min=2023)
    tr = stats(trades, before=SPLIT)
    te = stats(trades, since=SPLIT)
    yr_ok, yr_detail = True, []
    for y in FULL_YEARS:
        sy = stats(trades, year_eq=y)
        if sy is None or sy["avgR"] <= 0:
            yr_ok = False
        val = "--" if sy is None else f"{sy['avgR']:+.2f}"
        yr_detail.append(f"{y}:{val}")
    print(fmt(stats(trades), "    ALL"))
    print(fmt(s23, "    2023+"))
    print(fmt(tr, "    train<2025"))
    print(fmt(te, "    test 2025+"))
    print(f"    per-year avgR: {'  '.join(yr_detail)}")
    c1 = s23 is not None and s23["PF"] >= BAR_PF23
    c2 = yr_ok
    c3 = (tr is not None and tr["avgR"] > 0 and te is not None and te["avgR"] > 0)
    c4 = s23 is not None and s23["N"] >= BAR_MIN_N
    ok = c1 and c2 and c3 and c4
    print(f"    -> {label}: PF2023+>={BAR_PF23}:{'Y' if c1 else 'N'} "
          f"yearly+:{'Y' if c2 else 'N'} traintest+:{'Y' if c3 else 'N'} "
          f"N>={BAR_MIN_N}:{'Y' if c4 else 'N'} => {'PASS' if ok else 'FAIL'}")
    return ok


# ═════════════════════════ ASB screen ═════════════════════════
print("=" * 92)
print("ASB PAIR-EXTENSION SCREEN — honest fills (arm-check + gap-fill + real BE)")
print(f"pass bar: 2023+ PF>={BAR_PF23} on floored spread, yearly avgR>0, "
      f"train/test avgR>0, N>={BAR_MIN_N}")
print("=" * 92)

data, adr_med = {}, {}
for sym in ASB_PAIRS:
    m15, h1 = load(sym)
    if m15 is None:
        print(f"{sym}: insufficient M15 data — skipped")
        continue
    data[sym] = (m15, h1)
    daily = m15.groupby("bdate").agg(hi=("high", "max"), lo=("low", "min"))
    adr_med[sym] = float(((daily["hi"] - daily["lo"]) / pip_of(sym)).median())

assert INCUMBENT in data, "incumbent GBPJPY failed to load — cannot verify harness"

results, sanity_report = {}, {}
for sym in ASB_PAIRS:
    if sym not in data:
        continue
    m15, h1 = data[sym]
    pip = pip_of(sym)
    vf = adr_med[sym] / adr_med[INCUMBENT]
    cfg = dict(pip=pip, min_buf=MIN_BUF_BASE * vf, trend_thr=TREND_THR_BASE * vf,
               sp_floor=SP_FLOOR_BASE * vf, comm=comm_of(sym, pip))
    med_sp = float(m15["spread"].median()) / 10.0
    tag = "  <-- LIVE INCUMBENT (harness sanity row)" if sym == INCUMBENT else ""
    print(f"\n{'-' * 92}")
    print(f"{sym}: med ADR {adr_med[sym]:.0f}p, vol-scale x{vf:.2f} -> "
          f"min_buf {cfg['min_buf']:.1f}p, trend_thr {cfg['trend_thr']:.0f}p")
    print(f"  costs: comm {cfg['comm']:.2f}p, recorded median spread {med_sp:.2f}p, "
          f"floored to {cfg['sp_floor']:.2f}p{tag}")
    print(f"{'-' * 92}")

    # The contaminated model, printed ONLY as the contrast that shows the size
    # of the fiction. Never judged on.
    naive, _ = simulate(sym, m15, h1, cfg, "naive", False, False)
    s_naive = stats(naive, year_min=2023)
    honest, blk = simulate(sym, m15, h1, cfg, "honest", True, True)
    s_honest = stats(honest, year_min=2023)
    floored, _ = simulate(sym, m15, h1, cfg, "honest", True, True, sp_floor=True)
    s_floored = stats(floored, year_min=2023)
    cut, _ = simulate(sym, m15, h1, cfg, "cut", True, True, sp_floor=True)

    def pf(s):
        return "n/a" if s is None else f"PF={s['PF']:.2f} (N={s['N']})"

    print(f"  {'[VOID] old screen model':<30} 2023+ {pf(s_naive)}")
    print(f"  {'honest, recorded spread':<30} 2023+ {pf(s_honest)}")
    print(f"  {'honest, floored spread':<30} 2023+ {pf(s_floored)}")
    if s_naive and s_floored:
        print(f"  fiction inflation factor: x{s_naive['PF'] / s_floored['PF']:.2f}")
    print(f"  un-placeable legs at 07:00: {blk['days']} days "
          f"(long {blk['long']}, short {blk['short']})")
    be_ex = [x for x in floored if x["reason"] == "BE"]
    print(f"  real BE exits: {len(be_ex)}/{len(floored)}")

    if sym == INCUMBENT:
        sanity_report[("honest", "FULL")] = stats(honest)
        sanity_report[("honest", "2023+")] = s_honest
        sanity_report[("floored", "FULL")] = stats(floored)
        sanity_report[("floored", "2023+")] = s_floored

    # A pair whose M15 history doesn't span the evaluation window can't be
    # judged against a bar that requires per-year and train/test legs — it would
    # read as FAIL when the truth is "no data". AUDJPY hit this (history starts
    # 2025), so say so instead of scoring it.
    covered = {y for y in FULL_YEARS if stats(floored, year_eq=y) is not None}
    if len(covered) < len(FULL_YEARS):
        missing = sorted(set(FULL_YEARS) - covered)
        print(f"\n  INSUFFICIENT HISTORY — no trades in {missing}; "
              f"M15 starts {m15['bt'].iloc[0].date()}. Not scored.")
        results[sym] = None
        continue

    print("\n  VERDICT (floored spread — the conservative column):")
    passed = verdict(floored, f"ASB/{sym}")
    s_cut = stats(cut, year_min=2023)
    if s_cut:
        print(f"    [FYI only, NOT part of the bar] BE12-as-cut variant 2023+ "
              f"PF={s_cut['PF']:.2f} — unvalidated, found on this same data")
    results[sym] = passed

# ─── harness sanity: abort loudly if the incumbent drifted ───
print("\n" + "=" * 92)
print("HARNESS SANITY CHECK — incumbent must reproduce scripts/asb_fill_audit.py")
print("=" * 92)
bad = False
for col, period, want_pf, want_n in SANITY:
    s = sanity_report.get((col, period))
    got_pf = float("nan") if s is None else s["PF"]
    got_n = -1 if s is None else s["N"]
    ok = abs(got_pf - want_pf) <= SANITY_TOL and got_n == want_n
    bad |= not ok
    print(f"  GBPJPY {col:<8} {period:<6} expected PF {want_pf:.2f} N={want_n:<4} "
          f"got PF {got_pf:.2f} N={got_n:<4} {'OK' if ok else '*** MISMATCH ***'}")
if bad:
    print("\n!! Harness does NOT reproduce the audited incumbent. Every result")
    print("!! above is void. Do not act on this run. Fix the port first.")
    mt5.shutdown()
    sys.exit(1)
print("  harness verified — candidate results above are trustworthy")

print("\n" + "=" * 92)
print("SUMMARY")
print("=" * 92)
for sym, passed in results.items():
    role = " (incumbent)" if sym == INCUMBENT else ""
    tag = "NOT SCORED (insufficient history)" if passed is None else (
        "PASS" if passed else "FAIL")
    print(f"  ASB/{sym}{role}: {tag}")


# ═════════════════════════ LONDON_BO screen ═════════════════════════
# LONDON_BO was RETIRED 2026-07-28 ("do not rebuild" — CLAUDE.md). Its screen is
# kept only so this file stays a complete record, and is disabled by default.
# The fill model below has been corrected the same way as ASB, but note LBO's
# live exposure was strictly WORSE than ASB's: it fired a single pending stop,
# so an un-placeable leg lost the whole trade, where ASB's OCO bracket only
# loses one side. Do not re-enable without a new hypothesis.
if RUN_LBO:
    LBO_PAIRS = ["GBPUSD", "EURUSD", "GBPJPY", "EURGBP", "USDJPY"]
    BAND_LO, BAND_HI = 10.0, 22.0
    DAYS = (0, 1)
    print("\n" + "=" * 92)
    print("LONDON_BO SCREEN — RETIRED STRATEGY, reference only")
    print("=" * 92)
    for sym in LBO_PAIRS:
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
        if rates is None or len(rates) < 10000:
            print(f"{sym}: insufficient H1 data")
            continue
        pip = pip_of(sym)
        bars = []
        for r in rates:
            t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)
            off = eu_dst_offset(t_broker - timedelta(hours=3))
            t_utc = t_broker - timedelta(hours=off)
            bars.append({"bh": t_broker.hour, "uh": t_utc.hour, "udate": t_utc.date(),
                         "uwd": t_utc.weekday(), "op": r[1], "hi": r[2], "lo": r[3],
                         "cl": r[4], "sp": r[6] if len(r) > 6 else 0})
        sess = {}
        for b in bars:
            if b["uwd"] >= 5:
                continue
            sess.setdefault(b["udate"], {"bars": [], "wd": b["uwd"]})["bars"].append(b)
        rngs = []
        for d, s in sess.items():
            if s["wd"] not in DAYS:
                continue
            asian = [b for b in s["bars"] if b["uh"] < 7 and b["bh"] < 7]
            if len(asian) >= 3:
                rngs.append((max(b["hi"] for b in asian) -
                             min(b["lo"] for b in asian)) / pip)
        med_rng = float(np.median(rngs)) if rngs else 0.0
        print(f"\n--- {sym}: med asian range {med_rng:.0f}p (retired; see CLAUDE.md) ---")

mt5.shutdown()
