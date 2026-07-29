"""Donchian squeeze ablation — is there a tradable residue in the HVF thesis?

BACKGROUND (2026-07-29)
  HVF (Francis Hunt's "high velocity formation") was retired 2026-06-02 because
  the detector found ~zero patterns. But HVF bundles THREE separate claims, and
  only one of them is falsifiable-and-plausible:

    1. volatility compresses, then releases      <- robust (vol clustering)
    2. the wedge geometry predicts the DIRECTION <- no evidence; detector found
                                                    nothing; dropped
    3. the move extends by the pattern's width   <- folklore, and it is a CAP:
                                                    it truncates the fat right
                                                    tail that pays for losers

  Drop (2) by letting the market choose direction, drop (3) by trailing instead
  of projecting, and what remains is: a breakout with a trailing exit, gated on
  pre-breakout volatility COMPRESSION. That is BTC_DONCHIAN plus one filter.
  So the honest test of HVF's residue is not a new strategy — it is an ablation
  on the one simulator in this repo that survived the 2026-07-28 fill audits
  untouched (close-based entry, no SL-modify overlay).

  Prior evidence AGAINST: NR7_BREAKOUT was already a compression filter
  (narrowest range of 7 days). Honest re-backtest killed it — US500 PF 1.22
  full / 0.83 in 2023+, DE40 1.12 / 0.91 (scripts/nr7_honest_bt.py). One
  negative datapoint for compression-gated daily breakouts already exists.

  Prior REDUNDANCY concern: a 55-day Donchian breakout already implicitly
  selects for consolidation — you cannot print a 55-day high without having
  gone sideways first. The filter may be re-measuring what the entry encodes.
  If so, expect near-zero lift and a clean negative result. That is a useful
  answer: it closes the HVF file permanently.

METHOD
  - load/atr/simulate/_cost/stats/sanity_gate are ported from
    scripts/btc_donchian_honest_bt.py via scripts/donchian_universe_screen.py.
    This script does NOT re-derive the fill model (see CLAUDE.md negative
    results: pair_extension_screen.py was contaminated by exactly that).
  - The ONLY logic addition is a squeeze gate on the entry branch.
  - Squeeze is percentile-ranked CAUSALLY — against a trailing window of
    STRICTLY PRIOR values, then shifted one bar. A full-sample quantile would
    be lookahead and would manufacture the result this script exists to test.

TWO BASELINES — read this before comparing anything
  The rank column needs ~ATR_SLOW + RANK_WIN bars of warm-up, so it is NaN for
  the first ~1.5y of history. A filtered cell therefore cannot trade bars the
  unfiltered incumbent can. Comparing them directly would credit/blame the
  filter for a different eligible bar set.
    INCUMBENT (no gate)          -> used ONLY by the sanity gate.
    BASE      (gate at rank<=1.0)-> the honest comparison row: same NaN mask,
                                    same eligible bars, no selectivity.
  Every verdict below is filtered-vs-BASE, never filtered-vs-INCUMBENT.

PRE-COMMITTED BEFORE LOOKING AT ANY RESULT
  - Instruments = the 6 live BTC_DONCHIAN instances only. No universe re-screen.
  - Parameters FIXED at live values (55/20, ATR20 x1.0, 1% risk, entry "close").
  - Metrics (2): atr_ratio = ATR(20)/ATR(100); bandwidth = 20d range / close.
  - Thresholds (3): rank <= 0.20 / 0.33 / 0.50.  6 cells. No others.
  - Cost = "real" (recorded spread floored at the live snapshot + commission),
    the decision column from the universe screen. "stress" shown for context.
  - Train 2017-2021, Test 2022+ — same split the universe screen pre-committed.
  - Judged on POOLED R across the 6 instruments (per-instrument N is too thin
    to carry a verdict; per-instrument rows are printed as diagnostics only).
  - A cell PASSES only if ALL of:
        test  PF   > BASE test  PF
        test  avgR > BASE test  avgR
        train avgR > BASE train avgR
        test  N   >= 30
    i.e. it must beat the unfiltered rule on the HELD-OUT leg and not have been
    negative on train. Beating on one leg only is noise.
  - avgR is mean-driven and NOT robust on crypto/gold (universe screen caveat
    #1: one or two monster trends dominate). medR and PF are printed alongside;
    if PF and avgR disagree, believe PF.

MECHANICAL TRIPWIRE
  Retention (filtered N / BASE N) must land near the nominal threshold. It will
  not match exactly — entries are also blocked by an already-open position, and
  squeeze may genuinely correlate with breakouts — but a 0.33 cell retaining
  90% or 5% means the rank column is broken, not that the filter is weak. Cells
  outside [0.5x, 1.6x] of nominal are flagged SUSPECT and their verdict voided.

DEEP DIVE — why passing the bar above is NOT sufficient (added after the first
run, 2026-07-29, which passed atr_ratio<=0.50 and bandwidth<=0.50 on both cost
columns; every cell beat BASE on PF, which is itself the CLAUDE.md tell that a
whole winning parameter family is usually a mechanical artifact)

  medR is -1.00 in EVERY cell: the median trade is a full stop-out and the
  entire mean is a handful of monster trends. On a distribution like that, a
  selector that keeps 2/3 of trades at random will sometimes keep the good
  tail, so "PF went up" is nearly uninformative on its own. Four checks:

  1. PLACEBO (the decisive one). Re-run each passing cell with the squeeze
     column replaced by uniform noise carrying the SAME NaN mask and the SAME
     acceptance threshold — i.e. a selector with identical selectivity and zero
     information, propagating through the identical occupancy dynamics.
     N_PLACEBO draws, independent per instrument per draw. The empirical
     p-value is the fraction of draws whose pooled TEST-leg PF (and avgR)
     reaches the observed value. Pre-committed: p <= 0.05 on BOTH, or the cell
     is noise. This is the only check that prices in the fat tail correctly.
  2. TAIL ROBUSTNESS. Recompute the test leg with the top 3 and top 5 R trades
     dropped from each set independently. If the filter's lift over BASE does
     not survive dropping 3, it IS those trades.
  3. PER-INSTRUMENT SIGN TEST. How many of the 6 improve vs BASE. Pooled-only
     wins are single-instrument wins wearing a portfolio costume. Pre-committed:
     >= 5 of 6 (exact binomial p=0.109 at 5/6 — weak on its own, which is why
     it is a supporting check, not a gate).
  4. OVERLAP. What fraction of the filtered trades BASE never took. This sizes
     the occupancy confound directly: a filtered set that is NOT a subset of
     BASE is a different trade sequence, not "BASE minus the bad trades", and
     the intuitive reading of the PF lift does not apply.

Usage:
  ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/donchian_squeeze_ablation.py
  Set CALIBRATE=True to re-emit the sanity pins after a deliberate change.
"""
import os
import sys
import time as _time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

