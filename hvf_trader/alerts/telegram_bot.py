"""
Telegram alerts: trade events, daily summary, errors.
Uses python-telegram-bot library (async).
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

from hvf_trader import config

logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Bot = None


class TelegramAlerter:
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.bot = None
        self._loop = None

        if TELEGRAM_AVAILABLE and self.token and self.chat_id:
            self.bot = Bot(token=self.token)

    def _get_loop(self):
        """Get or create an event loop for sync contexts."""
        try:
            loop = asyncio.get_running_loop()
            return loop
        except RuntimeError:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            return self._loop

    def send_message(self, text: str, parse_mode: str = "HTML"):
        """Send a message synchronously (blocking)."""
        if not self.bot:
            logger.debug(f"Telegram not configured, would send: {text[:100]}...")
            return

        try:
            loop = self._get_loop()
            loop.run_until_complete(
                self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode,
                )
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def alert_pattern_detected(self, symbol: str, direction: str, score: float, rrr: float):
        """Alert when a new HVF pattern is detected and armed."""
        arrow = "\u2B06" if direction == "LONG" else "\u2B07"
        text = (
            f"<b>{arrow} HVF Pattern Detected</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Direction: <b>{direction}</b>\n"
            f"Score: <b>{score:.0f}/100</b>\n"
            f"RRR: <b>{rrr:.1f}:1</b>\n"
            f"Status: Armed, waiting for confirmation"
        )
        self.send_message(text)

    def alert_trade_opened(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        entry_price: float,
        stop_loss: float,
        target_1: float,
        target_2: float,
    ):
        """Alert when a trade is executed."""
        arrow = "\u2B06" if direction == "LONG" else "\u2B07"
        text = (
            f"<b>{arrow} Trade Opened</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Direction: <b>{direction}</b>\n"
            f"Lots: <b>{lot_size}</b>\n"
            f"Entry: <code>{entry_price:.5f}</code>\n"
            f"SL: <code>{stop_loss:.5f}</code>\n"
            f"TP1: <code>{target_1:.5f}</code>\n"
            f"TP2: <code>{target_2:.5f}</code>"
        )
        self.send_message(text)

    def alert_partial_close(
        self, symbol: str, direction: str, close_price: float, pnl_pips: float
    ):
        """Alert when a partial close occurs."""
        text = (
            f"<b>\u2705 Partial Close</b>\n"
            f"Symbol: <code>{symbol}</code> ({direction})\n"
            f"Close Price: <code>{close_price:.5f}</code>\n"
            f"Pips: <b>{pnl_pips:+.1f}</b>\n"
            f"SL moved to breakeven"
        )
        self.send_message(text)

    def alert_trade_closed(
        self,
        symbol: str,
        direction: str,
        close_price: float,
        pnl: float,
        pnl_pips: float,
        reason: str,
    ):
        """Alert when a trade is fully closed."""
        emoji = "\u2705" if pnl >= 0 else "\u274C"
        text = (
            f"<b>{emoji} Trade Closed</b>\n"
            f"Symbol: <code>{symbol}</code> ({direction})\n"
            f"Close: <code>{close_price:.5f}</code>\n"
            f"PnL: <b>{pnl:+.2f}</b>\n"
            f"Pips: <b>{pnl_pips:+.1f}</b>\n"
            f"Reason: {reason}"
        )
        self.send_message(text)

    def alert_circuit_breaker(self, level: str, loss_pct: float, resumes_at: datetime):
        """Alert when a circuit breaker trips."""
        text = (
            f"<b>\u26A0 Circuit Breaker Tripped</b>\n"
            f"Level: <b>{level}</b>\n"
            f"Loss: <b>{loss_pct:.1f}%</b>\n"
            f"Trading paused until: {resumes_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self.send_message(text)

    def alert_error(self, error_msg: str):
        """Alert on critical errors."""
        text = (
            f"<b>\U0001F6A8 Error</b>\n"
            f"<code>{error_msg[:500]}</code>"
        )
        self.send_message(text)

    def send_daily_summary(self, trade_logger):
        """Send daily trading summary."""
        daily_pnl = trade_logger.get_daily_pnl()

        # Count today's trades
        from hvf_trader.database.models import get_session, TradeRecord
        from datetime import timedelta
        session = get_session()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_trades = (
            session.query(TradeRecord)
            .filter(TradeRecord.closed_at >= today_start)
            .all()
        )
        session.close()

        wins = sum(1 for t in today_trades if t.pnl and t.pnl > 0)
        losses = sum(1 for t in today_trades if t.pnl and t.pnl < 0)
        total = len(today_trades)

        open_trades = trade_logger.get_open_trades()
        armed_patterns = trade_logger.get_armed_patterns()

        emoji = "\u2705" if daily_pnl >= 0 else "\u274C"
        text = (
            f"<b>\U0001F4CA Daily Summary</b>\n"
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"PnL: <b>{emoji} {daily_pnl:+.2f}</b>\n"
            f"Trades closed: {total} (W:{wins} L:{losses})\n"
            f"Open trades: {len(open_trades)}\n"
            f"Armed patterns: {len(armed_patterns)}"
        )
        self.send_message(text)

    def alert_startup(self):
        """Alert on bot startup."""
        text = (
            f"<b>\U0001F680 HVF Trader Started</b>\n"
            f"Environment: <b>{config.ENVIRONMENT}</b>\n"
            f"Instruments: {', '.join(config.INSTRUMENTS)}\n"
            f"Risk: {config.RISK_PCT}% per trade\n"
            f"Max concurrent: {config.MAX_CONCURRENT_TRADES}"
        )
        self.send_message(text)

    def alert_shutdown(self, reason: str = "Manual"):
        """Alert on bot shutdown."""
        text = (
            f"<b>\U0001F6D1 HVF Trader Stopped</b>\n"
            f"Reason: {reason}"
        )
        self.send_message(text)
