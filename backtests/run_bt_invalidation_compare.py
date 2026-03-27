"""Compare backtest results WITH vs WITHOUT invalidation exits.

Runs on VPS. Uses live config (KZ_HUNT, 5 pairs, 10yr data).
Outputs side-by-side metrics and per-trade invalidation analysis.
"""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_inval_compare")

    import MetaTrader5 as mt5
    import pandas as pd
    import numpy as np
    from collections import defaultdict

    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    path = os.getenv("MT5_PATH")
    if not mt5.initialize(path=path):
        raise RuntimeError("MT5 init failed")
    if not mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                     server=os.getenv("MT5_SERVER")):
        raise RuntimeError("MT5 login failed")

    PAIRS = config.INSTRUMENTS
    PATTERNS = config.ENABLED_PATTERNS
    EQUITY = 700.0
    H1_BARS = 70000
    H4_BARS = 18000

    for p in PAIRS:
        if p not in config.PIP_VALUES:
            config.PIP_VALUES[p] = 0.0001

    logger.info("=" * 90)
    logger.info("INVALIDATION A/B TEST — WITH vs WITHOUT")
    logger.info(f"Patterns: {PATTERNS}, Pairs: {PAIRS}")
    logger.info("=" * 90)

    # Fetch data once
    data = {}
    for symbol in PAIRS:
        r1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, H1_BARS)
        r4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, H4_BARS)
        if r1 is None or r4 is None:
            logger.warning(f"Skipping {symbol}: no data")
            continue
        d1 = pd.DataFrame(r1); d1["time"] = pd.to_datetime(d1["time"], unit="s", utc=True)
        d4 = pd.DataFrame(r4); d4["time"] = pd.to_datetime(d4["time"], unit="s", utc=True)
        d1 = add_indicators(d1); d4 = add_indicators(d4)
        d1 = d1.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        years = (d1["time"].iloc[-1] - d1["time"].iloc[0]).days / 365.25
        logger.info(f"{symbol}: {len(d1)} H1 bars ({years:.1f} years)")
        data[symbol] = (d1, d4)
    mt5.shutdown()

    # ─── Run A: WITH invalidation (current code) ────────────────────────────
    logger.info("\n" + "=" * 90)
    logger.info("RUN A: WITH INVALIDATION")
    logger.info("=" * 90)

    results_with = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
        res = eng.run(d1, symbol, d4)
        results_with[symbol] = res
        logger.info(f"  {symbol}: {res.total_trades}T, {res.total_pnl_pips:+.1f}p, "
                    f"PF={res.profit_factor:.2f}, Invalidations={res.invalidation_exits}")

    # ─── Run B: WITHOUT invalidation ────────────────────────────────────────
    # Temporarily zero out invalidation levels by patching BacktestTrade defaults
    # Simpler approach: just set invalidation_long/short to 0 which disables the check
    # since the check is `trade.invalidation_long > 0`
    # We need to prevent the engine from setting them. Monkey-patch the engine.
    logger.info("\n" + "=" * 90)
    logger.info("RUN B: WITHOUT INVALIDATION (baseline)")
    logger.info("=" * 90)

    # Save original run method and create a wrapper that zeros invalidation
    _orig_run = BacktestEngine.run

    def _run_no_invalidation(self, df_1h, symbol, df_4h=None):
        result = _orig_run(self, df_1h, symbol, df_4h)
        return result

    # Actually, the simplest way: temporarily set all invalidation levels to 0
    # after trade creation. Let's just monkey-patch _manage_trade to skip invalidation.
    _orig_manage = BacktestEngine._manage_trade

    def _manage_no_invalidation(self, trade, bar, trade_idx, highest, lowest, pip_value, trail_mult=None):
        # Save and zero out invalidation levels
        saved_long = trade.invalidation_long
        saved_short = trade.invalidation_short
        trade.invalidation_long = 0.0
        trade.invalidation_short = 0.0
        result = _orig_manage(self, trade, bar, trade_idx, highest, lowest, pip_value, trail_mult=trail_mult)
        # Restore (in case trade is still open)
        if not result:
            trade.invalidation_long = saved_long
            trade.invalidation_short = saved_short
        return result

    BacktestEngine._manage_trade = _manage_no_invalidation

    results_without = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
        res = eng.run(d1, symbol, d4)
        results_without[symbol] = res
        logger.info(f"  {symbol}: {res.total_trades}T, {res.total_pnl_pips:+.1f}p, "
                    f"PF={res.profit_factor:.2f}")

    # Restore original
    BacktestEngine._manage_trade = _orig_manage

    # ─── COMPARISON ──────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 90)
    logger.info("SIDE-BY-SIDE COMPARISON")
    logger.info(f"{'':>12} {'--- WITH INVALIDATION ---':>40} {'--- WITHOUT (BASELINE) ---':>40}")
    logger.info(f"{'Pair':<10} {'Trades':>7} {'WR':>6} {'PF':>7} {'Pips':>10} {'Inval':>6}  "
                f"{'Trades':>7} {'WR':>6} {'PF':>7} {'Pips':>10}  {'PipDiff':>8}")
    logger.info("-" * 110)

    totals = {"w_trades": 0, "w_pips": 0.0, "w_wins": 0, "w_gw": 0.0, "w_gl": 0.0, "w_inval": 0,
              "wo_trades": 0, "wo_pips": 0.0, "wo_wins": 0, "wo_gw": 0.0, "wo_gl": 0.0}

    for symbol in PAIRS:
        if symbol not in results_with or symbol not in results_without:
            continue
        rw = results_with[symbol]
        rwo = results_without[symbol]

        pf_w = f"{rw.profit_factor:.2f}" if rw.profit_factor < 100 else "inf"
        pf_wo = f"{rwo.profit_factor:.2f}" if rwo.profit_factor < 100 else "inf"
        diff = rw.total_pnl_pips - rwo.total_pnl_pips

        logger.info(
            f"  {symbol:<10} {rw.total_trades:>5} {rw.win_rate:>5.0f}% {pf_w:>7} {rw.total_pnl_pips:>+10.1f} {rw.invalidation_exits:>5}  "
            f"{rwo.total_trades:>5} {rwo.win_rate:>5.0f}% {pf_wo:>7} {rwo.total_pnl_pips:>+10.1f}  {diff:>+8.1f}"
        )

        # Accumulate
        totals["w_trades"] += rw.total_trades
        totals["w_pips"] += rw.total_pnl_pips
        totals["w_wins"] += rw.winning_trades
        totals["w_inval"] += rw.invalidation_exits
        w_winners = [t for t in rw.trades if t.pnl_pips > 0]
        w_losers = [t for t in rw.trades if t.pnl_pips <= 0]
        totals["w_gw"] += sum(t.pnl_pips for t in w_winners)
        totals["w_gl"] += abs(sum(t.pnl_pips for t in w_losers))

        totals["wo_trades"] += rwo.total_trades
        totals["wo_pips"] += rwo.total_pnl_pips
        totals["wo_wins"] += rwo.winning_trades
        wo_winners = [t for t in rwo.trades if t.pnl_pips > 0]
        wo_losers = [t for t in rwo.trades if t.pnl_pips <= 0]
        totals["wo_gw"] += sum(t.pnl_pips for t in wo_winners)
        totals["wo_gl"] += abs(sum(t.pnl_pips for t in wo_losers))

    # Totals
    logger.info("-" * 110)
    w_wr = totals["w_wins"] / totals["w_trades"] * 100 if totals["w_trades"] > 0 else 0
    w_pf = totals["w_gw"] / totals["w_gl"] if totals["w_gl"] > 0 else float("inf")
    wo_wr = totals["wo_wins"] / totals["wo_trades"] * 100 if totals["wo_trades"] > 0 else 0
    wo_pf = totals["wo_gw"] / totals["wo_gl"] if totals["wo_gl"] > 0 else float("inf")
    w_pf_s = f"{w_pf:.2f}" if w_pf < 100 else "inf"
    wo_pf_s = f"{wo_pf:.2f}" if wo_pf < 100 else "inf"
    diff = totals["w_pips"] - totals["wo_pips"]

    logger.info(
        f"  {'TOTAL':<10} {totals['w_trades']:>5} {w_wr:>5.0f}% {w_pf_s:>7} {totals['w_pips']:>+10.1f} {totals['w_inval']:>5}  "
        f"{totals['wo_trades']:>5} {wo_wr:>5.0f}% {wo_pf_s:>7} {totals['wo_pips']:>+10.1f}  {diff:>+8.1f}"
    )

    # ─── Invalidation trade analysis ─────────────────────────────────────────
    logger.info("\n" + "=" * 90)
    logger.info("INVALIDATION EXIT ANALYSIS (trades that were invalidated)")
    logger.info(f"{'Pair':<10} {'Dir':<6} {'Entry':>10} {'InvalExit':>10} {'PnlPips':>8} "
                f"{'MFE':>8} {'MAE':>8} {'BarsHeld':>8}")
    logger.info("-" * 90)

    inval_trades = []
    for symbol in PAIRS:
        if symbol not in results_with:
            continue
        for t in results_with[symbol].trades:
            if t.exit_reason == "INVALIDATION":
                bars_held = t.exit_bar - t.entry_bar
                logger.info(
                    f"  {t.symbol:<10} {t.direction:<6} {t.entry_price:>10.5f} {t.exit_price:>10.5f} "
                    f"{t.pnl_pips:>+8.1f} {t.max_favourable:>8.1f} {t.max_adverse:>8.1f} {bars_held:>8}"
                )
                inval_trades.append(t)

    if inval_trades:
        avg_pnl = np.mean([t.pnl_pips for t in inval_trades])
        avg_mfe = np.mean([t.max_favourable for t in inval_trades])
        avg_mae = np.mean([t.max_adverse for t in inval_trades])
        pct_neg = sum(1 for t in inval_trades if t.pnl_pips < 0) / len(inval_trades) * 100
        logger.info("-" * 90)
        logger.info(f"  Invalidated trades: {len(inval_trades)}")
        logger.info(f"  Avg PnL: {avg_pnl:+.1f} pips, Avg MFE: {avg_mfe:.1f} pips, Avg MAE: {avg_mae:.1f} pips")
        logger.info(f"  % losing at invalidation: {pct_neg:.0f}%")

    logger.info("\n=== COMPARISON COMPLETE ===")

    with open("C:/hvf_trader/bt_inval_status.txt", "w") as f:
        f.write("COMPLETE\n")
        f.write(f"WITH:    {totals['w_trades']}T, {totals['w_pips']:+.0f}p, PF={w_pf:.2f}, Inval={totals['w_inval']}\n")
        f.write(f"WITHOUT: {totals['wo_trades']}T, {totals['wo_pips']:+.0f}p, PF={wo_pf:.2f}\n")
        f.write(f"DIFF:    {diff:+.0f} pips\n")

except Exception:
    with open("C:/hvf_trader/bt_inval_error.txt", "w") as f:
        traceback.print_exc(file=f)
    with open("C:/hvf_trader/bt_inval_status.txt", "w") as f:
        f.write("CRASHED\n")
        traceback.print_exc(file=f)
