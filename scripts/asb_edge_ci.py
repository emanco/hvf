"""Confidence interval on ASB/GBPJPY's edge -- is there anything to size? (VPS, read-only)

Motivation: ASB/GBPJPY survived the 2026-07-28 fill audit at PF 1.28 (floored
spread, 2023+), which reads like a thin-but-real edge. PF is a point estimate
and hides its own uncertainty. This asks the question PF cannot answer: given
N=109, is the edge distinguishable from zero, and how many trades would it take?

Method
  - Reuses `asb_fill_audit.py::simulate` VERBATIM (this file is that file's
    first 256 lines plus the analysis below), so no fill-model can drift.
  - Pins row E 2023+ on PF *and* N in BOTH cost columns (1.36/109 recorded,
    1.28/109 floored) and aborts on drift -- the incumbent-sanity-gate pattern.
  - Bootstrap (20k resamples, seeded) CIs on avgR and PF; one-sample t on avgR;
    power via N = 7.85 * sd^2 / avgR^2 for 80% power at alpha=0.05.
  - Per-year CIs, and a bootstrap CI on the 2023-24 vs 2025+ DIFFERENCE, to
    test the "edge decayed" story against the "one noisy year" story.

Headline result 2026-07-29 (floored spread, honest BE12, 2023+, N=109):
  avgR +0.055, sd 0.598, SE 0.057, 95% CI [-0.056, +0.166]; PF 1.28 CI
  [0.78, 2.17]; P(true edge <= 0) ~ 17%. 80% power needs 923 trades = 26 years
  at 2.6 fills/mo. => the edge is UNPROVABLE live, not proven and not dead.
  Decay story unsupported: 2026 recovered to PF 2.04 / avgR +0.116, and the
  2023-24 vs 2025+ difference CI [-0.355, +0.094] straddles zero.

Read-only. Nothing is deployed or changed by this script.
Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -u -" < scripts/asb_edge_ci.py
"""
import os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

# mirror config.ASIAN_SESSION_BREAKOUT exactly (deploy == audit)
SYMS = {
    "GBPJPY": dict(pip=0.01,   min_buf=2.0, trend_thr=30.0, comm=1.00, sp_floor=1.5),
    "USDJPY": dict(pip=0.01,   min_buf=1.6, trend_thr=24.0, comm=1.05, sp_floor=0.8),
    "EURUSD": dict(pip=0.0001, min_buf=0.9, trend_thr=14.0, comm=0.70, sp_floor=0.6),
}
MIN_PCT, MAX_PCT = 0.4, 1.0
BUF_PCT = 0.10
TP_MULT = 1.0
SKIP_WD = (4, 5, 6)          # true-UTC Fri/Sat/Sun
BE_HOUR = 12                 # true UTC, deployed 2026-07-15
EOD_HOUR = 20                # true UTC

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load(sym):
    m15 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 99000))
    h1 = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 99000))
    for df in (m15, h1):
        df["bt"] = pd.to_datetime(df["time"], unit="s")   # broker-labelled
    m15["bdate"] = m15["bt"].dt.date
    m15["bh"] = m15["bt"].dt.hour
    h1 = h1.sort_values("bt").reset_index(drop=True)
    return m15, h1


