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
import math
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
    # Ticks (~60s each) to keep retrying a broker-rejected entry. IC's crypto
    # maintenance close has been observed to last ~4 min; 30 is generous cover
    # while still abandoning a signal well inside the same broker day.
    MAX_ENTRY_RETRIES = 30

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
        self._last_processed_date: str | None = None  # broker date of last processed CLOSED D1 bar
        # Entry-retry bookkeeping: a market order rejected by IC's crypto
        # maintenance close (retcode 10018 at the ~22:00 UTC rollover, which is
        # exactly when detection fires) must be retried, not dropped. Bounded so
        # a genuinely un-fillable signal can't spin order_send all day.
        self._entry_retry_date: str | None = None
        self._entry_retry_count: int = 0

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

        sym = self._cfg["instrument"]
        d1 = self._fetch_d1_bars(sym, count=self._cfg["entry_lookback_days"] + 30)
        if d1 is None or len(d1) < self._cfg["entry_lookback_days"] + 1:
            logger.warning("[BTC_DONCHIAN] Insufficient D1 data; waiting")
            return

        # Process each broker D1 bar as soon as it CLOSES — i.e. within one
        # poll of broker midnight (21:00/22:00 UTC by DST), not at 00:01 UTC.
        # The old 00:01-UTC gate entered 2-3h after the close the signal was
        # computed on; the 2026-07-02 honest re-backtest showed that lag cost
        # a third to half the edge (BTC 2023+: PF 2.59 at the close vs 1.76
        # lagged — scripts/btc_donchian_honest_bt.py).
        #
        # Bar timestamps are broker-time mislabeled as UTC, so the forming
        # bar is the one dated broker-"today"; the newest bar older than that
        # is the just-closed one (also correct across weekend gaps, where the
        # newest bar IS a closed Friday bar).
        last_bar = d1.iloc[-1]
        if last_bar.name.date() >= self._broker_today():
            if len(d1) < 2:
                return
            last_bar = d1.iloc[-2]
            prior_history = d1.iloc[:-2]
        else:
            prior_history = d1.iloc[:-1]
        last_bar_date = last_bar.name.date()
        closed_date_str = last_bar_date.isoformat()
        # Don't early-return when this bar's already been processed for
        # detection — the trailing-stop management below must run EVERY tick.
        # Its only modify attempt used to fire once/day at the D1 rollover
        # (~22:00 UTC), exactly when IC's crypto CFD is in its daily maintenance
        # close, so modify_stop_loss was rejected (retcode 10018 "Market
        # closed") and never retried until the next rollover — which also
        # fails. Net effect: the broker stop stayed stuck at the entry level
        # for the life of the position. Retrying each tick lets the trail apply
        # the moment the market reopens.
        already_processed = (self._last_processed_date == closed_date_str)

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

        # Manage the open position on EVERY tick (see note above) — the trail
        # target only changes daily, but re-attempting each poll means a modify
        # rejected during the rollover maintenance window is retried (and
        # succeeds) as soon as the market reopens. The guards inside
        # _manage_open_position no-op once the stop already sits at target.
        if self._open_trade_id is not None:
            self._manage_open_position(sym, last_bar, exit_high, exit_low, prior_history)
            self._save_state()

        if already_processed:
            return  # detection already ran for this closed bar

        # Detection
        entry_ok = True
        if self._open_trade_id is None:
            # Breakout entry
            if last_close > entry_high:
                entry_ok = self._attempt_entry(sym, "LONG", last_close, atr_val, last_bar_date)
            elif last_close < entry_low:
                entry_ok = self._attempt_entry(sym, "SHORT", last_close, atr_val, last_bar_date)
            else:
                logger.info(
                    "[BTC_DONCHIAN] %s no signal: close=%.2f entry_hi=%.2f entry_lo=%.2f atr=%.2f",
                    sym, last_close, entry_high, entry_low, atr_val,
                )

        # Only consume the signal once the broker has actually had its say.
        # Detection fires at the broker D1 rollover (~22:00 UTC), which is IC's
        # crypto maintenance close — measured live, order_send there returns
        # retcode 10018 for minutes. Marking the bar processed on a rejection
        # would DROP the trade outright (worse than the 2-3h entry lag this
        # gate was moved to avoid: a Donchian system earns from a handful of
        # trends). The trail already retries per-tick for the same reason; this
        # gives the entry the same treatment. Policy skips (circuit breaker,
        # portfolio gate, sub-minimum lots) still consume the signal.
        if not entry_ok:
            if self._entry_retry_date != closed_date_str:
                self._entry_retry_date = closed_date_str
                self._entry_retry_count = 0
            self._entry_retry_count += 1
            if self._entry_retry_count <= self.MAX_ENTRY_RETRIES:
                logger.warning(
                    "[BTC_DONCHIAN] %s entry rejected by broker; will retry "
                    "(%d/%d) on next tick — signal NOT consumed",
                    sym, self._entry_retry_count, self.MAX_ENTRY_RETRIES,
                )
                return  # leave _last_processed_date unset
            logger.error(
                "[BTC_DONCHIAN] %s entry still rejected after %d retries — "
                "abandoning the %s signal",
                sym, self.MAX_ENTRY_RETRIES, closed_date_str,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[BTC_DONCHIAN] entry abandoned</b>\n"
                    f"{sym}: broker rejected the {closed_date_str} signal "
                    f"{self.MAX_ENTRY_RETRIES}x — no position opened."
                )

        self._last_processed_date = closed_date_str
        self._save_state()

    @staticmethod
    def _broker_today():
        """Current broker-clock date. IC Markets runs UTC+2, UTC+3 during EU
        DST (last Sunday of March 01:00 UTC to last Sunday of October 01:00
        UTC). Wall-clock based — a stale weekend tick can't skew it."""
        now = datetime.now(timezone.utc)
        y = now.year
        mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
        mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
        oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
        oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
        offset = 3 if mar_last_sun <= now < oct_last_sun else 2
        return (now + timedelta(hours=offset)).date()

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
                       atr_val: float, signal_date) -> bool:
        """Portfolio-gate wrapper — entry logic in _inner.

        Returns False ONLY when the broker rejected the order (caller should
        retry without consuming the signal). Policy skips return True.
        """
        from hvf_trader.risk import portfolio_gate
        with portfolio_gate.reserve(symbol) as (gate_ok, gate_reason):
            if not gate_ok:
                logger.warning("[BTC_DONCHIAN] %s blocked by portfolio gate: %s",
                               symbol, gate_reason)
                if self._alerter:
                    from hvf_trader.alerts.telegram_bot import esc
                    self._alerter.send_message(
                        f"<b>[BTC_DONCHIAN] entry blocked</b>\n"
                        f"{symbol}: {esc(gate_reason)}")
                return True
            return self._attempt_entry_inner(symbol, direction, close_price,
                                             atr_val, signal_date)

    def _attempt_entry_inner(self, symbol: str, direction: str,
                             close_price: float, atr_val: float,
                             signal_date) -> bool:
        cfg = self._cfg
        # Circuit breakers
        if self._circuit_breaker.is_tripped:
            logger.info("[BTC_DONCHIAN] global breaker tripped, skipping")
            return True
        ok, reason = self._circuit_breaker.check_pattern(self.PATTERN_TYPE, symbol)
        if not ok:
            logger.info("[BTC_DONCHIAN] pattern breaker tripped: %s", reason)
            return True

        # Sizing
        account = self._connector.get_account_info()
        if not account:
            logger.error("[BTC_DONCHIAN] no account info; skipping entry")
            return True
        equity = account["equity"]

        # Anchor the stop to the price we are ABOUT to fill at, not the signal
        # D1 close. This is a fidelity fix, not a semantic change: the sim sets
        # stop = fill ± atr_mult × ATR, so risk is always exactly atr_mult × ATR.
        # Live used to anchor both the stop and the lot size to close_price
        # while filling at market seconds-to-hours later, so any adverse drift
        # went straight into real risk with nothing re-deriving it. Both live
        # trades over-risked: BTCUSD 1.39x, ETHUSD 1.53x intended (audit
        # 2026-07-28). The post-fill correction below closes the residual gap.
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.warning("[BTC_DONCHIAN] %s no tick; falling back to D1 close "
                           "as the entry anchor", symbol)
            ref_px = close_price
        else:
            ref_px = tick.ask if direction == "LONG" else tick.bid

        atr_mult = cfg["atr_stop_multiplier"]
        stop_dist = atr_mult * atr_val
        if stop_dist <= 0:
            logger.error("[BTC_DONCHIAN] invalid stop_dist=%.4f, skipping", stop_dist)
            return True
        stop_price = (ref_px - stop_dist if direction == "LONG"
                      else ref_px + stop_dist)

        # Lot sizing. DPP = account-currency dollars per 1.0 price unit per
        # 1.0 lot, read from the broker's own tick specs. This was hardcoded as
        # `risk_usd / stop_dist` — i.e. DPP == 1.0 — which is correct for
        # BTCUSD/ETHUSD (contract size 1) and ONLY for them. Extending the
        # universe to metals/indices (2026-07-29) makes that assumption
        # actively dangerous: XAUUSD is 100, so a 1% risk would have become
        # ~100% of equity on a single trade, and JP225 is ~0.0061, so it would
        # have traded silently at ~1/165th of intended size. Same family as the
        # "pips x $10" DO NOT in CLAUDE.md: never assume a value-per-point,
        # always read it from the instrument.
        risk_usd = equity * cfg["risk_pct"] / 100.0
        info = mt5.symbol_info(symbol)
        if info is not None and not info.visible:
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
        dpp = None
        if info is not None and info.trade_tick_size:
            dpp = info.trade_tick_value / info.trade_tick_size
        if not dpp or dpp <= 0:
            # Neither a policy skip nor a broker rejection — we simply cannot
            # size safely. Route it into the RETRYABLE bucket so a transient
            # Market Watch / spec glitch self-heals, bounded by
            # MAX_ENTRY_RETRIES with a Telegram alert on abandon. Sizing on a
            # guessed value-per-point is the one thing never to do here.
            logger.error(
                "[BTC_DONCHIAN] %s cannot derive value-per-point "
                "(tick_value=%s tick_size=%s) — refusing to size, will retry",
                symbol, getattr(info, "trade_tick_value", None),
                getattr(info, "trade_tick_size", None),
            )
            return False
        # round to broker step (0.01 lot for BTCUSD)
        raw_lots = risk_usd / (stop_dist * dpp)
        vol_step = info.volume_step or 0.01
        vol_min = info.volume_min or 0.01
        vol_max = info.volume_max or 10.0
        # FLOOR to the broker step — round() could size up to +20% over
        # intended risk, and clamping up to vol_min could 2x+ it (audit
        # 2026-07-02). Below-minimum sizing skips the trade, matching the
        # forex sizer's behavior. Epsilon guards float jitter at exact steps.
        lots = min(vol_max, math.floor(raw_lots / vol_step + 1e-9) * vol_step)
        lots = round(lots, 2)
        if lots < vol_min:
            logger.warning(
                "[BTC_DONCHIAN] %s raw lots %.4f below broker min %s — "
                "skipping entry (sizing up would exceed intended risk)",
                symbol, raw_lots, vol_min,
            )
            return True

        # Invariant: flooring to the broker step can only take realised risk
        # BELOW intended, never above. A violation means DPP is wrong for this
        # instrument — refuse the trade rather than discover it in the PnL.
        # This is the assertion that would have caught the crypto-only sizer
        # being pointed at gold, independently of whether the fix above is
        # right, so keep it even though it looks redundant.
        implied_risk = lots * stop_dist * dpp
        if implied_risk > risk_usd * 1.05:
            logger.error(
                "[BTC_DONCHIAN] %s sizing sanity FAILED: implied risk $%.2f > "
                "intended $%.2f (lots=%s dist=%.5f dpp=%.6g) — refusing entry",
                symbol, implied_risk, risk_usd, lots, stop_dist, dpp,
            )
            return True

        current_px = ref_px
        msg = (
            f"[BTC_DONCHIAN] {symbol} {direction} SIGNAL (D1 close={close_price:.2f}, "
            f"ATR={atr_val:.2f}, stop={stop_price:.2f}, dist={stop_dist:.5g}px, "
            f"lots={lots}, risk=${implied_risk:.2f} of ${risk_usd:.2f} intended, "
            f"dpp={dpp:.6g}, current={current_px:.2f})"
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
            return True

        # Place market order with broker-side initial SL, no TP
        result = self._order_manager.place_market_order(
            symbol=symbol, direction=direction, lot_size=lots,
            stop_loss=stop_price, take_profit=0.0,
            comment=self.PATTERN_TYPE, magic=cfg["magic"],
        )
        if not result:
            # Do NOT consume the signal — see the retry block in _tick.
            logger.error("[BTC_DONCHIAN] %s order_send failed (retryable)", symbol)
            return False
        ticket = result.get("ticket") or result.get("order_ticket")
        fill_price = result.get("fill_price", current_px)

        # Re-derive the stop from the ACTUAL fill so realised risk is exactly
        # atr_mult × ATR × lots. The order already carries a valid protective
        # stop, so there is no unprotected window; this only trims the residual
        # drift between the pre-trade tick and the fill. A failure here is
        # benign (the original stop stands) and self-heals on the next trail
        # tick, so it must not fail the entry.
        corrected_stop = (fill_price - stop_dist if direction == "LONG"
                          else fill_price + stop_dist)
        if abs(corrected_stop - stop_price) >= 0.01:
            if self._order_manager.modify_stop_loss(ticket, symbol, corrected_stop):
                logger.info(
                    "[BTC_DONCHIAN] %s stop re-anchored to fill: %.2f → %.2f "
                    "(fill %.2f vs pre-trade %.2f)",
                    symbol, stop_price, corrected_stop, fill_price, current_px,
                )
                stop_price = corrected_stop
            else:
                logger.warning(
                    "[BTC_DONCHIAN] %s could not re-anchor stop to fill "
                    "(keeping %.2f; risk ≈ $%.2f vs intended $%.2f)",
                    symbol, stop_price, abs(fill_price - stop_price) * lots,
                    stop_dist * lots,
                )

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
            "[BTC_DONCHIAN] %s %s FILLED: ticket=%s @ %.2f, SL=%.2f, lots=%s, "
            "risk=$%.2f",
            direction, symbol, ticket, fill_price, stop_price, lots,
            abs(fill_price - stop_price) * lots,
        )
        return True

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
            # Marker: last_processed_date holds the CLOSED BAR's broker date
            # (new gate semantics, 2026-07-02). Absent = legacy wall-date.
            "gate_semantics": "bar_date",
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
        # Migrate legacy state: the old gate stored the WALL date on which it
        # ran (00:01 UTC), i.e. the bar it processed was dated one day
        # earlier. Without this shift the first post-deploy rollover would be
        # silently skipped.
        if (self._last_processed_date
                and saved.get("gate_semantics") != "bar_date"):
            try:
                d = datetime.fromisoformat(self._last_processed_date).date()
                self._last_processed_date = (d - timedelta(days=1)).isoformat()
                logger.info(
                    "[BTC_DONCHIAN] migrated legacy gate state -> "
                    "last processed bar %s", self._last_processed_date,
                )
            except ValueError:
                self._last_processed_date = None
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
