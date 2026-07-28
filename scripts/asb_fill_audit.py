"""ASB blind-gap fill audit — does the same fiction that killed LONDON_BO inflate ASB?

Context (2026-07-28). LONDON_BO was retired after its PF 1.63 validation was
shown to fill 62% of trades at the breakout level on days the window already
OPENED through it. ASB has the same structural exposure: the range is captured
at true UTC 07:00 but the bars are broker-labelled, so the range really covers
UTC ~21:00-04:00 -- a ~3h blind gap before the bracket is armed. CLAUDE.md
already concedes the sim "fills already-through-at-07:00 days that live skips
(retcode 10015, slight sim optimism)". LBO is the evidence that "slight" needs
checking, not assuming.

Structural difference from LBO, and the reason this may well come out fine:
ASB arms an OCO *bracket*, not a single order. If price sits above the BUY_STOP
at 07:00 that side is un-placeable -- but the SELL_STOP below is still valid.
LBO had one order and lost the whole trade; ASB loses one leg. So the honest
model here is per-leg, not per-day.

Fill model (both applied; each is a leg-level correction to the incumbent):
  arm-check  at true UTC 07:00 take the open of the first fill-window bar as
             the reference. ref >= long_stop -> BUY_STOP invalid, long leg not
             placed. ref <= short_stop -> SELL_STOP invalid, short leg dropped.
  gap-fill   a bar that OPENS beyond a stop fills at that open, not the stop
             (SL/TP/size still derive from the level, as live does).

Rows:
  A INCUMBENT   scripts/asb_live_geometry_bt.py logic verbatim. Sanity row --
                GBPJPY must reproduce N=183, WR 60%, PF 1.57 (2023+ PF 1.64).
  B +BE12       adds the deployed 2026-07-15 overlay (SL -> entry at UTC 12:00).
                B is what is actually running today.
  C +arm-check  drop legs that could not have been placed.
  D +gap-fill   and fill gaps at the open. == honest deployed behaviour.

Also reported: how often each leg is un-placeable, and -- the load-bearing
diagnostic -- what the incumbent booked on exactly those impossible legs. If
they are its winners, the headline PF is borrowed.

Spread: the incumbent uses the recorded per-bar spread field. That field is
known to median to 0 on some IC symbols (a cost trap), so the median is printed
and a floored-cost variant is run as a sensitivity check.

Read-only.
Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/asb_fill_audit.py
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


def stats(tr, since=None):
    t = [x for x in tr if since is None or x["year"] >= since]
    if not t:
        return "N=0"
    R = np.array([x["pnl"] / x["risk"] for x in t])
    gp = R[R > 0].sum()
    gl = abs(R[R <= 0].sum()) or 1e-9
    eq = np.cumsum(R)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return (f"N={len(R):>4} WR={(R>0).mean()*100:>3.0f}% PF={gp/gl:>5.2f} "
            f"avgR={R.mean():>+6.3f} totR={R.sum():>+7.1f} ddR={dd:>5.1f}")


ROWS = [("A INCUMBENT      ", None,     False, False),
        ("B  +BE12 (DEPLOYED)", "naive",  False, False),
        ("C  +arm-check    ", "naive",  True,  False),
        ("D  +gap-fill     ", "naive",  True,  True),
        ("E  +honest BE12  ", "honest", True,  True),
        ("F  BE12-as-cut   ", "cut",    True,  True),
        ("G  no BE at all  ", None,     True,  True)]

for sym in SYMS:
    m15, h1 = load(sym)
    med_sp = float(m15["spread"].median()) / 10.0
    print(f"\n{'='*98}\n{sym}   M15 {len(m15)} bars from {m15['bt'].iloc[0].date()}   "
          f"median recorded spread = {med_sp:.2f}p (comm {SYMS[sym]['comm']}p)\n{'='*98}")
    base = keep_d = None
    for name, be, arm, gap in ROWS:
        tr, blk = simulate(sym, m15, h1, be, arm, gap)
        if base is None:
            base = (tr, blk)
        if name.startswith("D"):
            keep_d = tr
        print(f"  {name:<20} FULL   {stats(tr)}")
        print(f"  {'':<20} 2023+  {stats(tr, 2023)}")
    tr0, blk = base
    nb = [x for x in tr0 if x["blocked"]]
    if tr0:
        print(f"\n  un-placeable legs at 07:00: {blk['days']} days "
              f"(long {blk['long']}, short {blk['short']})")
        if nb:
            R = np.array([x["pnl"] / x["risk"] for x in nb])
            Rc = np.array([x["pnl"] / x["risk"] for x in tr0 if not x["blocked"]])
            print(f"  incumbent booked {len(nb)} trades on affected days: "
                  f"avgR {R.mean():+.3f} WR {(R>0).mean()*100:.0f}%  |  "
                  f"clean days: N={len(Rc)} avgR {Rc.mean():+.3f} WR {(Rc>0).mean()*100:.0f}%")
    # how much of D leans on a BE modify the broker would have rejected?
    if keep_d:
        be_ex = [x for x in keep_d if x["reason"] == "BE"]
        imp = [x for x in be_ex if x["uw"]]
        print(f"  D BE exits: {len(be_ex)}/{len(keep_d)}; of those {len(imp)} were "
              f"underwater at 12:00 UTC (modify rejected live, SL stays original)")
    print(f"\n  --- cost sensitivity: spread floored to {SYMS[sym]['sp_floor']}p "
          f"(recorded median is {med_sp:.2f}p) ---")
    for lbl, be in (("E honest BE12", "honest"), ("F BE12-as-cut", "cut"),
                    ("G no BE      ", None)):
        tr, _ = simulate(sym, m15, h1, be, True, True, sp_floor=True)
        print(f"    {lbl}  FULL  {stats(tr)}")
        print(f"    {'':<13}  2023+ {stats(tr, 2023)}")

mt5.shutdown()