def simulate(sym, m15, h1, be12, arm_check, gap_fill, sp_floor=False):
    c = SYMS[sym]
    PIP = c["pip"]
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
        buf = max(c["min_buf"], BUF_PCT * rng_p)
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
        if diff_p > c["trend_thr"]:
            place_short = False
        elif diff_p < -c["trend_thr"]:
            place_long = False

        win = g[(g["bh"] >= 7 + off) & (g["bh"] < 11 + off)]
        if win.empty:
            continue
        win = win.reset_index(drop=True)

        # --- arm-check: could the pending stop legally be placed at 07:00? ---
        ref = float(win.iloc[0]["open"])
        bl = bs = False
        if ref >= long_stop:
            bl = True
        if ref <= short_stop:
            bs = True
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
            sp = max(sp, c["sp_floor"])
        cost = sp + c["comm"]

        if direction == "BOTH":
            trades.append(dict(date=D, year=D.year, dir=direction,
                               pnl=-risk_p - cost, risk=risk_p + cost,
                               reason="SPAN_SL", blocked=(bl or bs)))
            continue

        if direction == "LONG":
            entry = max(long_stop, float(eb["open"])) if gap_fill and float(eb["open"]) > long_stop else long_stop
            sl, tp = short_stop, long_stop + rng_p * TP_MULT * PIP
        else:
            entry = min(short_stop, float(eb["open"])) if gap_fill and float(eb["open"]) < short_stop else short_stop
            sl, tp = long_stop, short_stop - rng_p * TP_MULT * PIP

        after = g[(g["bt"] >= eb["bt"]) & (g["bh"] < EOD_HOUR + off)].reset_index(drop=True)
        pnl = reason = None
        be_armed = False
        underwater_at_be = None
        for j in range(len(after)):
            b = after.iloc[j]
            in_be = b["bh"] >= BE_HOUR + off
            if in_be and underwater_at_be is None:
                # position underwater the moment BE12 first fires?
                underwater_at_be = (float(b["open"]) < entry if direction == "LONG"
                                    else float(b["open"]) > entry)
            if be12 == "cut" and in_be and underwater_at_be and not be_armed:
                # honest deployable version of BE12's intent: an SL through the
                # market is rejected, but a market CLOSE always fills. Cut the
                # fader at the 12:00 price (not at entry, which is the fiction).
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
            # end of the touching bar so no same-bar scratch is fabricated.
            if be12 in ("honest", "cut") and in_be and not be_armed:
                if (direction == "LONG" and float(b["high"]) >= entry) or \
                   (direction == "SHORT" and float(b["low"]) <= entry):
                    be_armed = True
        if pnl is None:
            last_c = float(after.iloc[-1]["close"]) if len(after) else entry
            raw = (last_c - entry) if direction == "LONG" else (entry - last_c)
            pnl, reason = raw / PIP - cost, "EOD"

        trades.append(dict(date=D, year=D.year, dir=direction, pnl=pnl,
                           risk=risk_p + cost, reason=reason, blocked=(bl or bs),
                           uw=bool(underwater_at_be)))
    return trades, blocked


# =====================================================================
# CONFIDENCE INTERVAL ON ASB/GBPJPY's EDGE
# Question: does 2023+ support ANY edge, and is the 2025 decline
# distinguishable from noise? Uses the audited simulate() unchanged.
# =====================================================================
SYM = "GBPJPY"
BOOT = 20000
RNG = np.random.default_rng(20260729)

# pinned from CLAUDE.md / asb_fill_audit.py row E, 2023+
PINS = {("rec", "E"): (1.36, 109), ("flr", "E"): (1.28, 109)}

def Rser(tr, since=None):
    return np.array([x["pnl"] / x["risk"] for x in tr
                     if since is None or x["year"] >= since])

def pf(R):
    gp = R[R > 0].sum(); gl = abs(R[R <= 0].sum()) or 1e-9
    return gp / gl

def boot_ci(R, fn, n=BOOT, lo=2.5, hi=97.5):
    idx = RNG.integers(0, len(R), size=(n, len(R)))
    vals = np.array([fn(R[i]) for i in idx])
    return np.percentile(vals, lo), np.percentile(vals, hi), vals

def norm_sf(z):
    import math as _m; return 0.5 * _m.erfc(z / np.sqrt(2))

m15, h1 = load(SYM)
print("=" * 78)
print("ASB / %s  --  is there an edge to size at all?" % SYM)
print("=" * 78)

series = {}
for tag, floor in (("rec", False), ("flr", True)):
    tr, _ = simulate(SYM, m15, h1, "honest", True, True, sp_floor=floor)
    series[(tag, "E")] = tr
    trG, _ = simulate(SYM, m15, h1, None, True, True, sp_floor=floor)
    series[(tag, "G")] = trG

