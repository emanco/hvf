"""Analyze what would have happened to invalidated trades without invalidation."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

OUTPUT_FILE = "C:/hvf_trader/fate_results.txt"
lines = []

def out(s=""):
    lines.append(str(s))
    print(s)

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import MetaTrader5 as mt5
    import pandas as pd
    import numpy as np
    from collections import defaultdict

    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    path = os.getenv("MT5_PATH")
    if not mt5.initialize(path=path):
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    if not mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                     server=os.getenv("MT5_SERVER")):
        raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    PAIRS = config.INSTRUMENTS
    PATTERNS = config.ENABLED_PATTERNS
    EQUITY = 700.0

    data = {}
    for symbol in PAIRS:
        r1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 70000)
        r4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 18000)
        if r1 is None or r4 is None:
            continue
        d1 = pd.DataFrame(r1)
        d1["time"] = pd.to_datetime(d1["time"], unit="s", utc=True)
        d4 = pd.DataFrame(r4)
        d4["time"] = pd.to_datetime(d4["time"], unit="s", utc=True)
        d1 = add_indicators(d1)
        d4 = add_indicators(d4)
        d1 = d1.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        data[symbol] = (d1, d4)
    mt5.shutdown()

    # Run WITH invalidation
    out("Running WITH invalidation...")
    results_with = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
        results_with[symbol] = eng.run(d1, symbol, d4)

    # Run WITHOUT
    out("Running WITHOUT invalidation...")
    _orig = BacktestEngine._manage_trade

    def _no_inval(self, trade, bar, ti, h, l, pv, trail_mult=None):
        sl, ss = trade.invalidation_long, trade.invalidation_short
        trade.invalidation_long = trade.invalidation_short = 0.0
        r = _orig(self, trade, bar, ti, h, l, pv, trail_mult=trail_mult)
        if not r:
            trade.invalidation_long, trade.invalidation_short = sl, ss
        return r

    BacktestEngine._manage_trade = _no_inval
    results_without = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
        results_without[symbol] = eng.run(d1, symbol, d4)
    BacktestEngine._manage_trade = _orig

    # Match invalidated trades to their without-invalidation counterparts
    wo_lookup = {}
    for symbol in PAIRS:
        if symbol not in results_without:
            continue
        for t in results_without[symbol].trades:
            wo_lookup[(symbol, t.entry_bar)] = t

    all_inval = []
    fates = defaultdict(lambda: {"count": 0, "pips_with": 0.0, "pips_without": 0.0})

    for symbol in PAIRS:
        if symbol not in results_with:
            continue
        for t_w in results_with[symbol].trades:
            if t_w.exit_reason != "INVALIDATION":
                continue
            key = (symbol, t_w.entry_bar)
            t_wo = wo_lookup.get(key)
            if t_wo is None:
                continue
            fate = t_wo.exit_reason
            fates[fate]["count"] += 1
            fates[fate]["pips_with"] += t_w.pnl_pips
            fates[fate]["pips_without"] += t_wo.pnl_pips
            all_inval.append((t_w, t_wo))

    out()
    out("=" * 75)
    out("FATE OF INVALIDATED TRADES (what would have happened without invalidation)")
    out("=" * 75)
    header = f"{'Fate':<16} {'Count':>7} {'%':>6} {'Pips WITH':>12} {'Pips W/OUT':>12} {'Diff':>10}"
    out(header)
    out("-" * 75)
    total_count = sum(f["count"] for f in fates.values())

    if total_count == 0:
        out("  No invalidated trades found!")
    else:
        for fate in ["STOP_LOSS", "TRAILING_STOP", "TARGET_2", "END_OF_DATA"]:
            f = fates.get(fate)
            if not f or f["count"] == 0:
                continue
            pct = f["count"] / total_count * 100
            diff = f["pips_without"] - f["pips_with"]
            out(f"  {fate:<14} {f['count']:>7} {pct:>5.0f}% {f['pips_with']:>+12.1f} {f['pips_without']:>+12.1f} {diff:>+10.1f}")

        out("-" * 75)
        total_w = sum(f["pips_with"] for f in fates.values())
        total_wo = sum(f["pips_without"] for f in fates.values())
        out(f"  {'ALL':<14} {total_count:>7} {100:>5.0f}% {total_w:>+12.1f} {total_wo:>+12.1f} {total_wo - total_w:>+10.1f}")

        would_win = [(w, wo) for w, wo in all_inval if wo.pnl_pips > 0]
        would_lose = [(w, wo) for w, wo in all_inval if wo.pnl_pips <= 0]

        out()
        out(f"Would have been WINNERS: {len(would_win)} ({len(would_win)/len(all_inval)*100:.0f}%)")
        out(f"Would have been LOSERS:  {len(would_lose)} ({len(would_lose)/len(all_inval)*100:.0f}%)")
        out()

        saved = sum(w.pnl_pips - wo.pnl_pips for w, wo in would_lose)
        lost = sum(w.pnl_pips - wo.pnl_pips for w, wo in would_win)
        out(f"Pips saved by invalidating future losers:  {saved:+.1f}")
        out(f"Pips lost by invalidating future winners:  {lost:+.1f}")
        out(f"Net impact:                                {saved + lost:+.1f}")

        if would_win:
            avg_wo_win = np.mean([wo.pnl_pips for _, wo in would_win])
            avg_w_loss = np.mean([w.pnl_pips for w, _ in would_win])
            out()
            out("Would-have-won trades:")
            out(f"  Avg pips at invalidation exit: {avg_w_loss:+.1f}")
            out(f"  Avg pips if held (no inval):   {avg_wo_win:+.1f}")
            out(f"  Avg pips left on table:        {avg_wo_win - avg_w_loss:+.1f}")

        out()
        out("=" * 75)
        out("PER-PAIR BREAKDOWN")
        out("=" * 75)
        header2 = f"{'Pair':<10} {'Inval':>6} {'WouldWin':>9} {'WouldLose':>10} {'SavedPips':>10} {'LostPips':>10} {'Net':>10}"
        out(header2)
        out("-" * 75)
        for symbol in PAIRS:
            pair_inval = [(w, wo) for w, wo in all_inval if w.symbol == symbol]
            if not pair_inval:
                continue
            pw = [(w, wo) for w, wo in pair_inval if wo.pnl_pips > 0]
            pl = [(w, wo) for w, wo in pair_inval if wo.pnl_pips <= 0]
            pair_saved = sum(w.pnl_pips - wo.pnl_pips for w, wo in pl)
            pair_lost = sum(w.pnl_pips - wo.pnl_pips for w, wo in pw)
            out(f"  {symbol:<10} {len(pair_inval):>4} {len(pw):>9} {len(pl):>10} {pair_saved:>+10.1f} {pair_lost:>+10.1f} {pair_saved + pair_lost:>+10.1f}")

    out()
    out("=== ANALYSIS COMPLETE ===")

except Exception:
    out(f"CRASHED: {traceback.format_exc()}")

finally:
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
