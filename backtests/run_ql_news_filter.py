"""Backtest a news filter overlay on QL EURCHF.

The QL backtest period is 2022-04 → 2026-04 (4 years of M15 data). Without
historical ForexFactory data we approximate the major CHF and EUR
high-impact events with a synthetic recurring schedule that mirrors the
real publication calendar reasonably well:

  - SNB Policy Rate: quarterly (Mar/Jun/Sep/Dec), 3rd Thursday @ 07:30 UTC
  - ECB Rate Decision: ~6-week cadence, Thursdays @ 12:45 UTC
  - CHF CPI: monthly, 1st Thursday @ 06:30 UTC
  - CHF GDP: quarterly, 1st Tuesday of Mar/Jun/Sep/Dec @ 06:00 UTC
  - German/EZ CPI Flash: monthly, last weekday @ 09:00 UTC

The filter: if any of the above falls inside the QL hold window
(22:00 UTC prior day → 21:00 UTC) for that session, skip the capture.

Tests two threshold variants:
  - HIGH only: SNB + ECB + GDP only (~16/year)
  - HIGH + CPI: above + CPI flashes (~40/year)

Reuses the QL simulation logic from run_ql_eurchf_vs_eurgbp.py.
"""
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
PIP = 0.0001
SPREAD = 1.0
CAPTURE_HOUR_UTC = 22
EXIT_HOUR_UTC = 21
DAYS = [6, 0, 1, 2, 3]  # Sun-Thu captures (Mon-Fri trading sessions)