print("\nSANITY PINS (row E, 2023+, must match the audit)")
for k, (epf, en) in PINS.items():
    R = Rser(series[k], 2023)
    got_pf, got_n = pf(R), len(R)
    ok = abs(got_pf - epf) <= 0.02 and got_n == en
    print("  %-4s PF %.2f (exp %.2f)  N %d (exp %d)   %s"
          % (k[0], got_pf, epf, got_n, en, "ok" if ok else "*** DRIFT ***"))
    if not ok:
        print("  aborting: simulator does not reproduce the audit"); raise SystemExit(1)

for tag, lbl in (("flr", "FLOORED spread (the decision column)"),
                 ("rec", "recorded spread")):
    for row, rname in (("E", "honest BE12"), ("G", "no BE")):
        R = Rser(series[(tag, row)], 2023)
        n = len(R); mu = R.mean(); sd = R.std(ddof=1); se = sd / np.sqrt(n)
        t = mu / se
        p1 = norm_sf(t) if t > 0 else 1 - norm_sf(-t)
        lo, hi, dist = boot_ci(R, lambda x: x.mean())
        plo, phi, _ = boot_ci(R, pf)
        p_le0 = float((dist <= 0).mean())
        print("\n" + "-" * 78)
        print("%s | row %s (%s) | 2023+" % (lbl, row, rname))
        print("-" * 78)
        print("  N=%d  PF=%.2f  WR=%.0f%%  avgR=%+.4f  sd(R)=%.3f  SE=%.4f"
              % (n, pf(R), (R > 0).mean() * 100, mu, sd, se))
        print("  t = %+.2f   one-sided p(edge<=0) = %.3f" % (t, p1))
        print("  bootstrap 95%% CI  avgR [%+.4f, %+.4f]   PF [%.2f, %.2f]"
              % (lo, hi, plo, phi))
        print("  P(true avgR <= 0) from bootstrap = %.1f%%" % (p_le0 * 100))
        need = 7.85 * sd ** 2 / mu ** 2 if mu != 0 else float("inf")
        print("  N needed for 80%% power at this effect size: %s trades (have %d)"
              % ("%.0f" % need if np.isfinite(need) else "inf", n))
        if np.isfinite(need):
            print("     -> at 2.6 fills/mo that is %.0f years" % ((need - n) / 2.6 / 12))

# ---- per-year, and is the 2025 decline real? ----
tr = series[("flr", "E")]
print("\n" + "=" * 78)
print("PER-YEAR (floored spread, row E) -- with bootstrap CIs")
print("=" * 78)
for y in sorted({x["year"] for x in tr if x["year"] >= 2023}):
    R = np.array([x["pnl"] / x["risk"] for x in tr if x["year"] == y])
    if len(R) < 5: continue
    lo, hi, _ = boot_ci(R, lambda x: x.mean())
    print("  %d  N=%3d  PF=%.2f  avgR=%+.3f   95%% CI [%+.3f, %+.3f]"
          % (y, len(R), pf(R), R.mean(), lo, hi))

early = np.array([x["pnl"]/x["risk"] for x in tr if 2023 <= x["year"] <= 2024])
late  = np.array([x["pnl"]/x["risk"] for x in tr if x["year"] >= 2025])
print("\n  2023-24  N=%d avgR %+.3f   |   2025+  N=%d avgR %+.3f   diff %+.3f"
      % (len(early), early.mean(), len(late), late.mean(), late.mean()-early.mean()))
d = np.array([RNG.choice(late, len(late)).mean() - RNG.choice(early, len(early)).mean()
              for _ in range(BOOT)])
print("  bootstrap 95%% CI on the difference: [%+.3f, %+.3f]"
      % (np.percentile(d, 2.5), np.percentile(d, 97.5)))
print("  P(2025+ genuinely worse than 2023-24) = %.1f%%" % ((d < 0).mean() * 100))
print("\n  -> a CI on the difference that straddles 0 means the 'decay' story and")
print("     the 'noisy year' story are BOTH consistent with this data.")
mt5.shutdown()
