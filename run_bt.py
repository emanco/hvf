"""Wrapper with error capture."""
import sys
import os
import traceback

sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

# Write crash info first
try:
    with open("C:/hvf_trader/bt_status.txt", "w") as f:
        f.write("STARTING\n")
        f.flush()

    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("DOTENV LOADED\n")
        f.flush()

    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        filename="C:/hvf_trader/bt_results.txt",
        filemode="w",
    )
    logger = logging.getLogger("run_bt")

    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("LOGGING CONFIGURED\n")
        f.flush()

    import MetaTrader5 as mt5
    import pandas as pd
    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("IMPORTS DONE\n")
        f.flush()

    ALL_PATTERNS = ["HVF", "VIPER", "KZ_HUNT", "LONDON_SWEEP"]

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

    for symbol in ["EURUSD", "GBPUSD"]:
        logger.info(f"\n{'='*60}")
        logger.info(f"BACKTEST: {symbol}")

        rates_1h = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 20000)
        df_1h = pd.DataFrame(rates_1h)
        df_1h["time"] = pd.to_datetime(df_1h["time"], unit="s", utc=True)

        rates_4h = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 5000)
        df_4h = pd.DataFrame(rates_4h)
        df_4h["time"] = pd.to_datetime(df_4h["time"], unit="s", utc=True)

        logger.info(f"{symbol} H1: {len(df_1h)} bars, H4: {len(df_4h)} bars")

        df_1h = add_indicators(df_1h)
        df_4h = add_indicators(df_4h)
        df_1h = df_1h.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        logger.info(f"{symbol} after warmup: {len(df_1h)} bars")

        with open("C:/hvf_trader/bt_status.txt", "a") as f:
            f.write(f"{symbol} DATA READY\n")
            f.flush()

        # HVF-only
        logger.info(f"\n--- {symbol} HVF-only ---")
        eng = BacktestEngine(starting_equity=500.0, enabled_patterns=["HVF"])
        hvf_r = eng.run(df_1h, symbol, df_4h)
        logger.info(f"HVF: {hvf_r.total_trades}T, WR={hvf_r.win_rate:.0f}%, "
                     f"PF={hvf_r.profit_factor:.2f}, PnL={hvf_r.total_pnl_pips:+.1f}p")
        for i, t in enumerate(hvf_r.trades):
            logger.info(f"  #{i+1}: [{t.pattern_type}] {t.direction} "
                        f"pips={t.pnl_pips:+.1f} reason={t.exit_reason} score={t.score:.0f}")

        with open("C:/hvf_trader/bt_status.txt", "a") as f:
            f.write(f"{symbol} HVF DONE: {hvf_r.total_trades}T\n")
            f.flush()

        # All patterns
        logger.info(f"\n--- {symbol} All Patterns ---")
        eng2 = BacktestEngine(starting_equity=500.0, enabled_patterns=ALL_PATTERNS)
        all_r = eng2.run(df_1h, symbol, df_4h)
        logger.info(f"ALL: {all_r.total_trades}T, WR={all_r.win_rate:.0f}%, "
                     f"PF={all_r.profit_factor:.2f}, PnL={all_r.total_pnl_pips:+.1f}p")

        by_type = {}
        for t in all_r.trades:
            pt = t.pattern_type
            if pt not in by_type:
                by_type[pt] = {"n": 0, "wins": 0, "pnl": 0.0}
            by_type[pt]["n"] += 1
            by_type[pt]["pnl"] += t.pnl_pips
            if t.pnl_pips > 0:
                by_type[pt]["wins"] += 1
        for pt, d in sorted(by_type.items()):
            wr = d["wins"] / d["n"] * 100 if d["n"] > 0 else 0
            logger.info(f"  {pt}: {d['n']}T, WR={wr:.0f}%, PnL={d['pnl']:+.1f}p")

        longs = [t for t in all_r.trades if t.direction == "LONG"]
        shorts = [t for t in all_r.trades if t.direction == "SHORT"]
        logger.info(f"  LONG={len(longs)} ({sum(t.pnl_pips for t in longs):+.1f}p), "
                     f"SHORT={len(shorts)} ({sum(t.pnl_pips for t in shorts):+.1f}p)")

        for i, t in enumerate(all_r.trades):
            logger.info(f"  #{i+1}: [{t.pattern_type}] {t.direction} "
                        f"pips={t.pnl_pips:+.1f} reason={t.exit_reason} score={t.score:.0f}")

        with open("C:/hvf_trader/bt_status.txt", "a") as f:
            f.write(f"{symbol} ALL DONE: {all_r.total_trades}T\n")
            f.flush()

        logger.info(f"\n{symbol} DELTA: {all_r.total_trades - hvf_r.total_trades:+d}T, "
                     f"{all_r.total_pnl_pips - hvf_r.total_pnl_pips:+.1f}p")

    mt5.shutdown()

    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("COMPLETE\n")
        f.flush()

    logger.info("\n=== BACKTEST COMPLETE ===")

except Exception:
    with open("C:/hvf_trader/bt_error.txt", "w") as f:
        traceback.print_exc(file=f)
    with open("C:/hvf_trader/bt_status.txt", "a") as f:
        f.write("CRASHED\n")
        traceback.print_exc(file=f)
