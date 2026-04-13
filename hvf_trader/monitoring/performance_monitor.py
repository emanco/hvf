"""
Performance Monitor — rolling health metrics with Telegram alerts.

Computes per-pattern and per-symbol rolling PF, win rate, loss streaks,
rolling Sharpe ratio, and win rate decay.
Alerts via Telegram when thresholds are breached (with 24h cooldown).
Does NOT modify any config or pause trading.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

from hvf_trader import config

logger = logging.getLogger("hvf_trader")


class PerformanceMonitor:
    def __init__(self, trade_logger, alerter, circuit_breaker=None):
        self.trade_logger = trade_logger
        self.alerter = alerter
        self.circuit_breaker = circuit_breaker
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

        # Check rolling Sharpe ratio
        alerts.extend(self._check_rolling_sharpe())

        # Check win rate decay
        alerts.extend(self._check_wr_decay())

        # Kill switch: auto-halt if PF < threshold after enough trades
        alerts.extend(self._check_kill_switch())

        # Send alerts (with cooldown) — batch into a single message
        pending = [(k, t) for k, t in alerts if self._should_alert(k)]
        if pending and self.alerter:
            combined = "\n\n".join(t for _, t in pending)
            self.alerter.send_message(combined)
            for k, _ in pending:
                self._alert_cooldowns[k] = now

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

    def _check_rolling_sharpe(self):
        """Compute 60-day rolling Sharpe from per-trade returns.

        Sharpe = mean(returns) / std(returns) * sqrt(252 / avg_trades_per_day)
        Simplified: annualized from trade-level returns.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.PERF_SHARPE_WINDOW_DAYS)
        # Never include trades before the go-live date (pre-fix data is unreliable)
        go_live = datetime.fromisoformat(config.PERF_GO_LIVE_DATE).replace(tzinfo=timezone.utc)
        if cutoff < go_live:
            cutoff = go_live
        trades = self.trade_logger.get_trades_closed_since(cutoff)

        if len(trades) < 20:
            return []

        # Use pnl_pips as returns (currency-neutral, consistent across pairs)
        returns = [t.pnl_pips for t in trades if t.pnl_pips is not None]
        if len(returns) < 20:
            return []

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(variance) if variance > 0 else 0.001

        # Annualize: trades span N days, so trades_per_year = len / days * 252
        days_span = (trades[-1].closed_at - trades[0].closed_at).total_seconds() / 86400
        if days_span < 1:
            days_span = 1
        trades_per_year = len(returns) / days_span * 252
        sharpe = (mean_r / std_r) * math.sqrt(trades_per_year)

        alerts = []

        if sharpe < config.PERF_SHARPE_HALT_THRESHOLD:
            key = "sharpe_halt"
            text = (
                f"<b>\U0001f6a8 SHARPE CRITICAL</b>\n"
                f"Rolling {config.PERF_SHARPE_WINDOW_DAYS}d Sharpe: <b>{sharpe:.2f}</b>\n"
                f"{len(returns)} trades, avg {mean_r:+.1f}p/trade\n"
                f"<b>Recommendation: HALT TRADING</b>"
            )
            alerts.append((key, text))
        elif sharpe < config.PERF_SHARPE_WARN_THRESHOLD:
            key = "sharpe_warn"
            text = (
                f"<b>\u26a0\ufe0f Sharpe Warning</b>\n"
                f"Rolling {config.PERF_SHARPE_WINDOW_DAYS}d Sharpe: <b>{sharpe:.2f}</b>\n"
                f"{len(returns)} trades, avg {mean_r:+.1f}p/trade\n"
                f"<b>Recommendation: reduce position size</b>"
            )
            alerts.append((key, text))

        logger.info(
            "Rolling Sharpe: %.2f (%d trades, %dd window, avg %.1f pips/trade)",
            sharpe, len(returns), config.PERF_SHARPE_WINDOW_DAYS, mean_r,
        )
        return alerts

    def _check_wr_decay(self):
        """Compare recent win rate to all-time win rate."""
        all_trades = self.trade_logger.get_all_closed_trades(
            since_date=config.PERF_GO_LIVE_DATE
        )
        if len(all_trades) < 30:
            return []

        all_wr = sum(1 for t in all_trades if t.pnl and t.pnl > 0) / len(all_trades) * 100

        # Recent = last PERF_ROLLING_TRADE_COUNT trades
        recent = all_trades[-config.PERF_ROLLING_TRADE_COUNT:]
        recent_wr = sum(1 for t in recent if t.pnl and t.pnl > 0) / len(recent) * 100

        decay = all_wr - recent_wr

        alerts = []
        if decay >= config.PERF_WR_DECAY_THRESHOLD:
            key = "wr_decay"
            text = (
                f"<b>\u26a0\ufe0f Win Rate Decay</b>\n"
                f"All-time WR: {all_wr:.0f}%\n"
                f"Last {len(recent)} trades: {recent_wr:.0f}%\n"
                f"Decay: {decay:.0f}pp"
            )
            alerts.append((key, text))

        return alerts

    def _check_kill_switch(self):
        """Auto-halt trading if live PF < threshold after enough trades."""
        all_trades = self.trade_logger.get_all_closed_trades(
            since_date=config.PERF_GO_LIVE_DATE
        )
        if len(all_trades) < config.PERF_KILL_SWITCH_MIN_TRADES:
            return []

        wins = [t for t in all_trades if t.pnl and t.pnl > 0]
        losses = [t for t in all_trades if t.pnl and t.pnl <= 0]
        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.001
        pf = gross_profit / gross_loss

        if pf >= config.PERF_KILL_SWITCH_MIN_PF:
            return []

        # Trip the circuit breaker — no auto-resume (manual restart required)
        if self.circuit_breaker and not self.circuit_breaker.is_tripped:
            # Use a far-future resume date so it won't auto-reset
            far_future = datetime.now(timezone.utc) + timedelta(days=365)
            self.circuit_breaker._trip("MONTHLY", pf, far_future)
            logger.warning(
                "KILL SWITCH ACTIVATED: PF %.2f < %.2f after %d trades. Trading halted.",
                pf, config.PERF_KILL_SWITCH_MIN_PF, len(all_trades),
            )

        key = "kill_switch"
        text = (
            f"<b>\U0001f6a8 KILL SWITCH ACTIVATED</b>\n"
            f"Live PF: <b>{pf:.2f}</b> after {len(all_trades)} trades\n"
            f"Threshold: PF < {config.PERF_KILL_SWITCH_MIN_PF} @ {config.PERF_KILL_SWITCH_MIN_TRADES}+ trades\n"
            f"<b>Trading HALTED. Manual restart required.</b>"
        )
        return [(key, text)]

    def _should_alert(self, key):
        """Check cooldown — don't re-alert same issue within 24h."""
        last = self._alert_cooldowns.get(key)
        if last is None:
            return True
        hours_since = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return hours_since >= config.PERF_ALERT_COOLDOWN_HOURS
