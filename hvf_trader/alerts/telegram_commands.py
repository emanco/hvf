"""
Telegram command handler — interactive bot commands via polling.

Runs in a daemon thread, listens for commands from the authorized chat_id.
Commands: /status, /health, /trades, /equity, /balance, /help
"""

import logging
import threading
import time
from datetime import datetime, timezone

from hvf_trader import config

logger = logging.getLogger(__name__)

try:
    from telegram import Bot, Update
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Bot = None
    Update = None


class TelegramCommandHandler:
    """Polls for incoming Telegram messages and responds to commands."""

    def __init__(self, alerter, trade_logger, connector, armed_patterns_ref=None):
        """
        Args:
            alerter: TelegramAlerter instance (reuse its bot + chat_id)
            trade_logger: TradeLogger for querying trades/patterns
            connector: MT5Connector for account info
            armed_patterns_ref: reference to HVFTrader._armed_patterns list
        """
        self.alerter = alerter
        self.trade_logger = trade_logger
        self.connector = connector
        self._armed_ref = armed_patterns_ref or []
        self._running = False
        self._thread = None
        self._last_update_id = 0

    def start(self):
        if not TELEGRAM_AVAILABLE or not self.alerter.bot:
            logger.info("Telegram commands disabled (bot not configured)")
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Telegram command handler started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Telegram command handler stopped")

    def _poll_loop(self):
        """Long-poll for updates every 5 seconds."""
        import asyncio
        loop = asyncio.new_event_loop()

        while self._running:
            try:
                updates = loop.run_until_complete(
                    self.alerter.bot.get_updates(
                        offset=self._last_update_id + 1,
                        timeout=5,
                    )
                )
                for update in updates:
                    self._last_update_id = update.update_id
                    self._handle_update(update)
            except Exception as e:
                logger.debug(f"Telegram poll error: {e}")
                time.sleep(5)

    def _handle_update(self, update):
        """Process a single incoming update."""
        if not update.message or not update.message.text:
            return

        # Only respond to the authorized chat
        chat_id = str(update.message.chat_id)
        if chat_id != str(self.alerter.chat_id):
            return

        text = update.message.text.strip().lower()
        cmd = text.split()[0] if text else ""

        handlers = {
            "/status": self._cmd_status,
            "/health": self._cmd_health,
            "/trades": self._cmd_trades,
            "/equity": self._cmd_equity,
            "/balance": self._cmd_balance,
            "/help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                handler()
            except Exception as e:
                logger.error(f"Command {cmd} failed: {e}")
                self.alerter.send_message(f"<b>Error</b>\n<code>{e}</code>")

    def _cmd_help(self):
        text = (
            "<b>HVF Bot Commands</b>\n\n"
            "/status - Bot status overview\n"
            "/health - MT5 connection + account\n"
            "/trades - Open trades\n"
            "/equity - Equity chart since go-live\n"
            "/balance - Current balance + PnL\n"
            "/help - This message"
        )
        self.alerter.send_message(text)

    def _cmd_status(self):
        now = datetime.now(timezone.utc)
        open_trades = self.trade_logger.get_open_trades()
        armed = self.trade_logger.get_armed_patterns()
        daily_pnl = self.trade_logger.get_daily_pnl()
        weekly_pnl = self.trade_logger.get_weekly_pnl()

        # Count today's closed trades
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_trades = self.trade_logger.get_trades_closed_since(today_start)
        wins = sum(1 for t in today_trades if t.pnl and t.pnl > 0)
        losses = sum(1 for t in today_trades if t.pnl and t.pnl <= 0)

        mt5_status = "Connected" if self.connector.connected else "DISCONNECTED"

        emoji_d = "\u2705" if daily_pnl >= 0 else "\u274C"
        emoji_w = "\u2705" if weekly_pnl >= 0 else "\u274C"

        text = (
            f"<b>\U0001F4CA Bot Status</b>\n"
            f"Time: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"MT5: <b>{mt5_status}</b>\n"
            f"Open trades: <b>{len(open_trades)}</b>\n"
            f"Armed patterns: <b>{len(armed)}</b>\n\n"
            f"Today: {emoji_d} <b>${daily_pnl:+.2f}</b> ({len(today_trades)}T, W:{wins} L:{losses})\n"
            f"Week: {emoji_w} <b>${weekly_pnl:+.2f}</b>"
        )
        self.alerter.send_message(text)

    def _cmd_health(self):
        mt5_status = "Connected" if self.connector.connected else "DISCONNECTED"
        account = self.connector.get_account_info()

        if account:
            margin_level = account.get("margin_level", 0) or 0
            text = (
                f"<b>\U0001F3E5 Health Check</b>\n\n"
                f"MT5: <b>{mt5_status}</b>\n"
                f"Balance: <b>${account['balance']:,.2f}</b>\n"
                f"Equity: <b>${account['equity']:,.2f}</b>\n"
                f"Free margin: ${account['free_margin']:,.2f}\n"
                f"Margin level: {margin_level:.0f}%\n"
                f"Unrealised PnL: ${account['profit']:+.2f}"
            )
        else:
            text = (
                f"<b>\U0001F3E5 Health Check</b>\n\n"
                f"MT5: <b>{mt5_status}</b>\n"
                f"Account info unavailable"
            )
        self.alerter.send_message(text)

    def _cmd_trades(self):
        open_trades = self.trade_logger.get_open_trades()
        if not open_trades:
            self.alerter.send_message("<b>No open trades</b>")
            return

        lines = [f"<b>\U0001F4C8 Open Trades ({len(open_trades)})</b>\n"]
        for t in open_trades:
            ptype = t.pattern_type or "HVF"
            arrow = "\u2B06" if t.direction == "LONG" else "\u2B07"
            pnl_str = f"${t.pnl:+.2f}" if t.pnl else "n/a"
            lines.append(
                f"{arrow} <code>{t.symbol}</code> {t.direction} ({ptype})\n"
                f"   Entry: {t.entry_price:.5f} | SL: {t.stop_loss:.5f}\n"
                f"   PnL: {pnl_str}"
            )
        self.alerter.send_message("\n".join(lines))

    def _cmd_equity(self):
        """Send equity chart."""
        all_trades = self.trade_logger.get_all_closed_trades(since_date="2026-03-13")
        if not all_trades:
            self.alerter.send_message("<b>No closed trades yet</b>")
            return

        starting_equity = 700.0
        total_pnl = sum(t.pnl for t in all_trades if t.pnl)
        balance = starting_equity + total_pnl

        chart_path = self.alerter._generate_equity_chart(all_trades, starting_equity)
        if chart_path:
            caption = (
                f"<b>Equity: ${balance:,.2f}</b> ({total_pnl:+.2f} from $700)\n"
                f"Trades: {len(all_trades)}"
            )
            self.alerter.send_photo(chart_path, caption=caption)
        else:
            self.alerter.send_message(
                f"<b>Balance: ${balance:,.2f}</b> ({total_pnl:+.2f} from $700)"
            )

    def _cmd_balance(self):
        account = self.connector.get_account_info()
        all_trades = self.trade_logger.get_all_closed_trades(since_date="2026-03-13")
        total_pnl = sum(t.pnl for t in all_trades if t.pnl) if all_trades else 0
        trade_count = len(all_trades) if all_trades else 0
        wins = sum(1 for t in all_trades if t.pnl and t.pnl > 0) if all_trades else 0

        if account:
            balance = account["balance"]
            equity = account["equity"]
        else:
            balance = 700.0 + total_pnl
            equity = balance

        wr = (wins / trade_count * 100) if trade_count > 0 else 0

        text = (
            f"<b>\U0001F4B0 Balance</b>\n\n"
            f"Balance: <b>${balance:,.2f}</b>\n"
            f"Equity: <b>${equity:,.2f}</b>\n"
            f"Total PnL: <b>${total_pnl:+.2f}</b> (from $700)\n"
            f"Trades: {trade_count} (WR: {wr:.0f}%)"
        )
        self.alerter.send_message(text)