# ---------------------------------------------------------------- live params
ENTRY_LB, EXIT_LB, ATR_P, ATR_MULT = 55, 20, 20, 1.0
START_EQ, RISK_PCT = 10000.0, 1.0

# ------------------------------------------------------------ ablation policy
ATR_FAST, ATR_SLOW = 20, 100     # atr_ratio = ATR(20)/ATR(100)
BW_LB = 20                       # bandwidth = 20d high-low range / close
RANK_WIN = 252                   # trailing bars the squeeze is ranked against
METRICS = ("atr_ratio", "bandwidth")
THRESHOLDS = (0.20, 0.33, 0.50)

SCORE_FROM_YEAR = 2017
TRAIN_YEARS = (2017, 2021)
TEST_FROM_YEAR = 2022
BAR_MIN_TEST_N = 30
RETENTION_LO, RETENTION_HI = 0.5, 1.6   # multiples of nominal threshold

# ------------------------------------------------------- deep-dive policy
# Pre-committed before the first placebo run. p is one-sided (a filter that is
# WORSE than noise is not interesting) and applies to the TEST leg only.
N_PLACEBO = 300
PLACEBO_SEED = 20260729
PLACEBO_ALPHA = 0.05
DROP_TOP = (3, 5)        # tail-robustness: R trades removed from each set
SIGN_TEST_BAR = 5        # of 6 instruments must improve

# the 6 live BTC_DONCHIAN instances (config.BTC_DONCHIAN instances, 2026-07-29)
INSTANCES = {
    "BTCUSD": "crypto", "ETHUSD": "crypto",
    "JP225": "index", "US500": "index", "USTEC": "index",
    "XAUUSD": "metal",
}

# IC raw-spread account: commission on FX/metals only ($3.50/side/100k).
COMMISSION_RT_USD_PER_LOT = {"metal": 7.0, "index": 0.0, "crypto": 0.0}

FLAT_COST = {"BTCUSD": 12.0, "ETHUSD": 5.0}   # incumbent's original assumption
DPP_INCUMBENT = 1.0                            # incumbent's hardcoded DPP

