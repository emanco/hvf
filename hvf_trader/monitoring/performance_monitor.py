"""
Performance Monitor — rolling health metrics with Telegram alerts.

Computes per-pattern and per-symbol rolling PF, win rate, and loss streaks.
Alerts via Telegram when thresholds are breached (with 24h cooldown).
Does NOT modify any config or pause trading.
"""

import logging
from datetime import datetime, timezone

from hvf_trader import config

logger = logging.getLogger("hvf_trader")


class PerformanceMonitor:
    def __init__(self, trade_logger, alerter):
        self.trade_logger = trade_logger
        self.alerter = alerter
        self._last_check = None
        self._alert_cooldowns = {}  # key -> last alert time

    def check_health(self):
        """Run all health checks. Called from main loop."""
        now = datetime.now(timezone.utc)
        if self._last_check and (now - self._last_check).total_seconds() < config.PERF_MONITOR_INTERVAL_SEC:
            return
        self._last_check = now

        # Skip if not enough trades yet
        if self.trade_logger.get_closed_trade_count() < config.PERF_ROLLING_TRADE_COUNT:
            return

        alerts = []

        # Check overall portfolio
        alerts.extend(self._check_rolling_metrics(label="Portfolio"))

        # Check per-pattern
        for pattern in config.ENABLED_PATTERNS:
            alerts.extend(self._check_rolling_metrics(pattern_type=pattern, label=pattern))

        # Check per-symbol
        for symbol in config.INSTRUMENTS:
            alerts.extend(self._check_rolling_metrics(symbol=symbol, label=symbol))

        # Check consecutive losses (portfolio-wide)
        alerts.extend(self._check_loss_streak())

        # Send alerts (with cooldown)
        for alert_key, alert_text in alerts:
            if self._should_alert(alert_key):
                self.alerter.send_message(alert_text)
                self._alert_cooldowns[alert_key] = now

    def _check_rolling_metrics(self, pattern_type=None, symbol=None, label=""):
        """Check rolling PF and win rate for a given filter."""
        trades = self.trade_logger.get_recent_closed_trades(
            limit=config.PERF_ROLLING_TRADE_COUNT,
            pattern_type=pattern_type,
            symbol=symbol,
        )
        if len(trades) < 10:  # Need at least 10 trades for meaningful stats
            return []

        alerts = []
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        # Profit Factor
        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.001
        pf = gross_profit / gross_loss

        if pf < config.PERF_MIN_PF_THRESHOLD:
            key = f"pf_{label}"
            text = (
                f"<b>\u26a0\ufe0f Performance Alert</b>\n"
                f"<b>{label}</b>: Rolling PF {pf:.2f} "
                f"(last {len(trades)} trades)\n"
                f"Threshold: {config.PERF_MIN_PF_THRESHOLD}"
            )
            alerts.append((key, text))

        # Win Rate
        win_rate = len(wins) / len(trades) * 100
        if win_rate < 40:  # Absolute floor — 40% WR is bare minimum
            key = f"wr_{label}"
            text = (
                f"<b>\u26a0\ufe0f Performance Alert</b>\n"
                f"<b>{label}</b>: Win rate {win_rate:.0f}% "
                f"(last {len(trades)} trades)"
            )
            alerts.append((key, text))

        return alerts

    def _check_loss_streak(self):
        """Check for consecutive losses across all trades."""
        trades = self.trade_logger.get_recent_closed_trades(
            limit=config.PERF_MAX_CONSECUTIVE_LOSSES + 5
        )
        streak = 0
        for t in trades:  # Most recent first
            if t.pnl <= 0:
                streak += 1
            else:
                break

        alerts = []
        if streak >= config.PERF_MAX_CONSECUTIVE_LOSSES:
            key = "loss_streak"
            text = (
                f"<b>\U0001f534 Loss Streak Alert</b>\n"
                f"{streak} consecutive losses\n"
                f"Review recommended"
            )
            alerts.append((key, text))
        return alerts

    def _should_alert(self, key):
        """Check cooldown — don't re-alert same issue within 24h."""
        last = self._alert_cooldowns.get(key)
        if last is None:
            return True
        hours_since = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return hours_since >= config.PERF_ALERT_COOLDOWN_HOURS
