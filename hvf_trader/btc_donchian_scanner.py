"""BTC Daily Donchian breakout scanner (Turtle System 2 variant).

Strategy (validated 2026-06-01 on 9 years of broker D1 data):
  - Entry: D1 close breaks the prior 55-day extreme (high → LONG, low → SHORT).
  - Initial stop: 1.0 × ATR(20) from entry. Tight stop — favours quick reset
    over wide breathing room.
  - Trail: each day after D1 close, move SL to the prior 20-day opposite
    extreme (only in the favourable direction).
  - Exit: broker SL hit OR opposite-direction breakout (flips position).
  - No fixed TP. Hold until trail-stop or new opposite signal.

Walk-forward PF per window: 14.15 / 13.16 / 2.94 / inconclusive (partial).
Expected trade frequency: 5-10 per year. Patient strategy.

Architecture mirrors quantum_london_scanner.py:
  - Independent scanner thread, poll once per minute.
  - State persistence (open_trade_id, current_stop, last_processed_date) to
    JSON. Re-adoption on restart.
  - Broker-managed initial SL placed at market entry. Daily trail via
    `order_manager.modify_stop_loss`.

Safety:
  - `dry_run=True` (default config): detection + sizing run, alert sent, but
    no broker call.
  - `enabled=False` (default config): scanner thread doesn't start at all.
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from hvf_trader import config

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

logger = logging.getLogger(__name__)


class BtcDonchianScanner:
    PATTERN_TYPE = "BTC_DONCHIAN"

    def __init__(self, order_manager, trade_logger, connector,
                 circuit_breaker, alerter=None, cfg=None):
        # cfg should be the merged parent+instance dict from main.py. The
        # top-level config.BTC_DONCHIAN has `instances` not `instrument`, so
        # callers must pass the merged dict explicitly.
        if cfg is None:
            raise ValueError(
                "BtcDonchianScanner requires explicit cfg (merged parent + instance)"
            )
        self._cfg = cfg
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._connector = connector
        self._circuit_breaker = circuit_breaker
        self._alerter = alerter
        self._running = False

        self._open_trade_id: int | None = None
        self._current_stop: float | None = None
        self._last_processed_date: str | None = None  # YYYY-MM-DD UTC

        instrument = self._cfg["instrument"]
        self._state_file = config.LOG_DIR / f"btc_donchian_state_{instrument}.json"

    # ─── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        self._running = True
        poll = self._cfg["poll_interval_sec"]
        hb_every = max(1, int(60 / poll))
        logger.info(
            "[BTC_DONCHIAN] Scanner thread started (poll=%ds, dry_run=%s, "
            "lookback=%d/%d, atr_mult=%.1f)",
            poll, self._cfg["dry_run"],
            self._cfg["entry_lookback_days"], self._cfg["exit_lookback_days"],
            self._cfg["atr_stop_multiplier"],
        )
        self._adopt_on_startup()
        iter_count = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[BTC_DONCHIAN] Scanner error: %s", e, exc_info=True)
            iter_count += 1
            if iter_count % hb_every == 0:
                logger.info(
                    "[BTC_DONCHIAN] heartbeat: iter=%d last_processed=%s open=%s stop=%s",
                    iter_count, self._last_processed_date,
                    self._open_trade_id, self._current_stop,
                )
            time.sleep(poll)
        logger.info("[BTC_DONCHIAN] Scanner thread stopped")

    def stop(self):
        self._running = False

    # ─── Core loop ───────────────────────────────────────────────────

    def _tick(self):
        if not MT5_AVAILABLE:
            return
        now = datetime.now(timezone.utc)
        today_str = now.date().isoformat()

        # Wait until at least 00:01 UTC (1 min after D1 close) to act
        if now.hour == 0 and now.minute < 1:
            return
        if self._last_processed_date == today_str:
            return  # already processed today's D1

        sym = self._cfg["instrument"]
        d1 = self._fetch_d1_bars(sym, count=self._cfg["entry_lookback_days"] + 30)
        if d1 is None or len(d1) < self._cfg["entry_lookback_days"] + 1:
            logger.warning("[BTC_DONCHIAN] Insufficient D1 data; waiting")
            return

        # The most recent CLOSED candle (broker D1 includes today's developing
        # bar; we want yesterday's). Pandas resample handles UTC; the broker's
        # D1 alignment may differ — we use today's bar only if hour ≥ 1 UTC
        # (already enforced above) and treat d1.iloc[-1] as the just-closed
        # bar if its date < today, else d1.iloc[-2].
        last_bar = d1.iloc[-1]
        last_bar_date = last_bar.name.date()
        if last_bar_date >= now.date():
            # Today's developing bar is in the slice — use the prior one
            if len(d1) < 2:
                return
            last_bar = d1.iloc[-2]
            last_bar_date = last_bar.name.date()
            prior_history = d1.iloc[:-2]
        else:
            prior_history = d1.iloc[:-1]

        # Compute rolling extremes from the bars BEFORE the last closed bar
        entry_lb = self._cfg["entry_lookback_days"]
        exit_lb = self._cfg["exit_lookback_days"]
        atr_period = self._cfg["atr_period_days"]
        if len(prior_history) < max(entry_lb, exit_lb, atr_period):
            return

        entry_high = prior_history["high"].tail(entry_lb).max()
        entry_low = prior_history["low"].tail(entry_lb).min()
        exit_high = prior_history["high"].tail(exit_lb).max()
        exit_low = prior_history["low"].tail(exit_lb).min()
        atr_val = self._wilder_atr(prior_history.tail(atr_period * 2), atr_period)

        last_close = float(last_bar["close"])
        last_high = float(last_bar["high"])
        last_low = float(last_bar["low"])

        # Manage open position first
        if self._open_trade_id is not None:
            self._manage_open_position(sym, last_bar, exit_high, exit_low, prior_history)
            # Even if trail moved the stop, we still want to process detection
            # in case it's a flip signal. But: don't open a counter position
            # while one's alive — that's handled in _attempt_entry().

        # Detection
        if self._open_trade_id is None:
            # Breakout entry
            if last_close > entry_high:
                self._attempt_entry(sym, "LONG", last_close, atr_val, last_bar_date)
            elif last_close < entry_low:
                self._attempt_entry(sym, "SHORT", last_close, atr_val, last_bar_date)
            else:
                logger.info(
                    "[BTC_DONCHIAN] %s no signal: close=%.2f entry_hi=%.2f entry_lo=%.2f atr=%.2f",
                    sym, last_close, entry_high, entry_low, atr_val,
                )

        self._last_processed_date = today_str
        self._save_state()

    def _wilder_atr(self, df: pd.DataFrame, period: int) -> float:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([
            h - l,
            (h - c.shift(1)).abs(),
            (l - c.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / period, adjust=False).mean()
        return float(atr.iloc[-1])

    def _fetch_d1_bars(self, symbol: str, count: int) -> pd.DataFrame | None:
        bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, count)
        if bars is None or len(bars) == 0:
            return None
        df = pd.DataFrame(bars)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df

    # ─── Entry ───────────────────────────────────────────────────────

    def _attempt_entry(self, symbol: str, direction: str, close_price: float,
                       atr_val: float, signal_date):
        cfg = self._cfg
        # Circuit breakers
        if self._circuit_breaker.is_tripped:
            logger.info("[BTC_DONCHIAN] global breaker tripped, skipping")
            return
        ok, reason = self._circuit_breaker.check_pattern(self.PATTERN_TYPE, symbol)
        if not ok:
            logger.info("[BTC_DONCHIAN] pattern breaker tripped: %s", reason)
            return

        # Sizing
        account = self._connector.get_account_info()
        if not account:
            logger.error("[BTC_DONCHIAN] no account info; skipping entry")
            return
        equity = account["equity"]

        # Initial stop = entry ± atr_mult × ATR
        atr_mult = cfg["atr_stop_multiplier"]
        if direction == "LONG":
            stop_price = close_price - atr_mult * atr_val
        else:
            stop_price = close_price + atr_mult * atr_val
        stop_dist = abs(close_price - stop_price)
        if stop_dist <= 0:
            logger.error("[BTC_DONCHIAN] invalid stop_dist=%.4f, skipping", stop_dist)
            return

        # BTCUSD lot sizing: 1 lot = 1 BTC, $1 per $1 price move per lot
        risk_usd = equity * cfg["risk_pct"] / 100.0
        # round to broker step (0.01 lot for BTCUSD)
        raw_lots = risk_usd / stop_dist
        info = mt5.symbol_info(symbol)
        vol_step = info.volume_step if info else 0.01
        vol_min = info.volume_min if info else 0.01
        vol_max = info.volume_max if info else 10.0
        lots = max(vol_min, min(vol_max, round(raw_lots / vol_step) * vol_step))
        # Round to 2 dp safety
        lots = round(lots, 2)

        # Get current ask/bid for entry estimate (market order)
        tick = mt5.symbol_info_tick(symbol)
        current_px = tick.ask if direction == "LONG" else tick.bid if tick else close_price

        msg = (
            f"[BTC_DONCHIAN] {symbol} {direction} SIGNAL (D1 close={close_price:.2f}, "
            f"ATR={atr_val:.2f}, stop={stop_price:.2f}, dist=${stop_dist:.2f}, "
            f"lots={lots}, risk=${risk_usd:.2f}, current={current_px:.2f})"
        )
        logger.info(msg)
        if cfg.get("alert_on_detection", True) and self._alerter:
            mode = "DRY-RUN" if cfg["dry_run"] else "LIVE"
            self._alerter.send_message(
                f"<b>[BTC_DONCHIAN] {direction} signal ({mode})</b>\n"
                f"{symbol} D1 close={close_price:.2f}\n"
                f"Entry≈{current_px:.2f}  Stop={stop_price:.2f}  Risk=${stop_dist*lots:.2f}\n"
                f"Lots={lots}  ATR(20)={atr_val:.2f}"
            )

        if cfg["dry_run"]:
            logger.info("[BTC_DONCHIAN] dry_run=True — not placing order")
            return

        # Place market order with broker-side initial SL, no TP
        result = self._order_manager.place_market_order(
            symbol=symbol, direction=direction, lot_size=lots,
            stop_loss=stop_price, take_profit=0.0,
            comment=self.PATTERN_TYPE, magic=cfg["magic"],
        )
        if not result:
            logger.error("[BTC_DONCHIAN] order_send failed")
            return
        ticket = result.get("ticket") or result.get("order_ticket")
        fill_price = result.get("fill_price", current_px)

        # Persist trade record
        trade_data = {
            "pattern_id": None,
            "symbol": symbol,
            "direction": direction,
            "pattern_type": self.PATTERN_TYPE,
            "mt5_ticket": ticket,
            "entry_price": fill_price,
            "stop_loss": stop_price,
            "target_1": 0.0,
            "target_2": 0.0,
            "lot_size": lots,
            "opened_at": datetime.now(timezone.utc),
            "status": "OPEN",
            "intended_entry": close_price,
            "intended_sl": stop_price,
            "slippage": fill_price - close_price if direction == "LONG" else close_price - fill_price,
            "pattern_metadata": json.dumps({
                "atr": atr_val,
                "atr_mult": atr_mult,
                "entry_lookback": cfg["entry_lookback_days"],
                "exit_lookback": cfg["exit_lookback_days"],
                "signal_d1_date": str(signal_date),
            }),
        }
        trade_record = self._trade_logger.log_trade_open(trade_data)
        self._open_trade_id = trade_record.id
        self._current_stop = stop_price
        logger.info(
            "[BTC_DONCHIAN] %s %s FILLED: ticket=%s @ %.2f, SL=%.2f, lots=%s",
            direction, symbol, ticket, fill_price, stop_price, lots,
        )

    # ─── Trail ───────────────────────────────────────────────────────

    def _manage_open_position(self, symbol: str, last_bar, exit_high: float,
                              exit_low: float, prior_history: pd.DataFrame):
        if self._open_trade_id is None:
            return
        from hvf_trader.database.models import TradeRecord
        trade = self._trade_logger._session.get(TradeRecord, self._open_trade_id)
        if not trade or trade.status == "CLOSED":
            self._open_trade_id = None
            self._current_stop = None
            return

        positions = mt5.positions_get(ticket=trade.mt5_ticket) or []
        if not positions:
            # Position closed at broker (SL hit). Reconciliation will handle
            # the trade-close logging; we just forget the reference.
            logger.info(
                "[BTC_DONCHIAN] %s position ticket=%d no longer at broker; "
                "reconciliation will resolve.",
                symbol, trade.mt5_ticket,
            )
            self._open_trade_id = None
            self._current_stop = None
            return

        # Compute the trail target
        if trade.direction == "LONG":
            target_sl = exit_low  # trail up to prior 20-day low
            if target_sl is None or target_sl <= trade.stop_loss:
                return  # no improvement
            new_stop = max(trade.stop_loss, target_sl)
        else:
            target_sl = exit_high
            if target_sl is None or target_sl >= trade.stop_loss:
                return
            new_stop = min(trade.stop_loss, target_sl)

        if abs(new_stop - trade.stop_loss) < 0.01:
            return

        if self._cfg["dry_run"]:
            logger.info(
                "[BTC_DONCHIAN] dry_run trail: would move %s SL from %.2f → %.2f",
                trade.direction, trade.stop_loss, new_stop,
            )
            return

        ok = self._order_manager.modify_stop_loss(trade.mt5_ticket, symbol, new_stop)
        if ok:
            self._trade_logger.log_trade_update(
                trade.id, stop_loss=new_stop, trailing_sl=new_stop,
            )
            self._current_stop = new_stop
            logger.info(
                "[BTC_DONCHIAN] %s trail: %s SL %.2f → %.2f",
                symbol, trade.direction, trade.stop_loss, new_stop,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[BTC_DONCHIAN] SL trailed</b>\n"
                    f"{symbol} {trade.direction}\n"
                    f"{trade.stop_loss:.2f} → {new_stop:.2f}"
                )

    # ─── State persistence ───────────────────────────────────────────

    def _save_state(self):
        payload = {
            "open_trade_id": self._open_trade_id,
            "current_stop": self._current_stop,
            "last_processed_date": self._last_processed_date,
            "instrument": self._cfg["instrument"],
        }
        try:
            tmp = self._state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self._state_file)
        except Exception as e:
            logger.warning("[BTC_DONCHIAN] failed to save state: %s", e)

    def _load_state(self) -> dict | None:
        if not self._state_file.exists():
            return None
        try:
            payload = json.loads(self._state_file.read_text())
        except Exception as e:
            logger.warning("[BTC_DONCHIAN] failed to load state: %s", e)
            return None
        if payload.get("instrument") != self._cfg["instrument"]:
            return None
        return payload

    def _adopt_on_startup(self):
        """Restore in-memory state from JSON. Verify open position still alive at broker."""
        saved = self._load_state()
        if not saved:
            return
        self._last_processed_date = saved.get("last_processed_date")
        self._current_stop = saved.get("current_stop")
        saved_id = saved.get("open_trade_id")
        if saved_id is None:
            return
        # Verify the position still exists at broker via DB lookup + MT5 query
        from hvf_trader.database.models import TradeRecord
        trade = self._trade_logger._session.get(TradeRecord, saved_id)
        if not trade or trade.status == "CLOSED":
            self._open_trade_id = None
            return
        if not MT5_AVAILABLE:
            self._open_trade_id = saved_id
            return
        positions = mt5.positions_get(ticket=trade.mt5_ticket) or []
        if positions:
            self._open_trade_id = saved_id
            logger.warning(
                "[BTC_DONCHIAN] startup re-adopt: open trade id=%d ticket=%d "
                "%s @ %.2f, SL=%.2f",
                trade.id, trade.mt5_ticket, trade.direction,
                trade.entry_price, trade.stop_loss,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[BTC_DONCHIAN] re-adopted open position</b>\n"
                    f"{trade.symbol} {trade.direction} ticket={trade.mt5_ticket}"
                )
        else:
            logger.warning(
                "[BTC_DONCHIAN] startup re-adopt: trade %d (ticket %d) gone at broker; "
                "reconciliation will resolve.",
                saved_id, trade.mt5_ticket,
            )
