"""LONDON_BO honest backtest (2026-06-23).

LONDON_BO was the only live strategy with no re-runnable validation — the
"12-20p range, PF 1.77" claim lived only in a docstring. This builds a proper
sim that REUSES the live detector (`LondonBreakoutTracker`) for range +
breakout signals (no logic drift), then simulates trade outcomes on H1 bars
with honest costs:

  - entry: at the breakout level + the detector's baked-in 1p spread, PLUS
    adverse stop-entry slippage (breakout fills slip).
  - exit: SL / TP resolved intrabar (SL checked first = conservative on ties),
    else force-close at 13:00 UTC.
  - round-trip cost (exit spread + commission) subtracted in pips.

Sweeps the extra round-trip cost {0,1,2,3}p to show friction sensitivity,
the same way NR7/NIGHT_TIDE were stress-tested. GBPUSD H1, Mon/Tue only.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from hvf_trader import config
from hvf_trader.detector.london_breakout import LondonBreakoutTracker, PIP

CFG = config.LONDON_BREAKOUT
SYM = CFG["instrument"]
STARTING_EQUITY = 700.0
RISK_PCT = CFG["risk_pct"]
CONTRACT = 100000


def load_h1() -> pd.DataFrame:
    df = pd.read_csv(REPO_ROOT / "backtests" / "data" / f"{SYM}_H1.csv")
    if df["time"].dtype.kind in "iu":
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


def simulate(df: pd.DataFrame, extra_cost_pips: float, entry_slip_pips: float):
    """Drive the live tracker bar-by-bar; simulate fills/exits with costs.

    Returns list of trade dicts.
    """
    tracker = LondonBreakoutTracker()
    trades = []
    open_t = None
    rows = df.to_dict("records")

    for i, bar in enumerate(rows):
        t = bar["time"]
        hour, weekday = t.hour, t.weekday()

        # 1) Manage an open trade against THIS bar.
        if open_t is not None:
            exit_px = exit_reason = None
            d = open_t["direction"]
            if hour >= CFG["exit_hour_utc"]:
                exit_px, exit_reason = bar["open"], "TIME"   # force-close at 13:00
            elif d == "LONG":
                if bar["low"] <= open_t["sl"]:               # SL first (conservative)
                    exit_px, exit_reason = open_t["sl"], "SL"
                elif bar["high"] >= open_t["tp"]:
                    exit_px, exit_reason = open_t["tp"], "TP"
            else:  # SHORT
                if bar["high"] >= open_t["sl"]:
                    exit_px, exit_reason = open_t["sl"], "SL"
                elif bar["low"] <= open_t["tp"]:
                    exit_px, exit_reason = open_t["tp"], "TP"
            if exit_px is not None:
                if d == "LONG":
                    gross = (exit_px - open_t["entry"]) / PIP
                else:
                    gross = (open_t["entry"] - exit_px) / PIP
                net = gross - extra_cost_pips           # exit spread + commission
                open_t.update(exit_time=t, exit_reason=exit_reason, pnl_pips=net)
                trades.append(open_t)
                open_t = None

        # 2) Day filter — only Mon/Tue form a range (mirrors main early-return).
        if weekday not in CFG["days"]:
            continue
        if hour >= CFG["exit_hour_utc"]:
            if tracker.state != "IDLE":
                tracker.reset()
            continue

        # 3) Formation / lock / breakout (mirrors _scan_london_breakout).
        if hour < 7:
            tracker.update_asian_bar(bar["high"], bar["low"], t)
            continue
        if tracker.state == "FORMING":
            tracker.finalize_range(CFG)   # range filter applied inside
        if hour < 8 or tracker.traded_today or open_t is not None:
            continue
        sig = tracker.check_breakout(pd.Series(bar), CFG)
        if sig:
            tracker.mark_traded()
            slip = entry_slip_pips * PIP
            # adverse entry slippage: pay more on a long, receive less on a short
            entry = sig.entry_price + slip if sig.direction == "LONG" else sig.entry_price - slip
            open_t = dict(direction=sig.direction, entry=entry, sl=sig.stop_loss,
                          tp=sig.take_profit, entry_time=t,
                          range_pips=sig.asian_range_pips)
    return trades


def stats(trades, years):
    if not trades:
        return None
    # equity-compounded USD with 1% risk per trade
    eq = STARTING_EQUITY
    usd = []
    for tr in trades:
        stop_pips = abs(tr["entry"] - tr["sl"]) / PIP
        risk_usd = eq * RISK_PCT / 100.0
        lots = max(min(round(risk_usd / max(stop_pips * PIP * CONTRACT, 1e-9), 2), 100.0), 0.01)
        pnl_usd = tr["pnl_pips"] * PIP * CONTRACT * lots
        eq += pnl_usd
        usd.append(pnl_usd)
    usd = np.array(usd)
    pips = np.array([t["pnl_pips"] for t in trades])
    n = len(trades)
    wins = (pips > 0).sum()
    gp, gl = pips[pips > 0].sum(), abs(pips[pips <= 0].sum())
    curve = np.concatenate([[STARTING_EQUITY], STARTING_EQUITY + np.cumsum(usd)])
    dd = (np.maximum.accumulate(curve) - curve).max()
    dd_pct = dd / np.maximum.accumulate(curve).max() * 100
    cagr = ((eq / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0
    return dict(n=n, wr=wins / n * 100, pf=(gp / gl if gl else float("inf")),
                pips=pips.sum(), usd=usd.sum(), dd_pct=dd_pct,
                cagr=cagr, mar=(cagr / dd_pct if dd_pct > 0 else 0))


def main():
    df = load_h1()
    years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
    print(f"LONDON_BO honest backtest — {SYM} H1, Mon/Tue, range {CFG['min_range_pips']}-{CFG['max_range_pips']}p")
    print(f"  {len(df)} bars, {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()} ({years:.1f}y)\n")
    print(f"{'arm':<42}{'N':>4}{'WR':>6}{'PF':>6}{'pips':>9}{'USD':>9}{'DD%':>7}{'MAR':>6}")
    print("-" * 89)
    arms = [
        ("baseline (1p spread only, as-claimed)", 0.0, 0.0),
        ("+ exit spread + $7 commission (~1.7p)", 1.7, 0.0),
        ("+ entry slippage 0.5p (honest)",        1.7, 0.5),
        ("stress: 3p round-trip + 1p entry slip", 3.0, 1.0),
    ]
    for label, cost, slip in arms:
        s = stats(simulate(df, cost, slip), years)
        if s:
            print(f"{label:<42}{s['n']:>4}{s['wr']:>5.0f}%{s['pf']:>6.2f}"
                  f"{s['pips']:>+9.0f}{s['usd']:>+9.0f}{s['dd_pct']:>6.1f}%{s['mar']:>6.2f}")
        else:
            print(f"{label:<42}  no trades")
    print("\nReference: docstring claimed PF 1.77 / 66% WR / +575p over 8y (142 trades).")


if __name__ == "__main__":
    main()
