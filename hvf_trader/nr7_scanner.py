"""NR7 breakout scanner for equity indices.

Strategy (validated 2026-06-05 across US500, DE40, JP225, UK100):
  - If today's D1 range is the narrowest of the last 7 days → NR7 day.
  - Place BUY_STOP at today's high, SELL_STOP at today's low for tomorrow.
  - Whichever fills becomes the trade; cancel the survivor.
  - Initial SL: 1× ATR(14) from entry.
  - Trail SL daily after each D1 close, to the prior 10-day opposite extreme.
  - No fixed TP — hold until trail SL or new opposite breakout.

Walk-forward PF across 14 years on all 4 indices: 4.04 → 5.74.
Friction-robust: PF still 3.92 at 10x assumed broker cost on US500.

Architecture mirrors btc_donchian_scanner.py with added pending-stop
bracket management (similar to ASB).
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from hvf_trader import config

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

logger = logging.getLogger(__name__)


class Nr7Scanner:
    PATTERN_TYPE = "NR7_BREAKOUT"

    def __init__(self, order_manager, trade_logger, connector,
                 circuit_breaker, alerter=None, cfg=None):
        if cfg is None:
            raise ValueError("Nr7Scanner requires explicit cfg")
        self._cfg = cfg
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._connector = connector
        self._circuit_breaker = circuit_breaker
        self._alerter = alerter
        self._running = False

        # State persisted to JSON
        self._open_trade_id: int | None = None
        self._current_stop: float | None = None
        self._buy_stop_ticket: int | None = None
        self._sell_stop_ticket: int | None = None
        self._nr_day_high: float | None = None
        self._nr_day_low: float | None = None
        self._initial_stop_dist: float | None = None
        self._last_processed_date: str | None = None

        instrument = self._cfg["instrument"]
        self._state_file = config.LOG_DIR / f"nr7_state_{instrument}.json"

    # ─── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        self._running = True
        poll = self._cfg["poll_interval_sec"]
        hb_every = max(1, int(60 / poll))
        logger.info(
            "[NR7] Scanner thread started: %s (poll=%ds, nr_lb=%d, atr_mult=%.1f, "
            "exit_lb=%d, risk=%.2f%%)",
            self._cfg["instrument"], poll,
            self._cfg["nr_lookback"], self._cfg["atr_stop_multiplier"],
            self._cfg["exit_lookback_days"], self._cfg["risk_pct"],
        )
        self._adopt_on_startup()
        iter_count = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[NR7] %s scanner error: %s", self._cfg["instrument"],
                             e, exc_info=True)
            iter_count += 1
            if iter_count % hb_every == 0:
                logger.info(
                    "[NR7] %s heartbeat: iter=%d last_proc=%s open=%s "
                    "pending(B/S)=%s/%s stop=%s",
                    self._cfg["instrument"], iter_count,
                    self._last_processed_date, self._open_trade_id,
                    self._buy_stop_ticket, self._sell_stop_ticket, self._current_stop,
                )
            time.sleep(poll)
        logger.info("[NR7] Scanner stopped: %s", self._cfg["instrument"])

    def stop(self):
        self._running = False

    # ─── Core ────────────────────────────────────────────────────────

    def _tick(self):
        if not MT5_AVAILABLE:
            return
        now = datetime.now(timezone.utc)
        sym = self._cfg["instrument"]

        # Intraday: if both pendings exist, watch for fill
        if self._buy_stop_ticket or self._sell_stop_ticket:
            self._check_pending_fills(sym)

        # Once per day: after midnight UTC + 1 min buffer for D1 settle
        today_str = now.date().isoformat()
        if now.hour == 0 and now.minute < 1:
            return
        if self._last_processed_date == today_str:
            return

        # 1) Manage open trade — trail SL
        if self._open_trade_id is not None:
            self._trail_open_trade(sym)

        # 2) If neither open trade nor pendings: check yesterday's NR7
        if (self._open_trade_id is None and
                self._buy_stop_ticket is None and
                self._sell_stop_ticket is None):
            self._attempt_nr7_bracket(sym)

        self._last_processed_date = today_str
        self._save_state()

    # ─── NR7 detection + bracket placement ──────────────────────────

    def _attempt_nr7_bracket(self, sym: str):
        cfg = self._cfg
        nr_lb = cfg["nr_lookback"]
        atr_period = cfg["atr_period"]

        # Need enough history for NR + ATR
        bars = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0,
                                        nr_lb + atr_period + 20)
        if bars is None or len(bars) < nr_lb + atr_period:
            logger.warning("[NR7] %s: insufficient D1 data", sym)
            return
        df = pd.DataFrame(bars)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")

        # Strip any developing-today bar
        now = datetime.now(timezone.utc)
        if df.index[-1].date() >= now.date():
            df = df.iloc[:-1]
        if len(df) < nr_lb + atr_period:
            return

        last_bar = df.iloc[-1]
        last_range = float(last_bar["high"] - last_bar["low"])
        recent_min = float(df["range_calc"].iloc[-nr_lb:].min()) if "range_calc" in df.columns else \
                     float((df["high"] - df["low"]).iloc[-nr_lb:].min())

        if last_range > recent_min + 1e-9:
            logger.info("[NR7] %s no signal: range=%.2f recent_min=%.2f",
                        sym, last_range, recent_min)
            return

        # NR7 confirmed. Compute ATR.
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift(1)).abs(),
                        (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1/atr_period, adjust=False).mean().iloc[-1])

        # Circuit breakers
        if self._circuit_breaker.is_tripped:
            logger.info("[NR7] %s: global breaker tripped", sym)
            return
        ok, reason = self._circuit_breaker.check_pattern(self.PATTERN_TYPE, sym)
        if not ok:
            logger.info("[NR7] %s: pattern breaker tripped: %s", sym, reason)
            return

        nr_high = float(last_bar["high"])
        nr_low = float(last_bar["low"])
        atr_mult = cfg["atr_stop_multiplier"]

        # Stops are placed AT the NR day's H/L; SL = ATR cushion past entry
        long_sl = nr_high - atr_mult * atr
        short_sl = nr_low + atr_mult * atr

        # Sizing — 1% of equity / stop distance / $/point
        account = self._connector.get_account_info()
        if not account:
            logger.error("[NR7] %s: no account info", sym)
            return
        equity = account["equity"]
        risk_usd = equity * cfg["risk_pct"] / 100.0

        # dollar-per-point from broker's tick_value/tick_size
        sinfo = mt5.symbol_info(sym)
        if sinfo is None:
            logger.error("[NR7] %s: symbol_info None", sym)
            return
        if not sinfo.visible:
            mt5.symbol_select(sym, True)
            sinfo = mt5.symbol_info(sym)
        # Each broker reports tick_value per tick of price for 1 lot.
        # We need $/price-unit: tick_value / tick_size.
        if sinfo.trade_tick_size > 0:
            dollar_per_point = sinfo.trade_tick_value / sinfo.trade_tick_size
        else:
            dollar_per_point = 1.0
        if dollar_per_point <= 0:
            logger.error("[NR7] %s: dollar_per_point=0 (broker tick_value missing)", sym)
            return

        stop_dist = atr_mult * atr
        raw_lots = risk_usd / (stop_dist * dollar_per_point)
        vol_step = sinfo.volume_step
        vol_min = sinfo.volume_min
        vol_max = sinfo.volume_max
        lots = round(raw_lots / vol_step) * vol_step
        lots = max(vol_min, min(vol_max, lots))
        # Round to handle floating-point step jitter
        lots = round(lots, 4)

        logger.info(
            "[NR7] %s SIGNAL: NR_day H=%.2f L=%.2f range=%.2f ATR=%.2f "
            "buy_stop=%.2f sell_stop=%.2f SL_long=%.2f SL_short=%.2f "
            "lots=%g risk=$%.2f",
            sym, nr_high, nr_low, last_range, atr,
            nr_high, nr_low, long_sl, short_sl, lots, risk_usd,
        )
        if self._alerter and cfg.get("alert_on_detection", True):
            self._alerter.send_message(
                f"<b>[NR7] {sym} bracket placed</b>\n"
                f"NR-day H={nr_high:.2f}  L={nr_low:.2f}  range={last_range:.2f}\n"
                f"BUY_STOP={nr_high:.2f} SL={long_sl:.2f}\n"
                f"SELL_STOP={nr_low:.2f} SL={short_sl:.2f}\n"
                f"Lots={lots:g}  Risk=${risk_usd:.2f}"
            )

        # Place pending stops
        buy_res = self._order_manager.place_pending_stop_order(
            symbol=sym, direction="LONG", lot_size=lots,
            stop_price=nr_high, stop_loss=long_sl, take_profit=0.0,
            comment=self.PATTERN_TYPE, magic=cfg["magic"],
        )
        sell_res = self._order_manager.place_pending_stop_order(
            symbol=sym, direction="SHORT", lot_size=lots,
            stop_price=nr_low, stop_loss=short_sl, take_profit=0.0,
            comment=self.PATTERN_TYPE, magic=cfg["magic"],
        )
        if buy_res:
            self._buy_stop_ticket = buy_res.get("order_ticket")
        if sell_res:
            self._sell_stop_ticket = sell_res.get("order_ticket")

        if not buy_res and not sell_res:
            logger.error("[NR7] %s: BOTH bracket placements failed", sym)
            return

        # Cache the NR day's geometry + stop distance for trade record on fill
        self._nr_day_high = nr_high
        self._nr_day_low = nr_low
        self._initial_stop_dist = stop_dist

    # ─── Pending fill watch ──────────────────────────────────────────

    def _check_pending_fills(self, sym: str):
        """Detect which side filled, cancel the survivor, log trade open."""
        positions = mt5.positions_get(symbol=sym) or []
        our_pos = None
        for pos in positions:
            if pos.magic == self._cfg["magic"] and pos.comment == self.PATTERN_TYPE:
                our_pos = pos
                break

        if our_pos is None:
            # Neither filled yet — check if pendings vanished (broker cancelled)
            for label, ticket in (("BUY_STOP", self._buy_stop_ticket),
                                   ("SELL_STOP", self._sell_stop_ticket)):
                if ticket is not None:
                    orders = mt5.orders_get(ticket=ticket) or []
                    if not orders:
                        logger.warning("[NR7] %s %s ticket=%d vanished",
                                       sym, label, ticket)
            return

        # Identify side
        if our_pos.type == mt5.ORDER_TYPE_BUY:
            direction = "LONG"
            survivor = self._sell_stop_ticket
        else:
            direction = "SHORT"
            survivor = self._buy_stop_ticket

        # Cancel survivor
        if survivor is not None:
            self._order_manager.cancel_pending_order(survivor)
        self._buy_stop_ticket = None
        self._sell_stop_ticket = None

        # Already have a trade record? — re-adopt path; just bind ticket
        if self._open_trade_id is not None:
            return

        # Log the trade open
        fill_price = our_pos.price_open
        sl = our_pos.sl
        trade_data = {
            "pattern_id": None,
            "symbol": sym,
            "direction": direction,
            "pattern_type": self.PATTERN_TYPE,
            "mt5_ticket": our_pos.ticket,
            "entry_price": fill_price,
            "stop_loss": sl,
            "target_1": 0.0,
            "target_2": 0.0,
            "lot_size": our_pos.volume,
            "opened_at": datetime.now(timezone.utc),
            "status": "OPEN",
            "intended_entry": self._nr_day_high if direction == "LONG" else self._nr_day_low,
            "intended_sl": sl,
            "slippage": 0.0,
            "pattern_metadata": json.dumps({
                "nr_day_high": self._nr_day_high,
                "nr_day_low": self._nr_day_low,
                "atr_mult": self._cfg["atr_stop_multiplier"],
                "exit_lookback": self._cfg["exit_lookback_days"],
            }),
        }
        trade_record = self._trade_logger.log_trade_open(trade_data)
        self._open_trade_id = trade_record.id
        self._current_stop = sl
        self._save_state()

        logger.info(
            "[NR7] %s %s FILLED: ticket=%d @ %.2f SL=%.2f lots=%g",
            sym, direction, our_pos.ticket, fill_price, sl, our_pos.volume,
        )
        if self._alerter:
            self._alerter.send_message(
                f"<b>[NR7] {sym} {direction} FILLED</b>\n"
                f"Entry: {fill_price:.2f}  SL: {sl:.2f}\n"
                f"Lots: {our_pos.volume:g}"
            )

    # ─── Trail ───────────────────────────────────────────────────────

    def _trail_open_trade(self, sym: str):
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
            # Broker already closed it (SL hit). Reconciliation will handle.
            logger.info("[NR7] %s position %d gone at broker — reconciliation will resolve",
                        sym, trade.mt5_ticket)
            self._open_trade_id = None
            self._current_stop = None
            return

        # Fetch the 10-day opposite extreme
        exit_lb = self._cfg["exit_lookback_days"]
        bars = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, exit_lb + 5)
        if bars is None or len(bars) < exit_lb + 1:
            return
        df = pd.DataFrame(bars)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        # Drop today's developing bar if present
        now = datetime.now(timezone.utc)
        if df["time"].iloc[-1].date() >= now.date():
            df = df.iloc[:-1]
        if len(df) < exit_lb:
            return
        recent = df.tail(exit_lb)
        prior_high = float(recent["high"].max())
        prior_low = float(recent["low"].min())

        if trade.direction == "LONG":
            target_sl = prior_low
            if target_sl <= trade.stop_loss:
                return  # no improvement
            new_stop = max(trade.stop_loss, target_sl)
        else:
            target_sl = prior_high
            if target_sl >= trade.stop_loss:
                return
            new_stop = min(trade.stop_loss, target_sl)

        if abs(new_stop - trade.stop_loss) < 0.01:
            return

        ok = self._order_manager.modify_stop_loss(trade.mt5_ticket, sym, new_stop)
        if ok:
            self._trade_logger.log_trade_update(
                trade.id, stop_loss=new_stop, trailing_sl=new_stop,
            )
            self._current_stop = new_stop
            logger.info("[NR7] %s trail: %s SL %.2f → %.2f",
                        sym, trade.direction, trade.stop_loss, new_stop)
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[NR7] {sym} SL trailed</b>\n"
                    f"{trade.direction}: {trade.stop_loss:.2f} → {new_stop:.2f}"
                )

    # ─── State persistence ───────────────────────────────────────────

    def _save_state(self):
        payload = {
            "open_trade_id": self._open_trade_id,
            "current_stop": self._current_stop,
            "buy_stop_ticket": self._buy_stop_ticket,
            "sell_stop_ticket": self._sell_stop_ticket,
            "nr_day_high": self._nr_day_high,
            "nr_day_low": self._nr_day_low,
            "initial_stop_dist": self._initial_stop_dist,
            "last_processed_date": self._last_processed_date,
            "instrument": self._cfg["instrument"],
        }
        try:
            tmp = self._state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self._state_file)
        except Exception as e:
            logger.warning("[NR7] %s state save failed: %s",
                           self._cfg["instrument"], e)

    def _adopt_on_startup(self):
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text())
        except Exception:
            return
        if payload.get("instrument") != self._cfg["instrument"]:
            return

        self._last_processed_date = payload.get("last_processed_date")
        self._current_stop = payload.get("current_stop")
        self._nr_day_high = payload.get("nr_day_high")
        self._nr_day_low = payload.get("nr_day_low")
        self._initial_stop_dist = payload.get("initial_stop_dist")

        saved_id = payload.get("open_trade_id")
        if saved_id is None:
            # Maybe pendings? Try to re-adopt those
            self._buy_stop_ticket = payload.get("buy_stop_ticket")
            self._sell_stop_ticket = payload.get("sell_stop_ticket")
            if self._buy_stop_ticket or self._sell_stop_ticket:
                logger.warning(
                    "[NR7] %s startup: re-adopted pending tickets B=%s S=%s",
                    self._cfg["instrument"], self._buy_stop_ticket, self._sell_stop_ticket,
                )
            return

        # Re-adopt open trade
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
                "[NR7] %s startup re-adopt: open trade id=%d ticket=%d %s @ %.2f SL=%.2f",
                self._cfg["instrument"], trade.id, trade.mt5_ticket,
                trade.direction, trade.entry_price, trade.stop_loss,
            )
        else:
            logger.warning(
                "[NR7] %s startup: trade %d (ticket %d) gone at broker — reconciliation will resolve",
                self._cfg["instrument"], saved_id, trade.mt5_ticket,
            )