# Incumbent pins, frozen window — identical to donchian_universe_screen.py.
# If these drift, the port is wrong and every number below is void.
CALIBRATE = False
SANITY_CUTOFF = pd.Timestamp("2026-07-01")
SANITY_PF_TOL = 0.02
SANITY = {
    ('BTCUSD', 'orig(close+flat)', 'FULL'):    (4.21, 73),
    ('BTCUSD', 'orig(close+flat)', '2023+'):   (2.59, 26),
    ('BTCUSD', 'HONEST(lag+spread)', 'FULL'):  (3.60, 58),
    ('BTCUSD', 'HONEST(lag+spread)', '2023+'): (1.76, 29),
    ('ETHUSD', 'orig(close+flat)', 'FULL'):    (3.22, 61),
    ('ETHUSD', 'orig(close+flat)', '2023+'):   (4.75, 20),
    ('ETHUSD', 'HONEST(lag+spread)', 'FULL'):  (2.72, 41),
    ('ETHUSD', 'HONEST(lag+spread)', '2023+'): (3.92, 21),
}

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


# ================================================================== PORTED ===
# Behaviourally equivalent to scripts/btc_donchian_honest_bt.py (via
# donchian_universe_screen.py). Do not "improve" it in place — the sanity gate
# is the only thing standing between an edit here and a fabricated result.

def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load(sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000)
    if rates is None or len(rates) < 2000:
        return None
    df = pd.DataFrame(rates)
    df["tb"] = pd.to_datetime(df["time"], unit="s")           # broker clock
    off = df["tb"].apply(lambda t: eu_dst_offset(
        (t - pd.Timedelta(hours=3)).tz_localize("UTC")))
    df["tu"] = df["tb"] - pd.to_timedelta(off, unit="h")       # true UTC
    point = mt5.symbol_info(sym).point
    df["spread_price"] = df["spread"] * point
    df = df.iloc[:-1]
    df["bdate"] = df["tb"].dt.date
    d1 = df.groupby("bdate").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last")).reset_index()
    utc0 = df[df["tu"].dt.hour == 0].groupby("bdate").agg(
        lag_open=("open", "first"), lag_spread=("spread_price", "first"))
    d1 = d1.merge(utc0, on="bdate", how="left")
    close_sp = df.groupby("bdate").agg(close_spread=("spread_price", "last"))
    d1 = d1.merge(close_sp, on="bdate", how="left")
    return d1