# --- Synthetic news schedule -------------------------------------------------

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
    """nth occurrence of `weekday` in `month/year` (n=1..5). weekday: 0=Mon."""
    d = datetime(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    d += timedelta(weeks=n - 1)
    if d.month != month:
        return None
    return d


def _last_weekday(year: int, month: int) -> datetime:
    """Last weekday (Mon-Fri) of `month/year`."""
    if month == 12:
        d = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = datetime(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


def generate_news_events(start: datetime, end: datetime, include_cpi: bool):
    """Return list of (event_time_utc, label, severity) covering [start, end]."""
    events = []
    year, month = start.year, start.month
    end_naive = end.replace(tzinfo=None) if end.tzinfo else end
    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    while datetime(year, month, 1) <= end_naive:
        # SNB quarterly: Mar/Jun/Sep/Dec, 3rd Thursday @ 07:30 UTC
        if month in (3, 6, 9, 12):
            d = _nth_weekday(year, month, 3, 3)  # 3=Thu
            if d:
                events.append((
                    d.replace(hour=7, minute=30, tzinfo=timezone.utc),
                    "SNB Policy Rate", "HIGH",
                ))
            # CHF GDP: 1st Tuesday @ 06:00 UTC
            d = _nth_weekday(year, month, 1, 1)
            if d:
                events.append((
                    d.replace(hour=6, minute=0, tzinfo=timezone.utc),
                    "CHF GDP", "HIGH",
                ))
        # CHF CPI: 1st Thursday @ 06:30 UTC (every month)
        d = _nth_weekday(year, month, 3, 1)
        if d:
            events.append((
                d.replace(hour=6, minute=30, tzinfo=timezone.utc),
                "CHF CPI", "CPI",
            ))
        # ECB ~6 weeks: approximate as 3rd Thursday of Mar/Apr/Jun/Jul/Sep/Oct/Dec @ 12:45 UTC
        if month in (3, 4, 6, 7, 9, 10, 12):
            d = _nth_weekday(year, month, 3, 3)
            if d:
                events.append((
                    d.replace(hour=12, minute=45, tzinfo=timezone.utc),
                    "ECB Rate", "HIGH",
                ))
        # EZ CPI Flash: last weekday @ 09:00 UTC (monthly)
        d = _last_weekday(year, month)
        if d:
            events.append((
                d.replace(hour=9, minute=0, tzinfo=timezone.utc),
                "EZ CPI Flash", "CPI",
            ))
        month += 1
        if month > 12:
            year += 1
            month = 1

    # Compare in UTC (events are tz-aware UTC; ensure start/end are too)
    start_aware = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end_aware = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    events = [e for e in events if start_aware <= e[0] <= end_aware]
    if not include_cpi:
        events = [e for e in events if e[2] != "CPI"]
    events.sort()
    return events


def session_blocked(session_date, news_events: list) -> bool:
    """A QL session is the 23h window 22:00 prior day → 21:00 session day UTC."""
    start = datetime.combine(session_date, dtime(22, 0), tzinfo=timezone.utc) - timedelta(days=1)
    end = datetime.combine(session_date, dtime(21, 0), tzinfo=timezone.utc)
    return any(start <= et <= end for et, _, _ in news_events)


# --- QL simulation (re-used from run_ql_eurchf_vs_eurgbp) -------------------

def load_eurchf_m15():
    df = pd.read_csv(ROOT / "data/EURCHF_M15.csv")
    df["utc_t"] = pd.to_datetime(df["time"], utc=True)
    return df


def build_sessions(df):
    sessions = {}
    for _, r in df.iterrows():
        utc_t = r["utc_t"]
        if isinstance(utc_t, pd.Timestamp):
            utc_t = utc_t.to_pydatetime()
        h = utc_t.hour
        if h >= CAPTURE_HOUR_UTC:
            sd = utc_t.date()
        elif h < EXIT_HOUR_UTC:
            sd = utc_t.date() - timedelta(days=1)
        else:
            continue
        if sd not in sessions:
            sessions[sd] = {"wd": sd.weekday(), "bars": []}
        sessions[sd]["bars"].append({
            "h_utc": h, "utc_t": utc_t,
            "o": r["open"], "hi": r["high"], "lo": r["low"], "cl": r["close"],
        })
    for sd, s in sessions.items():
        s["bars"].sort(key=lambda b: b["utc_t"])
        cap = [b for b in s["bars"] if b["h_utc"] >= CAPTURE_HOUR_UTC]
        s["open"] = cap[0]["o"] if cap else None
    return sessions


def simulate(sessions, trigger, target, stop, news_events=None):
    trades = []
    fired = total = blocked = 0
    for sd in sorted(sessions):
        s = sessions[sd]
        if s["open"] is None or s["wd"] not in DAYS:
            continue
        if news_events is not None and session_blocked(sd, news_events):
            blocked += 1
            continue
        total += 1
        so = s["open"]
        trading = [b for b in s["bars"] if b["utc_t"].date() > sd or b["h_utc"] >= CAPTURE_HOUR_UTC]
        if not trading:
            continue
        ot = None
        done = False
        for i, b in enumerate(trading):
            if done:
                break
            if ot is None:
                if i == 0:
                    continue
                if b["lo"] <= so - trigger * PIP:
                    ep = so - trigger * PIP
                    ot = ("L", ep, ep + target * PIP, ep - stop * PIP, i)
                    fired += 1
                elif b["hi"] >= so + trigger * PIP:
                    ep = so + trigger * PIP
                    ot = ("S", ep, ep - target * PIP, ep + stop * PIP, i)
                    fired += 1
            else:
                d_dir, ep, tp, sl_p, entry_idx = ot
                if i <= entry_idx:
                    continue
                if d_dir == "L":
                    if b["lo"] <= sl_p:
                        trades.append({"d": sd, "pnl": (sl_p - ep) / PIP - SPREAD, "x": "SL"}); done = True
                    elif b["hi"] >= tp:
                        trades.append({"d": sd, "pnl": (tp - ep) / PIP - SPREAD, "x": "TP"}); done = True
                else:
                    if b["hi"] >= sl_p:
                        trades.append({"d": sd, "pnl": (ep - sl_p) / PIP - SPREAD, "x": "SL"}); done = True
                    elif b["lo"] <= tp:
                        trades.append({"d": sd, "pnl": (ep - tp) / PIP - SPREAD, "x": "TP"}); done = True
        if ot and not done:
            d_dir, ep, *_ = ot
            last = trading[-1]
            pnl = (last["cl"] - ep) / PIP - SPREAD if d_dir == "L" else (ep - last["cl"]) / PIP - SPREAD
            trades.append({"d": sd, "pnl": pnl, "x": "TIME"})
    return trades, fired, total, blocked


def stats(trades):
    if not trades:
        return None
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    wins = (pnls > 0).sum()
    gp = pnls[pnls > 0].sum() if wins else 0
    gl = abs(pnls[pnls <= 0].sum()) if (pnls <= 0).sum() else 0.001
    eq = np.cumsum(pnls)
    dd = (np.maximum.accumulate(eq) - eq).max() if n > 1 else 0
    return {"n": n, "wr": wins/n*100, "pf": gp/gl, "tot": pnls.sum(),
            "dd": dd, "eq": eq, "mar": pnls.sum()/dd if dd > 0 else 0,
            "tps": sum(1 for t in trades if t["x"] == "TP"),
            "sls": sum(1 for t in trades if t["x"] == "SL"),
            "tms": sum(1 for t in trades if t["x"] == "TIME")}


def main():
    print("Loading EURCHF M15 data...")
    df = load_eurchf_m15()
    start, end = df["utc_t"].iloc[0].to_pydatetime(), df["utc_t"].iloc[-1].to_pydatetime()
    print(f"  Range: {start} → {end}\n")

    events_high = generate_news_events(start, end, include_cpi=False)
    events_full = generate_news_events(start, end, include_cpi=True)
    print(f"Generated news schedules:")
    print(f"  HIGH only (SNB+ECB+GDP):    {len(events_high)} events")
    print(f"  HIGH + CPI:                 {len(events_full)} events\n")

    sessions = build_sessions(df)
    valid = sum(1 for s in sessions.values() if s["open"] is not None and s["wd"] in DAYS)
    print(f"  EURCHF: {valid} valid sessions\n")

    TRIG, TGT, STP = 40, 12.5, 40  # production tuning

    print(f"=== EURCHF 40/12.5/40 (IC Markets tuning), 4 years ===")
    print(f"{'Variant':<28} {'Fired':>6} {'Rate':>5} {'Blkd':>5} {'N':>4} {'WR':>5} {'PF':>5} {'Tot':>9} {'DD':>6} {'MAR':>5}")
    print("-" * 110)

    runs = []
    for label, events in [
        ("baseline (no filter)", None),
        ("filter HIGH only",     events_high),
        ("filter HIGH + CPI",    events_full),
    ]:
        trades, fired, total, blocked = simulate(sessions, TRIG, TGT, STP, news_events=events)
        r = stats(trades)
        if r:
            rate = fired / max(1, total) * 100
            print(f"{label:<28} {fired:>6d} {rate:>4.0f}% {blocked:>5d} {r['n']:>4d} "
                  f"{r['wr']:>4.0f}% {r['pf']:>5.2f} {r['tot']:>+8.1f}p "
                  f"{r['dd']:>5.0f}p {r['mar']:>5.2f}")
            runs.append((label, r, blocked))

    # Equity curves
    print()
    fig, ax = plt.subplots(figsize=(14, 7))
    for label, r, blocked in runs:
        eq = np.concatenate([[0], r["eq"]])
        ax.plot(range(len(eq)), eq, label=f"{label} (N={r['n']}, PF={r['pf']:.2f}, +{r['tot']:.0f}p)")
    ax.axhline(0, color="gray", linestyle="--", alpha=0.4)
    ax.set_title("QL EURCHF — news-filter overlay (4-yr backtest, 40/12.5/40)",
                 fontsize=12, fontweight="bold")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative pips")
    ax.legend()
    ax.grid(True, alpha=0.3)
    out = ROOT / "charts" / "ql_news_filter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved chart: {out}")


if __name__ == "__main__":
    main()
