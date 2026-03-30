"""
Telegram alerts: trade events, daily summary, errors.
Uses python-telegram-bot library (async).
"""

import logging
import asyncio
import queue
import threading
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

        # Background send queue — prevents blocking caller threads
        self._send_queue = queue.Queue()
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._sender_thread.start()

    def _send_loop(self):
        """Background thread that processes the send queue sequentially."""
        loop = asyncio.new_event_loop()
        while True:
            try:
                task = self._send_queue.get()
                if task is None:
                    break
                task_type = task[0]
                if task_type == "message":
                    _, text, parse_mode = task
                    loop.run_until_complete(
                        self.bot.send_message(
                            chat_id=self.chat_id,
                            text=text,
                            parse_mode=parse_mode,
                        )
                    )
                elif task_type == "photo":
                    _, photo_path, caption = task
                    with open(photo_path, "rb") as f:
                        loop.run_until_complete(
                            self.bot.send_photo(
                                chat_id=self.chat_id,
                                photo=f,
                                caption=caption,
                                parse_mode="HTML",
                            )
                        )
            except Exception as e:
                logger.error(f"Telegram send failed: {e}")

    def send_message(self, text: str, parse_mode: str = "HTML"):
        """Queue a message for background sending (non-blocking)."""
        if not self.bot:
            logger.debug(f"Telegram not configured, would send: {text[:100]}...")
            return
        self._send_queue.put(("message", text, parse_mode))

    def send_photo(self, photo_path: str, caption: str = None):
        """Queue a photo for background sending (non-blocking)."""
        if not self.bot:
            return
        self._send_queue.put(("photo", photo_path, caption))

    def alert_pattern_detected(self, symbol: str, direction: str, score: float, rrr: float, pattern_type: str = "HVF"):
        """Alert when a new pattern is detected and armed."""
        arrow = "\u2B06" if direction == "LONG" else "\u2B07"
        text = (
            f"<b>{arrow} {pattern_type} Pattern Detected</b>\n"
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
        pattern_type: str = "HVF",
    ):
        """Alert when a trade is executed."""
        arrow = "\u2B06" if direction == "LONG" else "\u2B07"
        text = (
            f"<b>{arrow} {pattern_type} Trade Opened</b>\n"
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
        """Send daily trading summary with equity chart."""
        daily_pnl = trade_logger.get_daily_pnl()

        # Count today's trades
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_trades = trade_logger.get_trades_closed_since(today_start)

        wins = sum(1 for t in today_trades if t.pnl and t.pnl > 0)
        losses = sum(1 for t in today_trades if t.pnl and t.pnl < 0)
        total = len(today_trades)

        open_trades = trade_logger.get_open_trades()
        armed_patterns = trade_logger.get_armed_patterns()

        # Build equity curve from all closed trades since go-live
        all_trades = trade_logger.get_all_closed_trades(since_date="2026-03-13")
        starting_equity = 700.0
        balance = starting_equity
        total_pnl = sum(t.pnl for t in all_trades if t.pnl)
        balance = starting_equity + total_pnl

        emoji = "\u2705" if daily_pnl >= 0 else "\u274C"
        text = (
            f"<b>\U0001F4CA Daily Summary</b>\n"
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"PnL today: <b>{emoji} ${daily_pnl:+.2f}</b>\n"
            f"Trades closed: {total} (W:{wins} L:{losses})\n"
            f"Open trades: {len(open_trades)}\n"
            f"Armed patterns: {len(armed_patterns)}\n\n"
            f"Balance: <b>${balance:,.2f}</b> ({total_pnl:+.2f} from $700)"
        )

        # Generate equity chart
        chart_path = self._generate_equity_chart(all_trades, starting_equity)
        if chart_path:
            self.send_photo(chart_path, caption=text)
        else:
            self.send_message(text)

    def _generate_equity_chart(self, trades, starting_equity: float):
        """Generate a small equity curve PNG. Returns file path or None."""
        if not trades:
            return None
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            import tempfile, os

            eq = [starting_equity]
            times = [trades[0].closed_at or trades[0].opened_at]
            for t in trades:
                eq.append(eq[-1] + (t.pnl or 0))
                times.append(t.closed_at or t.opened_at)

            fig, ax = plt.subplots(figsize=(8, 3.5))
            color = "#2196F3" if eq[-1] >= starting_equity else "#F44336"
            ax.plot(times, eq, color=color, linewidth=1.5)
            ax.fill_between(times, starting_equity, eq, alpha=0.15, color=color)
            ax.axhline(y=starting_equity, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)

            ax.set_title(
                f"Equity: ${eq[-1]:,.2f}  ({eq[-1] - starting_equity:+,.2f})",
                fontsize=11, fontweight="bold",
            )
            ax.set_ylabel("$", fontsize=9)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
            ax.tick_params(labelsize=8)
            ax.grid(True, alpha=0.2)
            plt.tight_layout()

            path = os.path.join(tempfile.gettempdir(), "hvf_equity.png")
            plt.savefig(path, dpi=120, bbox_inches="tight")
            plt.close()
            return path
        except Exception as e:
            logger.error(f"Equity chart generation failed: {e}")
            return None

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

    def send_performance_summary(self, trade_logger):
        """Send weekly performance summary with per-pattern breakdown."""
        trades = trade_logger.get_recent_closed_trades(limit=50)
        if not trades:
            return

        # Overall stats
        wins = [t for t in trades if t.pnl and t.pnl > 0]
        losses = [t for t in trades if t.pnl and t.pnl <= 0]
        total_pnl = sum(t.pnl for t in trades if t.pnl)
        total_pips = sum(t.pnl_pips for t in trades if t.pnl_pips)
        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.001
        pf = gross_profit / gross_loss
        wr = len(wins) / len(trades) * 100 if trades else 0

        # Per-pattern breakdown
        by_pattern = {}
        for t in trades:
            pt = t.pattern_type or "HVF"
            by_pattern.setdefault(pt, []).append(t)

        pattern_lines = []
        for pt, pt_trades in sorted(by_pattern.items()):
            pt_pnl = sum(t.pnl for t in pt_trades if t.pnl)
            pt_wins = sum(1 for t in pt_trades if t.pnl and t.pnl > 0)
            pattern_lines.append(
                f"  {pt}: {len(pt_trades)}T, {pt_wins}W, PnL {pt_pnl:+.2f}"
            )

        # Live vs backtest tracking
        slippage_trades = [t for t in trades if t.slippage is not None]
        if slippage_trades:
            avg_slip = sum(t.slippage for t in slippage_trades) / len(slippage_trades)
            max_slip = max(t.slippage for t in slippage_trades)
            # Convert to pips for readability
            slip_pips = [
                t.slippage / (0.01 if "JPY" in t.symbol else 0.0001)
                for t in slippage_trades
            ]
            avg_slip_pips = sum(slip_pips) / len(slip_pips)
            slip_section = (
                f"\n\n<b>Live vs Backtest:</b>\n"
                f"  Avg slippage: {avg_slip_pips:+.1f}p ({len(slippage_trades)}T)\n"
                f"  Max slippage: {max(slip_pips):+.1f}p"
            )
        else:
            slip_section = ""

        # Invalidation ratio from pattern records
        from hvf_trader.database.models import PatternRecord
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent_patterns = (
            trade_logger.session.query(PatternRecord)
            .filter(PatternRecord.detected_at >= cutoff)
            .all()
        )
        armed = sum(1 for p in recent_patterns if p.status in ("ARMED", "TRIGGERED", "EXPIRED"))
        triggered = sum(1 for p in recent_patterns if p.status == "TRIGGERED")
        expired = sum(1 for p in recent_patterns if p.status == "EXPIRED")
        if armed > 0:
            inval_section = (
                f"\n  Armed: {armed} | Triggered: {triggered} | Expired: {expired}"
                f"\n  Trigger rate: {triggered/armed*100:.0f}%"
            )
        else:
            inval_section = ""

        text = (
            f"<b>\U0001f4ca Weekly Performance</b>\n"
            f"Last {len(trades)} trades:\n"
            f"PnL: <b>{total_pnl:+.2f}</b> ({total_pips:+.1f}p)\n"
            f"WR: {wr:.0f}% | PF: {pf:.2f}\n\n"
            f"<b>By Pattern:</b>\n"
            + "\n".join(pattern_lines)
            + slip_section
            + inval_section
        )
        self.send_message(text)

    def alert_shutdown(self, reason: str = "Manual"):
        """Alert on bot shutdown."""
        text = (
            f"<b>\U0001F6D1 HVF Trader Stopped</b>\n"
            f"Reason: {reason}"
        )
        self.send_message(text)