def atr(d1, period=ATR_P):
    h, l, c = d1["high"], d1["low"], d1["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _cost(spec, cost_mode, sp):
    if cost_mode == "spread":
        return sp if not pd.isna(sp) else spec["flat"]
    if cost_mode == "flat":
        return spec["flat"]
    base = max(0.0 if pd.isna(sp) else sp, spec["floor"]) + spec["comm"]
    return base * (2.0 if cost_mode == "stress" else 1.0)


def simulate(spec, d1, entry_mode, cost_mode, since_year=None,
             until_year=None, cutoff=None, squeeze_col=None, squeeze_max=1.0):
    """Ported simulator + ONE addition: the squeeze gate.

    squeeze_col=None reproduces the incumbent exactly (sanity gate relies on
    this). With a column set, a breakout signal is taken only when that bar's
    causally-ranked squeeze is <= squeeze_max; NaN ranks are never tradable.
    The gate sits on the SIGNAL branch only — it never touches exits, so an
    already-open trade is managed identically in every cell.
    """
    df = d1.copy()
    if cutoff is not None:
        df = df[pd.to_datetime(df["bdate"]) < cutoff].reset_index(drop=True)
    df["entry_high"] = df["high"].rolling(ENTRY_LB).max().shift(1)
    df["entry_low"] = df["low"].rolling(ENTRY_LB).min().shift(1)
    df["exit_high"] = df["high"].rolling(EXIT_LB).max().shift(1)
    df["exit_low"] = df["low"].rolling(EXIT_LB).min().shift(1)
    df["atr"] = atr(df).shift(1)
    rows = df.to_dict("records")
    trades = []
    recs = []
    equity = START_EQ
    open_t = None
    pending_entry = None
    for i, row in enumerate(rows):
        if since_year and row["bdate"].year < since_year:
            continue
        if until_year and row["bdate"].year > until_year:
            continue
        if pd.isna(row["entry_high"]) or pd.isna(row["atr"]):
            continue

        if pending_entry is not None and open_t is None:
            direction, sig_atr = pending_entry
            ep = row.get("lag_open")
            sp = row.get("lag_spread")
            if ep is None or pd.isna(ep):
                pending_entry = None
            else:
                cost = _cost(spec, cost_mode, sp)
                stop = ep - ATR_MULT * sig_atr if direction == "L" else ep + ATR_MULT * sig_atr
                open_t = {"dir": direction, "ep": ep, "stop": stop,
                          "isd": abs(ep - stop), "cost": cost,
                          "in": row["bdate"]}
                pending_entry = None

        if open_t is not None:
            if open_t["dir"] == "L":
                if row["low"] <= open_t["stop"]:
                    xp = min(row["open"], open_t["stop"])
                    pnl_pts = (xp - open_t["ep"]) - open_t["cost"]
                else:
                    if not pd.isna(row["exit_low"]):
                        open_t["stop"] = max(open_t["stop"], row["exit_low"])
                    pnl_pts = None
            else:
                if row["high"] >= open_t["stop"]:
                    xp = max(row["open"], open_t["stop"])
                    pnl_pts = (open_t["ep"] - xp) - open_t["cost"]
                else:
                    if not pd.isna(row["exit_high"]):
                        open_t["stop"] = min(open_t["stop"], row["exit_high"])
                    pnl_pts = None
            if pnl_pts is not None:
                risk_usd = equity * RISK_PCT / 100.0
                lots = risk_usd / max(open_t["isd"] * spec["dpp"], 0.01)
                lots = max(min(round(lots, 2), 100.0), 0.01)
                usd = pnl_pts * lots * spec["dpp"]
                equity += usd
                trades.append(usd)
                recs.append({"sym": spec["sym"], "dir": open_t["dir"],
                             "in": open_t["in"], "out": row["bdate"],
                             "R": pnl_pts / open_t["isd"] if open_t["isd"] else 0.0,
                             "usd": usd})
                open_t = None

        if open_t is None and pending_entry is None:
            direction = None
            if row["close"] > row["entry_high"]:
                direction = "L"
            elif row["close"] < row["entry_low"]:
                direction = "S"
            # --- the ONLY logic addition to the ported simulator ---
            if direction and squeeze_col is not None:
                z = row.get(squeeze_col)
                if z is None or pd.isna(z) or z > squeeze_max:
                    direction = None
            # -------------------------------------------------------
            if direction:
                if entry_mode == "lag":
                    pending_entry = (direction, row["atr"])
                else:
                    ep = row["close"]
                    sp = row.get("close_spread")
                    cost = _cost(spec, cost_mode, sp)
                    stop = ep - ATR_MULT * row["atr"] if direction == "L" else ep + ATR_MULT * row["atr"]
                    open_t = {"dir": direction, "ep": ep, "stop": stop,
                              "isd": abs(ep - stop), "cost": cost,
                              "in": row["bdate"]}
    return np.array(trades), equity, recs

# ============================================================== END PORTED ===


def rolling_pct_rank(s, window):
    """Fraction of the STRICTLY PRIOR `window` values below the current one.

    Causal by construction: the slice is v[i-window:i], which excludes v[i].
    A full-sample `.quantile()` here would be lookahead — the compressed bars
    would be labelled using vol that had not happened yet, which is precisely
    how a squeeze filter fakes an edge.
    """
    v = s.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    for i in range(window, len(v)):
        cur = v[i]
        if np.isnan(cur):
            continue
        w = v[i - window:i]
        n = np.count_nonzero(~np.isnan(w))
        if n < window // 2:
            continue
        out[i] = np.count_nonzero(w < cur) / n
    return pd.Series(out, index=s.index)


def add_squeeze(d1):
    """Attach causally-ranked squeeze columns, shifted to the prior close.

    Both metrics measure PRE-breakout compression: they are ranked on the raw
    series then `.shift(1)`, matching the incumbent's convention for `atr` /
    `entry_high` so the signal bar only ever sees data through yesterday.
    """
    df = d1.copy()
    fast = atr(df, ATR_FAST)
    slow = atr(df, ATR_SLOW)
    df["atr_ratio"] = rolling_pct_rank(
        (fast / slow.replace(0, np.nan)), RANK_WIN).shift(1)
    rng = (df["high"].rolling(BW_LB).max() - df["low"].rolling(BW_LB).min())
    df["bandwidth"] = rolling_pct_rank(
        (rng / df["close"].replace(0, np.nan)), RANK_WIN).shift(1)
    return df


def stats(trades, recs, years=1.0):
    if len(trades) == 0:
        return None
    w = (trades > 0).sum()
    gp = trades[trades > 0].sum()
    gl = abs(trades[trades <= 0].sum())
    eq = np.concatenate([[START_EQ], START_EQ + np.cumsum(trades)])
    dd = np.maximum.accumulate(eq) - eq
    ddpct = (dd.max() / np.maximum.accumulate(eq)[dd.argmax()] * 100
             if dd.max() > 0 else 0.0)
    return {"n": len(trades), "wr": w / len(trades) * 100,
            "pf": (gp / gl) if gl > 0 else float("inf"),
            "avgR": float(np.mean([r["R"] for r in recs])) if recs else 0.0,
            "dd": ddpct}


def pooled(recs):
    """Stats on pooled R across instruments — the judged number.

    PF is computed on R (risk-normalised), not USD, so a single instrument's
    dollar scale cannot dominate the pool.
    """
    if not recs:
        return None
    R = np.array([r["R"] for r in recs])
    wins, losses = R[R > 0].sum(), abs(R[R <= 0].sum())
    return {"n": len(R), "wr": float((R > 0).mean() * 100),
            "pf": float(wins / losses) if losses > 0 else float("inf"),
            "avgR": float(R.mean()), "medR": float(np.median(R))}


def build_spec(sym, cls):
    info = mt5.symbol_info(sym)
    if info is None:
        return None
    if not info.visible:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
    if not info.trade_tick_size:
        return None
    dpp = info.trade_tick_value / info.trade_tick_size
    if dpp <= 0:
        return None
    return {"sym": sym, "cls": cls, "dpp": dpp,
            "comm": COMMISSION_RT_USD_PER_LOT[cls] / dpp,
            "floor": info.spread * info.point,
            "flat": FLAT_COST.get(sym, 0.0)}


def sanity_gate():
    """Reproduce btc_donchian_honest_bt.py on a frozen window, or die."""
    print("=" * 78)
    print("INCUMBENT SANITY GATE  (frozen window: bdate < %s, gate OFF)"
          % SANITY_CUTOFF.date())
    print("=" * 78)
    emitted, failures = {}, []
    for sym in ("BTCUSD", "ETHUSD"):
        d1 = load(sym)
        if d1 is None:
            print("  %s: NO DATA — cannot verify" % sym)
            sys.exit(1)
        spec = {"sym": sym, "dpp": DPP_INCUMBENT, "flat": FLAT_COST[sym],
                "comm": 0.0, "floor": 0.0}
        for mode_label, em, cm in (("orig(close+flat)", "close", "flat"),
                                   ("HONEST(lag+spread)", "lag", "spread")):
            for per_label, sy in (("FULL", None), ("2023+", 2023)):
                tr, _eq, rc = simulate(spec, d1, em, cm, since_year=sy,
                                       cutoff=SANITY_CUTOFF)
                s = stats(tr, rc)
                key = (sym, mode_label, per_label)
                got = (round(s["pf"], 2), s["n"])
                emitted[key] = got
                if CALIBRATE:
                    print("    %-7s %-19s %-6s PF=%5.2f N=%3d"
                          % (sym, mode_label, per_label, got[0], got[1]))
                    continue
                exp = SANITY.get(key)
                if exp is None:
                    failures.append("%s %s %s: no pin recorded"
                                    % (sym, mode_label, per_label))
                    continue
                ok = abs(got[0] - exp[0]) <= SANITY_PF_TOL and got[1] == exp[1]
                print("  %-7s %-19s %-6s PF %5.2f (exp %5.2f) N %3d (exp %3d)  %s"
                      % (sym, mode_label, per_label, got[0], exp[0],
                         got[1], exp[1], "ok" if ok else "DRIFT"))
                if not ok:
                    failures.append("%s %s %s: PF %.2f vs %.2f, N %d vs %d"
                                    % (sym, mode_label, per_label,
                                       got[0], exp[0], got[1], exp[1]))
    if CALIBRATE:
        print("\n  SANITY = {")
        for k, v in emitted.items():
            print("      %-42s (%.2f, %d)," % (str(k) + ":", v[0], v[1]))
        print("  }\n  CALIBRATE=True — pins emitted, ablation not run.")
        mt5.shutdown()
        sys.exit(0)
    if failures:
        print("\n  SANITY GATE FAILED — the ported simulator has drifted from")
        print("  btc_donchian_honest_bt.py. Every number below would be void.")
        for f in failures:
            print("    - " + f)
        mt5.shutdown()
        sys.exit(1)
    print("\n  gate passed — simulator reproduces the incumbent.\n")


def legs(spec, dfq, metric, thr, cost_mode):
    """FULL / train / test pooled records for one (metric, threshold) cell."""
    out = {}
    for label, kw in (("full", dict(since_year=SCORE_FROM_YEAR)),
                      ("train", dict(since_year=TRAIN_YEARS[0],
                                     until_year=TRAIN_YEARS[1])),
                      ("test", dict(since_year=TEST_FROM_YEAR))):
        _tr, _eq, rc = simulate(spec, dfq, "close", cost_mode,
                                squeeze_col=metric, squeeze_max=thr, **kw)
        out[label] = rc
    return out


def per_sym_line(per_sym, leg="full"):
    parts = []
    for s, v in per_sym.items():
        st = v[leg] if isinstance(v, dict) and leg in v else v
        parts.append("%s N=0" % s if not st
                     else "%s PF=%.2f/N=%d" % (s, st["pf"], st["n"]))
    return ", ".join(parts)


def run(cost_mode="real"):
    print("=" * 78)
    print("DONCHIAN SQUEEZE ABLATION  %d/%d ATR%dx%.1f  %.0f%% risk  cost=%s"
          % (ENTRY_LB, EXIT_LB, ATR_P, ATR_MULT, RISK_PCT, cost_mode))
    print("6 live instances | rank window %d bars, causal | train %d-%d, test %d+"
          % (RANK_WIN, TRAIN_YEARS[0], TRAIN_YEARS[1], TEST_FROM_YEAR))
    print("BASE = same NaN mask, no selectivity. Verdicts are vs BASE.")
    print("=" * 78)

    data = {}
    for sym, cls in INSTANCES.items():
        spec = build_spec(sym, cls)
        d1 = load(sym) if spec else None
        if spec is None or d1 is None:
            print("  %-8s SKIPPED — no tick specs / insufficient history" % sym)
            continue
        data[sym] = (spec, add_squeeze(d1))
    if not data:
        print("  no instruments loaded.")
        return {}, {}, []

    # cells: (metric, threshold); threshold 1.0 is that metric's BASE row
    results = {}
    for metric in METRICS:
        for thr in (1.0,) + THRESHOLDS:
            agg = {"full": [], "train": [], "test": []}
            per_sym, per_sym_recs = {}, {}
            for sym, (spec, dfq) in data.items():
                lg = legs(spec, dfq, metric, thr, cost_mode)
                per_sym_recs[sym] = lg
                per_sym[sym] = {k: pooled(v) for k, v in lg.items()}
                for k in agg:
                    agg[k].extend(lg[k])
            results[(metric, thr)] = {
                "pool": {k: pooled(v) for k, v in agg.items()},
                "per_sym": per_sym, "recs": agg, "per_sym_recs": per_sym_recs,
            }

    def fmt(s):
        if s is None:
            return "     N=0"
        return ("N=%3d WR=%2.0f%% PF=%5.2f avgR=%+.3f medR=%+.3f"
                % (s["n"], s["wr"], s["pf"], s["avgR"], s["medR"]))

    verdicts = []
    for metric in METRICS:
        base = results[(metric, 1.0)]["pool"]
        print("\n### %s" % metric)
        print("  BASE (rank<=1.00)")
        for leg in ("full", "train", "test"):
            print("      %-6s %s" % (leg, fmt(base[leg])))
        print("      per-instrument (full): %s"
              % per_sym_line(results[(metric, 1.0)]["per_sym"]))

        for thr in THRESHOLDS:
            cell = results[(metric, thr)]
            pool = cell["pool"]
            print("\n  rank<=%.2f" % thr)
            for leg in ("full", "train", "test"):
                print("      %-6s %s" % (leg, fmt(pool[leg])))
            print("      per-instrument (full): %s"
                  % per_sym_line(cell["per_sym"]))

            # mechanical tripwire on retention
            bn = base["full"]["n"] if base["full"] else 0
            fn = pool["full"]["n"] if pool["full"] else 0
            ret = (fn / bn) if bn else 0.0
            suspect = not (RETENTION_LO * thr <= ret <= RETENTION_HI * thr)
            print("      retention %.2f of BASE (nominal %.2f)%s"
                  % (ret, thr, "   <-- SUSPECT, verdict void" if suspect else ""))

            te, tr_, bte, btr = (pool["test"], pool["train"],
                                 base["test"], base["train"])
            if suspect:
                verdict, why = "VOID", "retention outside tripwire band"
            elif te is None or tr_ is None or bte is None or btr is None:
                verdict, why = "VOID", "empty leg"
            elif te["n"] < BAR_MIN_TEST_N:
                verdict, why = "FAIL", "test N=%d < %d" % (te["n"], BAR_MIN_TEST_N)
            else:
                checks = [("test PF", te["pf"] > bte["pf"],
                           "%.2f vs %.2f" % (te["pf"], bte["pf"])),
                          ("test avgR", te["avgR"] > bte["avgR"],
                           "%+.3f vs %+.3f" % (te["avgR"], bte["avgR"])),
                          ("train avgR", tr_["avgR"] > btr["avgR"],
                           "%+.3f vs %+.3f" % (tr_["avgR"], btr["avgR"]))]
                failed = [c for c in checks if not c[1]]
                verdict = "PASS" if not failed else "FAIL"
                why = "; ".join("%s %s" % (c[0], c[2]) for c in (failed or checks))
            print("      VERDICT %-4s  (%s)" % (verdict, why))
            verdicts.append((metric, thr, verdict))

    print("\n" + "=" * 78)
    passers = [(m, t) for m, t, v in verdicts if v == "PASS"]
    print("PASSING CELLS: %s"
          % (", ".join("%s<=%.2f" % (m, t) for m, t in passers)
             if passers else "none"))
    if not passers:
        print("  No squeeze filter improves the held-out leg. On this evidence")
        print("  the HVF compression thesis has no residue beyond what the")
        print("  55-day Donchian entry already captures — consistent with the")
        print("  redundancy concern in the docstring and with NR7's failure.")
    else:
        print("  6 cells were tested. Treat 1-2 passes as a multiple-comparisons")
        print("  candidate, not a result: require the SAME cell to pass on the")
        print("  'stress' cost column and to hold up per-instrument before any")
        print("  deploy conversation. A filter that only works pooled is a")
        print("  filter that works on one instrument.")
    print("=" * 78)
    return data, results, passers


# ================================================================ DEEP DIVE ===

def drop_top(recs, k):
    """Pool after removing the k largest-R trades. Ranked within each set."""
    if len(recs) <= k:
        return None
    return pooled(sorted(recs, key=lambda r: r["R"])[:len(recs) - k])


def binom_sf(k, n, p=0.5):
    """P(X >= k) for X ~ Binomial(n, p). Exact — n is 6."""
    from math import comb
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def placebo(data, results, metric, thr, cost_mode, n_draws=N_PLACEBO):
    """Uninformative selector with the same selectivity and the same NaN mask.

    This is the null the PF lift has to beat. Each draw replaces the squeeze
    rank with U(0,1) — which is exactly what a *causal percentile rank* looks
    like marginally — so the acceptance probability, the warm-up mask and the
    occupancy dynamics are all identical, and the ONLY thing removed is the
    information content. Draws are independent per instrument, matching the
    real filter's independence across books.
    """
    obs = results[(metric, thr)]["pool"]["test"]
    obs_n = obs["n"]
    rng = np.random.default_rng(PLACEBO_SEED)
    masks = {s: dfq[metric].isna().to_numpy() for s, (_sp, dfq) in data.items()}

    pfs, avgs, ns = [], [], []
    t0 = _time.time()
    for d in range(n_draws):
        agg = []
        for sym, (spec, dfq) in data.items():
            u = rng.random(len(dfq))
            u[masks[sym]] = np.nan
            dfq["_placebo"] = u
            _tr, _eq, rc = simulate(spec, dfq, "close", cost_mode,
                                    since_year=TEST_FROM_YEAR,
                                    squeeze_col="_placebo", squeeze_max=thr)
            agg.extend(rc)
        p = pooled(agg)
        if p is None:
            continue
        pfs.append(p["pf"])
        avgs.append(p["avgR"])
        ns.append(p["n"])
        if (d + 1) % 50 == 0:
            print("      ... %d/%d draws (%.0fs)"
                  % (d + 1, n_draws, _time.time() - t0))

    pfs = np.array([x for x in pfs if np.isfinite(x)])
    avgs, ns = np.array(avgs), np.array(ns)
    p_pf = float((pfs >= obs["pf"]).mean())
    p_avg = float((avgs >= obs["avgR"]).mean())
    print("      observed   test PF=%5.2f avgR=%+.3f N=%3d"
          % (obs["pf"], obs["avgR"], obs_n))
    print("      placebo    PF  p50=%5.2f p90=%5.2f p95=%5.2f max=%5.2f"
          % (np.percentile(pfs, 50), np.percentile(pfs, 90),
             np.percentile(pfs, 95), pfs.max()))
    print("      placebo    avgR p50=%+.3f p90=%+.3f p95=%+.3f"
          % (np.percentile(avgs, 50), np.percentile(avgs, 90),
             np.percentile(avgs, 95)))
    print("      placebo    N    mean=%.1f (observed %d) -- if these match, the"
          % (ns.mean(), obs_n))
    print("                      over-retention is occupancy, not information")
    print("      p(PF   >= observed) = %.3f%s"
          % (p_pf, "  <= alpha" if p_pf <= PLACEBO_ALPHA else "   NOT significant"))
    print("      p(avgR >= observed) = %.3f%s"
          % (p_avg, "  <= alpha" if p_avg <= PLACEBO_ALPHA else "   NOT significant"))
    return p_pf, p_avg


def deep_dive(data, results, cells, cost_mode="real"):
    print("\n" + "=" * 78)
    print("DEEP DIVE on passing cells  (cost=%s, %d placebo draws, seed %d)"
          % (cost_mode, N_PLACEBO, PLACEBO_SEED))
    print("Pre-committed: placebo p<=%.2f on BOTH PF and avgR; lift survives"
          % PLACEBO_ALPHA)
    print("dropping the top %d R trades; >=%d of %d instruments improve."
          % (DROP_TOP[0], SIGN_TEST_BAR, len(data)))
    print("=" * 78)

    verdict_lines = []
    for metric, thr in cells:
        cell = results[(metric, thr)]
        base = results[(metric, 1.0)]
        print("\n### %s <= %.2f" % (metric, thr))

        # -- 1. tail robustness -------------------------------------------
        print("  [1] tail robustness (test leg)")
        bt, ct = base["pool"]["test"], cell["pool"]["test"]
        print("      drop  0   BASE PF=%5.2f avgR=%+.3f | CELL PF=%5.2f avgR=%+.3f"
              "  lift %+.2f" % (bt["pf"], bt["avgR"], ct["pf"], ct["avgR"],
                                ct["pf"] - bt["pf"]))
        tail_ok = True
        for k in DROP_TOP:
            b, c = drop_top(base["recs"]["test"], k), drop_top(cell["recs"]["test"], k)
            if b is None or c is None:
                continue
            lift = c["pf"] - b["pf"]
            if k == DROP_TOP[0] and lift <= 0:
                tail_ok = False
            print("      drop %2d   BASE PF=%5.2f avgR=%+.3f | CELL PF=%5.2f "
                  "avgR=%+.3f  lift %+.2f%s"
                  % (k, b["pf"], b["avgR"], c["pf"], c["avgR"], lift,
                     "" if lift > 0 else "   <-- lift gone"))

        # -- 2. per-instrument sign test -----------------------------------
        print("  [2] per-instrument sign test (test leg, PF vs own BASE)")
        wins = 0
        for sym in data:
            b = base["per_sym"][sym]["test"]
            c = cell["per_sym"][sym]["test"]
            if not b or not c:
                print("      %-7s  n/a" % sym)
                continue
            up = c["pf"] > b["pf"]
            wins += int(up)
            print("      %-7s BASE PF=%5.2f/N=%2d -> CELL PF=%5.2f/N=%2d  %s"
                  % (sym, b["pf"], b["n"], c["pf"], c["n"],
                     "up" if up else "DOWN"))
        n_inst = len(data)
        sign_ok = wins >= SIGN_TEST_BAR
        print("      %d/%d improve (need >=%d)   exact binomial p=%.3f"
              % (wins, n_inst, SIGN_TEST_BAR, binom_sf(wins, n_inst)))

        # -- 3. overlap / occupancy confound -------------------------------
        bkeys = {(r["sym"], r["in"]) for r in base["recs"]["test"]}
        ckeys = [(r["sym"], r["in"]) for r in cell["recs"]["test"]]
        novel = sum(1 for k in ckeys if k not in bkeys)
        print("  [3] overlap: %d/%d cell trades (%.0f%%) are entries BASE never"
              " took" % (novel, len(ckeys), 100.0 * novel / max(len(ckeys), 1)))
        print("      (a subset would be 0%% — anything above that means this is a")
        print("       different trade sequence, not 'BASE minus the bad trades')")

        # -- 4. placebo ----------------------------------------------------
        print("  [4] placebo / permutation")
        p_pf, p_avg = placebo(data, results, metric, thr, cost_mode)
        plac_ok = p_pf <= PLACEBO_ALPHA and p_avg <= PLACEBO_ALPHA

        ok = plac_ok and tail_ok and sign_ok
        verdict_lines.append(
            "%s<=%.2f: placebo %s (p=%.3f/%.3f), tail %s, sign %s  =>  %s"
            % (metric, thr, "ok" if plac_ok else "FAIL", p_pf, p_avg,
               "ok" if tail_ok else "FAIL", "ok" if sign_ok else "FAIL",
               "SURVIVES" if ok else "REJECTED"))
        print("  ---> %s" % verdict_lines[-1].split("=>")[-1].strip())

    print("\n" + "=" * 78)
    print("DEEP DIVE SUMMARY")
    for line in verdict_lines:
        print("  " + line)
    print("=" * 78)


if __name__ == "__main__":
    sanity_gate()
    data, results, passers = run("real")
    if passers:
        deep_dive(data, results, passers, "real")
    print("\n--- context only: same cells at 2x cost -------------------------")
    run("stress")
    print("\nNOTE: this is an ABLATION, not a deploy decision. BTC_DONCHIAN is")
    print("unchanged either way; a PASS would only open a train/test discussion.")
    mt5.shutdown()
