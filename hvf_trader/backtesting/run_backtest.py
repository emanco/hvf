"""
Run walk-forward backtest on EURUSD and GBPUSD.
Pulls 2+ years of history from MT5, runs detection + backtest + walk-forward.
Sends results to Telegram.
"""

import sys
import os
import logging

# Add parent of hvf_trader package to path
sys.path.insert(0, "C:/")

from dotenv import load_dotenv
load_dotenv("C:/hvf_trader/.env")

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from hvf_trader import config
from hvf_trader.data.data_fetcher import add_indicators
from hvf_trader.backtesting.backtest_engine import BacktestEngine
from hvf_trader.backtesting.walk_forward import run_walk_forward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_history(symbol, timeframe_name, timeframe_mt5, bars=20000):
    """Fetch historical data from MT5."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, bars)
    if rates is None or len(rates) == 0:
        logger.error(f"Failed to fetch {symbol} {timeframe_name}: {mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    logger.info(f"{symbol} {timeframe_name}: {len(df)} bars, "
                f"{df['time'].iloc[0].strftime('%Y-%m-%d')} to "
                f"{df['time'].iloc[-1].strftime('%Y-%m-%d')}")
    return df


def main():
    # Connect to MT5
    path = os.getenv("MT5_PATH")
    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not mt5.initialize(path=path):
        logger.error(f"MT5 init failed: {mt5.last_error()}")
        return
    if not mt5.login(login, password=password, server=server):
        logger.error(f"MT5 login failed: {mt5.last_error()}")
        return

    logger.info("MT5 connected")

    results = {}

    for symbol in ["EURUSD", "GBPUSD", "AUDUSD", "USDJPY"]:
        logger.info(f"\n{'='*60}")
        logger.info(f"BACKTEST: {symbol}")
        logger.info(f"{'='*60}")

        # Fetch data
        df_1h = fetch_history(symbol, "H1", mt5.TIMEFRAME_H1, bars=20000)
        df_4h = fetch_history(symbol, "H4", mt5.TIMEFRAME_H4, bars=5000)

        if df_1h is None:
            logger.error(f"Skipping {symbol} - no H1 data")
            continue

        # Add indicators
        logger.info(f"Computing indicators for {symbol}...")
        df_1h = add_indicators(df_1h)
        if df_4h is not None:
            df_4h = add_indicators(df_4h)

        # Drop rows with NaN indicators (warmup period)
        df_1h = df_1h.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        logger.info(f"{symbol} H1 after indicator warmup: {len(df_1h)} bars")

        # Run simple backtest first
        logger.info(f"\nRunning full-period backtest for {symbol}...")
        engine = BacktestEngine(starting_equity=500.0)
        bt_result = engine.run(df_1h, symbol, df_4h)

        logger.info(f"\n--- {symbol} Full Backtest Results ---")
        logger.info(f"Total trades: {bt_result.total_trades}")
        logger.info(f"Win rate: {bt_result.win_rate:.1f}%")
        logger.info(f"Profit factor: {bt_result.profit_factor:.2f}")
        logger.info(f"Total PnL (pips): {bt_result.total_pnl_pips:.1f}")
        logger.info(f"Total PnL (currency): {bt_result.total_pnl_currency:.2f}")
        logger.info(f"Max drawdown: {bt_result.max_drawdown_pct:.1f}%")
        logger.info(f"Avg score: {bt_result.avg_score:.1f}")

        if bt_result.trades:
            logger.info(f"\nTrade details:")
            for i, t in enumerate(bt_result.trades):
                logger.info(
                    f"  #{i+1}: {t.direction} entry={t.entry_price:.5f} "
                    f"exit={t.exit_price:.5f} pips={t.pnl_pips:+.1f} "
                    f"reason={t.exit_reason} score={t.score:.0f}"
                )

        # Run walk-forward
        logger.info(f"\nRunning walk-forward for {symbol}...")
        wf_result = run_walk_forward(
            df_1h, symbol, df_4h,
            train_months=6,
            test_months=2,
            starting_equity=500.0,
        )

        results[symbol] = {
            "backtest": bt_result,
            "walk_forward": wf_result,
        }

    mt5.shutdown()

    # Print summary
    logger.info(f"\n\n{'='*60}")
    logger.info("FINAL SUMMARY")
    logger.info(f"{'='*60}")

    for symbol, res in results.items():
        bt = res["backtest"]
        wf = res["walk_forward"]
        logger.info(f"\n{symbol}:")
        logger.info(f"  Backtest: {bt.total_trades} trades, "
                     f"WR={bt.win_rate:.0f}%, PF={bt.profit_factor:.2f}, "
                     f"PnL={bt.total_pnl_pips:+.1f} pips, "
                     f"MaxDD={bt.max_drawdown_pct:.1f}%")
        logger.info(f"  Walk-Forward: {wf.total_oos_trades} OOS trades, "
                     f"WR={wf.oos_win_rate:.0f}%, PF={wf.oos_profit_factor:.2f}, "
                     f"Positive windows={wf.oos_positive_windows}/{len(wf.windows)} "
                     f"({wf.oos_positive_window_pct:.0f}%)")

    # Send to Telegram
    try:
        import asyncio
        from telegram import Bot
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            bot = Bot(token=token)
            loop = asyncio.new_event_loop()

            lines = ["<b>\U0001F4CA Backtest Results</b>\n"]
            for symbol, res in results.items():
                bt = res["backtest"]
                wf = res["walk_forward"]
                emoji = "\u2705" if bt.profit_factor > 1.0 else "\u274C"
                lines.append(f"<b>{symbol}</b>")
                lines.append(f"  {emoji} {bt.total_trades} trades, "
                             f"WR={bt.win_rate:.0f}%, PF={bt.profit_factor:.2f}")
                lines.append(f"  PnL: {bt.total_pnl_pips:+.1f} pips, "
                             f"MaxDD: {bt.max_drawdown_pct:.1f}%")
                lines.append(f"  WF: {wf.oos_positive_windows}/{len(wf.windows)} "
                             f"positive OOS windows\n")

            loop.run_until_complete(bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode="HTML",
            ))
            logger.info("Results sent to Telegram")
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()
