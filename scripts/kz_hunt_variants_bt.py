"""
KZ Hunt: backtest variant comparison.

Variants:
  A) baseline (score>=50, 1-bar confirmation, current ruleset)
  B) score>=70
  C) bars_since_rejection <= 1 (only the bar immediately after rejection)
  D) rej_size_atr >= 1.0 (require rejection candle range >= 1x ATR)
  E) combined: score>=60 AND bars_since_rejection<=1
  F) combined: score>=60 AND rej_size_atr>=1.0

Uses the real BacktestEngine. Monkey-patches detect_kz_hunt_patterns to add
filters where needed.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from hvf_trader.backtesting import backtest_engine as be_mod
from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.detector import kz_hunt_detector as kz_mod
from hvf_trader.detector.kz_hunt_detector import detect_kz_hunt_patterns

DATA = "/Users/emanuelemanco/dev/hvf/backtests/data"
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]

# Limit to recent ~3 years (sufficient sample, fast turnaround)
START_DATE = "2023-01-01"


def load_h1(sym):
    p = os.path.join(DATA, f"{sym}_H1.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df[df["time"] >= START_DATE].copy()
    df = add_indicators(df)
    if "tick_volume" in df.columns:
        df["volume"] = df["tick_volume"]
    return df.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)


# Filter spec: callable(pattern, df, last_bar_idx) -> bool (True = keep)
def make_detect_with_filter(filt):
    def detect(df, symbol, timeframe, kz_tracker):
        pats = detect_kz_hunt_patterns(df, symbol, timeframe, kz_tracker)
        if not filt:
            return pats
        last_idx = df.index[-1]
        return [p for p in pats if filt(p, df, last_idx)]
    return detect


def filter_fresh_rejection(max_bars):
    """Only allow patterns where rejection_bar_idx is within `max_bars` of current bar."""
    def f(p, df, last_idx):
        return (last_idx - p.rejection_bar_idx) <= max_bars
    return f


def filter_rej_size_atr(min_ratio):
    """Require rejection candle (high-low) >= min_ratio * ATR at rejection bar."""
    def f(p, df, last_idx):
        if p.rejection_bar_idx not in df.index:
            return False
        bar = df.loc[p.rejection_bar_idx]
        atr = bar.get("atr", 0)
        if atr <= 0 or np.isnan(atr):
            return False
        return (bar["high"] - bar["low"]) / atr >= min_ratio
    return f


def filter_and(*filters):
    def f(p, df, last_idx):
        return all(filt(p, df, last_idx) for filt in filters)
    return f


def run_variant(label, score_threshold, extra_filter, h1_data):
    # Patch the detector reference inside backtest_engine
    original = be_mod.detect_kz_hunt_patterns
    be_mod.detect_kz_hunt_patterns = make_detect_with_filter(extra_filter)

    # Patch SCORE_THRESHOLD_BY_PATTERN
    original_thresh = config.SCORE_THRESHOLD_BY_PATTERN.get("KZ_HUNT", 50)
    config.SCORE_THRESHOLD_BY_PATTERN["KZ_HUNT"] = score_threshold

    try:
        all_trades = []
        for sym in INSTRUMENTS:
            df = h1_data.get(sym)
            if df is None:
                continue
            engine = BacktestEngine(
                starting_equity=10000.0,
                enabled_patterns=["KZ_HUNT"],
                simulate_news_blocks=True,
                simulate_circuit_breaker=True,
            )
            res = engine.run(df, sym)
            for t in res.trades:
                all_trades.append({
                    "sym": sym,
                    "dir": t.direction,
                    "score": t.score,
                    "pnl_pips": t.pnl_pips,
                    "pnl_currency": t.pnl_currency,
                    "exit_reason": t.exit_reason,
                })
    finally:
        be_mod.detect_kz_hunt_patterns = original
        config.SCORE_THRESHOLD_BY_PATTERN["KZ_HUNT"] = original_thresh

    if not all_trades:
        print(f"  {label}: 0 trades")
        return None

    df_t = pd.DataFrame(all_trades)
    n = len(df_t)
    wins = (df_t["pnl_pips"] > 0).sum()
    wr = wins / n * 100
    gp = df_t.loc[df_t["pnl_pips"] > 0, "pnl_pips"].sum()
    gl = abs(df_t.loc[df_t["pnl_pips"] <= 0, "pnl_pips"].sum())
    pf = gp / gl if gl > 0 else float("inf")
    tot_pips = df_t["pnl_pips"].sum()
    tot_cur = df_t["pnl_currency"].sum()
    print(f"  {label:<60} n={n:4d}  WR={wr:5.1f}%  PF={pf:4.2f}  Pips={tot_pips:+8.0f}  $={tot_cur:+9.0f}")
    return {"label": label, "n": n, "wr": wr, "pf": pf, "pips": tot_pips, "$": tot_cur, "trades": df_t}


def main():
    import sys as _sys
    _sys.stdout.reconfigure(line_buffering=True)
    print(f"Loading H1 data for 8 pairs (from {START_DATE})...")
    h1_data = {sym: load_h1(sym) for sym in INSTRUMENTS}
    h1_data = {k: v for k, v in h1_data.items() if v is not None}
    for sym, df in h1_data.items():
        print(f"  {sym}: {len(df)} bars, {df['time'].iloc[0].date()} to {df['time'].iloc[-1].date()}")
    print()
    print("Running variants...")
    print()

    variants = [
        ("A) baseline score>=50",                  50, None),
        ("B) score>=70",                            70, None),
        ("C) score>=50 + bars_since_rej<=1",       50, filter_fresh_rejection(1)),
        ("D) score>=50 + rej_size_atr>=1.0",       50, filter_rej_size_atr(1.0)),
        ("E) score>=60 + bars_since_rej<=1",       60, filter_fresh_rejection(1)),
        ("F) score>=70 + bars_since_rej<=1",       70, filter_fresh_rejection(1)),
        ("G) score>=60 + rej_size>=1.0 + bsr<=1",  60,
                                                  filter_and(filter_fresh_rejection(1), filter_rej_size_atr(1.0))),
    ]

    results = []
    for label, thresh, filt in variants:
        try:
            r = run_variant(label, thresh, filt, h1_data)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  {label}: ERROR {e}")
            import traceback; traceback.print_exc()

    print()
    print("=== Summary (sorted by PF) ===")
    for r in sorted(results, key=lambda x: -x["pf"]):
        print(f"  PF={r['pf']:.2f}  WR={r['wr']:5.1f}%  n={r['n']:4d}  Pips={r['pips']:+7.0f}  ${r['$']:+8.0f}  | {r['label']}")


if __name__ == "__main__":
    main()
