"""HVF backtest across candidate pairs at £700 equity."""
import sys
import os
import traceback

sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    with open("C:/hvf_trader/bt_status.txt", "w") as f:
        f.write("STARTING MULTI-PAIR\n")
        f.flush()

    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        filename="C:/hvf_trader/bt_results.txt",
        filemode="w",
    )
    logger = logging.getLogger("run_bt_pairs")

    import MetaTrader5 as mt5
    import pandas as pd
    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    path = os.getenv("MT5_PATH")
    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not mt5.initialize(path=path):
        logger.error(f"MT5 init failed: {mt5.last_error()}")
        sys.exit(1)
    if not mt5.login(login, password=password, server=server):
        logger.error(f"MT5 login failed: {mt5.last_error()}")
        sys.exit(1)

    logger.info("MT5 connected")

    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("MT5 CONNECTED\n")
        f.flush()

    # Test these pairs — all have pip_size=0.0001 so sizing works at £700
    TEST_PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP"]
    EQUITY = 700.0
    BARS = 10000  # ~14 months H1

    logger.info(f"Testing {len(TEST_PAIRS)} pairs, {BARS} H1 bars, £{EQUITY:.0f} equity")
    logger.info("=" * 70)

    results_summary = []

    for symbol in TEST_PAIRS:
        logger.info(f"\n{'='*60}")
        logger.info(f"BACKTEST: {symbol}")

        with open("C:/hvf_trader/bt_status.txt", "a") as f:
            f.write(f"{symbol} STARTING\n")
            f.flush()

        try:
            # Fetch data
            rates_1h = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, BARS)
            if rates_1h is None or len(rates_1h) == 0:
                logger.warning(f"{symbol}: No H1 data available, skipping")
                results_summary.append(f"{symbol}: NO DATA")
                continue

            df_1h = pd.DataFrame(rates_1h)
            df_1h["time"] = pd.to_datetime(df_1h["time"], unit="s", utc=True)

            rates_4h = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 2500)
            if rates_4h is None or len(rates_4h) == 0:
                logger.warning(f"{symbol}: No H4 data available, skipping")
                results_summary.append(f"{symbol}: NO 4H DATA")
                continue

            df_4h = pd.DataFrame(rates_4h)
            df_4h["time"] = pd.to_datetime(df_4h["time"], unit="s", utc=True)

            logger.info(f"{symbol} H1: {len(df_1h)} bars, H4: {len(df_4h)} bars")

            # Add indicators
            df_1h = add_indicators(df_1h)
            df_4h = add_indicators(df_4h)
            df_1h = df_1h.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
            logger.info(f"{symbol} after warmup: {len(df_1h)} bars")

            # Run HVF-only backtest
            eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=["HVF"])
            result = eng.run(df_1h, symbol, df_4h)

            pf_str = f"{result.profit_factor:.2f}" if result.profit_factor != float('inf') else "inf"
            wr_str = f"{result.win_rate:.0f}%" if result.total_trades > 0 else "-"

            logger.info(f"RESULT: {result.total_trades}T, WR={wr_str}, "
                        f"PF={pf_str}, PnL={result.total_pnl_pips:+.1f}p, "
                        f"MaxDD={result.max_drawdown_pct:.1f}%")

            # Trade details
            longs = [t for t in result.trades if t.direction == "LONG"]
            shorts = [t for t in result.trades if t.direction == "SHORT"]
            logger.info(f"  LONG={len(longs)} ({sum(t.pnl_pips for t in longs):+.1f}p), "
                        f"SHORT={len(shorts)} ({sum(t.pnl_pips for t in shorts):+.1f}p)")

            for i, t in enumerate(result.trades):
                logger.info(f"  #{i+1}: {t.direction} entry={t.entry_price:.5f} "
                            f"exit={t.exit_price:.5f} pips={t.pnl_pips:+.1f} "
                            f"reason={t.exit_reason} score={t.score:.0f}")

            summary = f"{symbol}: {result.total_trades}T, WR={wr_str}, PF={pf_str}, PnL={result.total_pnl_pips:+.1f}p"
            results_summary.append(summary)

            with open("C:/hvf_trader/bt_status.txt", "a") as f:
                f.write(f"{symbol} DONE: {result.total_trades}T, PnL={result.total_pnl_pips:+.1f}p\n")
                f.flush()

        except Exception as e:
            logger.error(f"{symbol} CRASHED: {e}")
            import traceback as tb
            logger.error(tb.format_exc())
            results_summary.append(f"{symbol}: ERROR - {e}")
            with open("C:/hvf_trader/bt_status.txt", "a") as f:
                f.write(f"{symbol} ERROR: {e}\n")
                f.flush()
            continue

    # Final summary
    logger.info(f"\n{'='*70}")
    logger.info("MULTI-PAIR SUMMARY (HVF-only, 10K H1 bars, £700)")
    logger.info("=" * 70)
    for line in results_summary:
        logger.info(f"  {line}")

    mt5.shutdown()

    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("COMPLETE\n")
        for line in results_summary:
            f.write(f"  {line}\n")
        f.flush()

    logger.info("\n=== BACKTEST COMPLETE ===")

except Exception:
    with open("C:/hvf_trader/bt_error.txt", "w") as f:
        traceback.print_exc(file=f)
    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("CRASHED\n")
        traceback.print_exc(file=f)
