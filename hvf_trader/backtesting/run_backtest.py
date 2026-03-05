"""
Run multi-pattern backtest on EURUSD and GBPUSD.
Pulls 2+ years of history from MT5, runs detection + backtest + walk-forward.
Compares HVF-only vs all-patterns performance.
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

ALL_PATTERNS = ["HVF", "VIPER", "KZ_HUNT", "LONDON_SWEEP"]


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


def run_single_backtest(df_1h, df_4h, symbol, equity, enabled_patterns, label):
    """Run backtest with specific pattern set and return result."""
    logger.info(f"\n--- {symbol} {label} ({', '.join(enabled_patterns)}) ---")
    engine = BacktestEngine(starting_equity=equity, enabled_patterns=enabled_patterns)
    result = engine.run(df_1h, symbol, df_4h)

    logger.info(f"Total trades: {result.total_trades}")
    logger.info(f"Win rate: {result.win_rate:.1f}%")
    logger.info(f"Profit factor: {result.profit_factor:.2f}")
    logger.info(f"Total PnL (pips): {result.total_pnl_pips:.1f}")
    logger.info(f"Total PnL (currency): {result.total_pnl_currency:.2f}")
    logger.info(f"Max drawdown: {result.max_drawdown_pct:.1f}%")
    logger.info(f"Avg score: {result.avg_score:.1f}")

    if result.trades:
        # Per-pattern breakdown
        by_type = {}
        for t in result.trades:
            pt = t.pattern_type
            if pt not in by_type:
                by_type[pt] = {"trades": [], "wins": 0, "pnl": 0.0}
            by_type[pt]["trades"].append(t)
            by_type[pt]["pnl"] += t.pnl_pips
            if t.pnl_pips > 0:
                by_type[pt]["wins"] += 1

        logger.info(f"\nPer-pattern breakdown:")
        for pt, data in sorted(by_type.items()):
            n = len(data["trades"])
            wr = data["wins"] / n * 100 if n > 0 else 0
            logger.info(f"  {pt}: {n} trades, WR={wr:.0f}%, PnL={data['pnl']:+.1f} pips")

        # Direction breakdown
        longs = [t for t in result.trades if t.direction == "LONG"]
        shorts = [t for t in result.trades if t.direction == "SHORT"]
        logger.info(f"\nDirection breakdown:")
        logger.info(f"  LONG:  {len(longs)} trades, "
                     f"PnL={sum(t.pnl_pips for t in longs):+.1f} pips")
        logger.info(f"  SHORT: {len(shorts)} trades, "
                     f"PnL={sum(t.pnl_pips for t in shorts):+.1f} pips")

        logger.info(f"\nTrade details:")
        for i, t in enumerate(result.trades):
            logger.info(
                f"  #{i+1}: [{t.pattern_type}] {t.direction} "
                f"entry={t.entry_price:.5f} exit={t.exit_price:.5f} "
                f"pips={t.pnl_pips:+.1f} reason={t.exit_reason} "
                f"score={t.score:.0f}"
            )

    return result


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

    for symbol in ["EURUSD", "GBPUSD"]:
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

        # ─── Run 1: HVF-only (baseline) ────────────────────────────
        hvf_result = run_single_backtest(
            df_1h, df_4h, symbol, 500.0, ["HVF"], "HVF-only"
        )

        # ─── Run 2: All patterns ────────────────────────────────────
        all_result = run_single_backtest(
            df_1h, df_4h, symbol, 500.0, ALL_PATTERNS, "All Patterns"
        )

        # ─── Walk-forward: skipped for now (run separately) ─────────
        results[symbol] = {
            "hvf_only": hvf_result,
            "all_patterns": all_result,
        }

    mt5.shutdown()

    # Print comparison summary
    logger.info(f"\n\n{'='*60}")
    logger.info("COMPARISON SUMMARY: HVF-only vs All Patterns")
    logger.info(f"{'='*60}")

    for symbol, res in results.items():
        hvf = res["hvf_only"]
        all_p = res["all_patterns"]

        logger.info(f"\n{symbol}:")
        logger.info(f"  HVF-only:      {hvf.total_trades} trades, "
                     f"WR={hvf.win_rate:.0f}%, PF={hvf.profit_factor:.2f}, "
                     f"PnL={hvf.total_pnl_pips:+.1f} pips, "
                     f"MaxDD={hvf.max_drawdown_pct:.1f}%")
        logger.info(f"  All Patterns:  {all_p.total_trades} trades, "
                     f"WR={all_p.win_rate:.0f}%, PF={all_p.profit_factor:.2f}, "
                     f"PnL={all_p.total_pnl_pips:+.1f} pips, "
                     f"MaxDD={all_p.max_drawdown_pct:.1f}%")

        # Improvement delta
        if hvf.total_trades > 0:
            trade_delta = all_p.total_trades - hvf.total_trades
            pnl_delta = all_p.total_pnl_pips - hvf.total_pnl_pips
            logger.info(f"  Delta:         {trade_delta:+d} trades, "
                         f"{pnl_delta:+.1f} pips")

    # Send to Telegram
    try:
        import asyncio
        from telegram import Bot
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            bot = Bot(token=token)
            loop = asyncio.new_event_loop()

            lines = ["<b>\U0001F4CA Multi-Pattern Backtest Results</b>\n"]
            for symbol, res in results.items():
                hvf = res["hvf_only"]
                all_p = res["all_patterns"]
                emoji = "\u2705" if all_p.profit_factor > 1.0 else "\u274C"

                lines.append(f"<b>{symbol}</b>")
                lines.append(f"  HVF-only: {hvf.total_trades}T, "
                             f"PF={hvf.profit_factor:.2f}, "
                             f"PnL={hvf.total_pnl_pips:+.1f}p")
                lines.append(f"  {emoji} All: {all_p.total_trades}T, "
                             f"PF={all_p.profit_factor:.2f}, "
                             f"PnL={all_p.total_pnl_pips:+.1f}p")

                # Per-pattern counts
                by_type = {}
                for t in all_p.trades:
                    by_type[t.pattern_type] = by_type.get(t.pattern_type, 0) + 1
                breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
                lines.append(f"  Breakdown: {breakdown}\n")

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
