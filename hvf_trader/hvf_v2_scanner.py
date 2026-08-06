"""HVF v2 scanner — Hunt Volatility Funnel, the version the 8.36-8.47 research measured.

WHAT IT TRADES. Six pivots read as three contracting waves after a trend exhaustion, in the
direction of the prior trend. All the geometry comes from
`hvf_trader.detector.hvf_rules`, which is the single definition shared with the backtest
scripts — see the parity guard in `scripts/hvf_v2_rules_parity.py`. Nothing about the rules
is decided in this file; it only turns a `Setup` into orders.

CONFIG THIS REPRODUCES (spec 8.45, IC Markets data and exact broker terms):
    arm on FORMING, stop at RL2, 8.42 shape gate, causal 500-bar trend, "hunt" exit, D1.

ENTRY IS A RESTING STOP ORDER. Arming on `forming` means RH3 has confirmed and price is
still pulling back, so the entry sits above the market for a long. That is a BUY_STOP, not
a market order, and it expires after `entry_wait_bars` — the same window both arms were
given in the research, so it is part of the measured result rather than a live convenience.

TWO LEGS, ONE SETUP. Hunt takes half off at TP2 and lets the rest run to TP3 with the stop
at breakeven. MT5 has no native partial TP, so the user's own suggestion is used: two orders
at the same entry with different exits. The TP1 leg is deliberately absent — 8.43 measured
the "hunt" exit against thirds and this is the rule the trader actually described.

HONEST STATUS. The 8.44 wide run returned NO GO; 8.45 suspended it after finding financing
was mis-modelled, and 8.46 could not resolve the question because the design was
underpowered. So this ships `dry_run=True`: it detects, sizes, alerts and logs, and places
nothing. What it is for is collecting live-outcome records against a rule frozen in advance,
which is the one thing the research could not manufacture.

Safety:
  - `enabled=False` — the thread never starts.
  - `dry_run=True`  — detection, sizing, alert and logging run; no broker call.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from hvf_trader import config
from hvf_trader.detector import hvf_rules

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

logger = logging.getLogger(__name__)


class HvfV2Scanner:
    PATTERN_TYPE = "HVF_V2"

    # Bars of history to pull. The trend rule looks back 500 and the zigzag needs room to
    # form six pivots before that, so this is the trend horizon plus working space.
    HISTORY_BARS = 900

    def __init__(self, order_manager, trade_logger, connector,
                 circuit_breaker, alerter=None, cfg=None):
        if cfg is None:
            raise ValueError(
                "HvfV2Scanner requires explicit cfg (merged parent + instance)"
            )
        self._cfg = cfg
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._connector = connector
        self._circuit_breaker = circuit_breaker
        self._alerter = alerter
        self._running = False

        # One setup in flight at a time per instrument. `_legs` holds the two orders from
        # the arming bar down to their close; `_acted_key` stops the same setup being
        # re-placed every poll while it rests unfilled.
        self._acted_key: str | None = None
        self._legs: list[dict] = []
        self._breakeven_done = False

        instrument = self._cfg["instrument"]
        self._state_file = config.LOG_DIR / f"hvf_v2_state_{instrument}.json"
        self._chart_dir = config.LOG_DIR / "hvf_v2_charts"

    # ─── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        self._running = True
        poll = self._cfg["poll_interval_sec"]
        hb_every = max(1, int(3600 / poll))
        logger.info(
            "[HVF_V2] Scanner thread started (%s, poll=%ds, dry_run=%s, arm=%s, "
            "stop=%s, wait=%d bars, risk=%.2f%%)",
            self._cfg["instrument"], poll, self._cfg["dry_run"],
            self._cfg["arm_on"], self._cfg["stop_at"],
            self._cfg["entry_wait_bars"], self._cfg["risk_pct"],
        )
        self._adopt_on_startup()
        iters = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:                                 # noqa: BLE001
                logger.error("[HVF_V2] Scanner error: %s", e, exc_info=True)
            iters += 1
            if iters % hb_every == 0:
                logger.info("[HVF_V2] heartbeat %s: iter=%d acted=%s legs=%d",
                            self._cfg["instrument"], iters, self._acted_key,
                            len(self._legs))
            time.sleep(poll)
        logger.info("[HVF_V2] Scanner thread stopped (%s)", self._cfg["instrument"])

    def stop(self):
        self._running = False

    # ─── Core loop ───────────────────────────────────────────────────

    def _tick(self):
        if not MT5_AVAILABLE:
            return
        sym = self._cfg["instrument"]

        frame = self._fetch_bars(sym, self.HISTORY_BARS)
        if frame is None or len(frame) < 600:
            logger.warning("[HVF_V2] %s insufficient history (%s bars); waiting",
                           sym, 0 if frame is None else len(frame))
            return

        # Manage first: legs in flight take priority over new detection, and the
        # breakeven move must be retried every poll so a modify rejected during the
        # broker's daily maintenance close applies as soon as the market reopens.
        if self._legs:
            self._manage_legs(sym)
            self._save_state()
            return

        # Only act on CLOSED bars. The forming bar's high and low keep moving, and with
        # them the funnel tip, the stop distance and every target.
        closed = frame.iloc[:-1]
        setup = hvf_rules.latest_setup(
            closed,
            max_age_bars=self._cfg["max_age_bars"],
            arm_on=self._cfg["arm_on"],
            stop_at=self._cfg["stop_at"],
        )
        if setup is None:
            logger.info("[HVF_V2] %s no setup (bars=%d, last=%s)",
                        sym, len(closed), hvf_rules.bar_time(closed, -1).date())
            return

        key = self._setup_key(closed, setup)
        if key == self._acted_key:
            return
        self._act_on(sym, closed, setup, key)

    @staticmethod
    def _setup_key(frame, setup) -> str:
        """Identity of a setup, stable across restarts and across bar-count drift."""
        return (f"{hvf_rules.bar_time(frame, setup.arm).date().isoformat()}|"
                f"{setup.direction:+d}|{setup.entry:.6f}|{setup.stop:.6f}")

    def _fetch_bars(self, symbol: str, count: int) -> pd.DataFrame | None:
        bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, count)
        if bars is None or len(bars) == 0:
            return None
        df = pd.DataFrame(bars)
        # Match the frame contract the research path uses and `zigzag_pct` requires:
        # a `dt` COLUMN over a RangeIndex, not a DatetimeIndex. Getting this wrong
        # makes pivot indices and row numbers silently interchangeable.
        df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
        cols = ["open", "high", "low", "close"]
        df[cols] = df[cols].astype(float)
        return df[["dt", *cols]].sort_values("dt").reset_index(drop=True)

    # ─── Acting on a setup ───────────────────────────────────────────

    def _act_on(self, sym: str, frame, setup, key: str):
        from hvf_trader.risk import portfolio_gate
        with portfolio_gate.reserve(sym) as (gate_ok, gate_reason):
            if not gate_ok:
                logger.warning("[HVF_V2] %s blocked by portfolio gate: %s", sym, gate_reason)
                self._acted_key = key           # consume it; the setup won't wait for us
                self._save_state()
                return
            self._act_on_inner(sym, frame, setup, key)

    def _act_on_inner(self, sym: str, frame, setup, key: str):
        cfg = self._cfg
        side = "LONG" if setup.direction > 0 else "SHORT"

        if self._circuit_breaker.is_tripped:
            logger.info("[HVF_V2] global breaker tripped, skipping %s", sym)
            self._acted_key = key
            self._save_state()
            return
        ok, reason = self._circuit_breaker.check_pattern(self.PATTERN_TYPE, sym)
        if not ok:
            logger.info("[HVF_V2] pattern breaker tripped: %s", reason)
            self._acted_key = key
            self._save_state()
            return

        sizing = self._size(sym, setup)
        if sizing is None:
            self._acted_key = key
            self._save_state()
            return
        lots_tp2, lots_tp3, dpp, risk_usd, info = sizing

        expiry = datetime.now(timezone.utc) + timedelta(days=cfg["entry_wait_bars"])
        chart = self._render(frame, setup, sym, key)
        self._alert(sym, side, setup, lots_tp2, lots_tp3, risk_usd, dpp, expiry, chart)

        logger.info(
            "[HVF_V2] %s %s SETUP arm=%s entry=%.5f stop=%.5f risk=%.5f "
            "tp=(%.5f/%.5f/%.5f) rrr=%.2f shape=(%.2f,%.2f) lots=%.2f+%.2f",
            sym, side, hvf_rules.bar_time(frame, setup.arm).date(), setup.entry, setup.stop,
            setup.risk, *setup.tps, setup.rrr, setup.t3_t1, setup.amp3_amp1,
            lots_tp2, lots_tp3,
        )

        if cfg["dry_run"]:
            logger.info("[HVF_V2] dry_run=True — not placing orders for %s", sym)
            self._log_paper_setup(sym, side, setup, frame, lots_tp2, lots_tp3, risk_usd)
            self._acted_key = key
            self._save_state()
            return

        placed = []
        for lots, tp, tag in ((lots_tp2, setup.tps[1], "TP2"),
                              (lots_tp3, setup.tps[2], "TP3")):
            result = self._order_manager.place_pending_stop_order(
                symbol=sym, direction=side, lot_size=lots,
                stop_price=setup.entry, stop_loss=setup.stop, take_profit=tp,
                comment=f"{self.PATTERN_TYPE}_{tag}", magic=cfg["magic"],
                expiration_utc=expiry,
            )
            if not result:
                logger.error("[HVF_V2] %s %s leg rejected by broker", sym, tag)
                continue
            placed.append({"tag": tag, "order_ticket": result.get("order_ticket"),
                           "lots": lots, "tp": tp, "side": side,
                           "stop": setup.stop, "position_ticket": None,
                           "trade_id": None})

        if not placed:
            # Both legs rejected. Do NOT consume the setup: it stays actionable for
            # max_age_bars and the next poll can try again, the same treatment the
            # Donchian scanner gives a rollover-rejected entry.
            logger.error("[HVF_V2] %s both legs rejected — setup NOT consumed", sym)
            return
        if len(placed) == 1:
            # Half a strategy is not the strategy: the hunt exit is defined by the
            # relationship between the two legs. Roll back rather than run a mutant.
            logger.error("[HVF_V2] %s only the %s leg placed — cancelling it, "
                         "the hunt exit needs both", sym, placed[0]["tag"])
            self._order_manager.cancel_pending_order(placed[0]["order_ticket"])
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[HVF_V2] setup abandoned</b>\n"
                    f"{sym} {side}: only one of two legs could be placed, "
                    f"so both were withdrawn.")
            self._acted_key = key
            self._save_state()
            return

        self._legs = placed
        self._breakeven_done = False
        self._acted_key = key
        self._record_setup(sym, side, setup, frame, risk_usd)
        self._save_state()

    def _size(self, sym: str, setup):
        """Lots for the two legs, or None when the trade cannot be sized safely.

        Risk is 1% of LIVE equity measured entry-to-stop, which for `stop_at="rl2"` is the
        second funnel, not the tip. Value-per-point is read from the instrument — never
        assumed — for the reason recorded in CLAUDE.md.
        """
        cfg = self._cfg
        account = self._connector.get_account_info()
        if not account:
            logger.error("[HVF_V2] no account info; skipping %s", sym)
            return None
        risk_usd = account["equity"] * cfg["risk_pct"] / 100.0

        info = mt5.symbol_info(sym)
        if info is not None and not info.visible:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
        dpp = None
        if info is not None and info.trade_tick_size:
            dpp = info.trade_tick_value / info.trade_tick_size
        if not dpp or dpp <= 0:
            logger.error("[HVF_V2] %s cannot derive value-per-point "
                         "(tick_value=%s tick_size=%s) — refusing to size",
                         sym, getattr(info, "trade_tick_value", None),
                         getattr(info, "trade_tick_size", None))
            return None

        vol_step = info.volume_step or 0.01
        vol_min = info.volume_min or 0.01
        vol_max = info.volume_max or 100.0
        raw = risk_usd / (setup.risk * dpp)
        total = min(vol_max, math.floor(raw / vol_step + 1e-9) * vol_step)

        # Split half and half, flooring each leg. Flooring can only take realised risk
        # below intended, never above.
        half = math.floor((total / 2) / vol_step + 1e-9) * vol_step
        lots_tp2 = lots_tp3 = round(half, 4)
        if lots_tp2 < vol_min:
            # A silent no-op instrument is the failure mode the Donchian config documents
            # at length, so say so loudly rather than log-and-forget.
            logger.error(
                "[HVF_V2] %s cannot split into two legs: raw %.4f lots, half %.4f is "
                "below broker min %s. Equity $%.0f at %.2f%% over a %.5f stop is too "
                "small for this instrument — it will NEVER trade until equity or risk "
                "rises. Skipping.",
                sym, raw, half, vol_min, account["equity"], cfg["risk_pct"], setup.risk,
            )
            if self._alerter:
                self._alerter.send_message(
                    f"<b>[HVF_V2] {sym} cannot be sized</b>\n"
                    f"Half-leg {half:.4f} lots is under the broker minimum {vol_min}. "
                    f"This instrument cannot trade at ${account['equity']:,.0f} equity "
                    f"and {cfg['risk_pct']:.2f}% risk.")
            return None

        implied = (lots_tp2 + lots_tp3) * setup.risk * dpp
        if implied > risk_usd * 1.05:
            logger.error(
                "[HVF_V2] %s sizing sanity FAILED: implied $%.2f > intended $%.2f "
                "(lots=%.2f+%.2f dist=%.5f dpp=%.6g) — refusing",
                sym, implied, risk_usd, lots_tp2, lots_tp3, setup.risk, dpp,
            )
            return None
        return lots_tp2, lots_tp3, dpp, risk_usd, info

    # ─── Managing the two legs ───────────────────────────────────────

    def _manage_legs(self, sym: str):
        """Fills, expiry, and the breakeven move once the TP2 leg banks.

        Hunt's rule is half off at TP2 with the remainder running to TP3 on a breakeven
        stop. Live, the TP2 leg closing IS the trigger — there is nothing else to watch.
        """
        alive = []
        tp2_closed = False
        for leg in self._legs:
            if leg["position_ticket"] is None:
                # Still pending, or filled since the last poll.
                order = self._order_manager.get_pending_order(leg["order_ticket"])
                if order is not None:
                    alive.append(leg)
                    continue
                pos = self._position_for_order(leg["order_ticket"])
                if pos is None:
                    logger.info("[HVF_V2] %s %s leg expired or was cancelled unfilled",
                                sym, leg["tag"])
                    continue
                leg["position_ticket"] = pos["ticket"]
                leg["trade_id"] = self._record_fill(sym, leg, pos)
                logger.info("[HVF_V2] %s %s leg FILLED ticket=%s @ %.5f lots=%s",
                            sym, leg["tag"], pos["ticket"], pos["price_open"], leg["lots"])
                if self._alerter:
                    self._alerter.send_message(
                        f"<b>[HVF_V2] {sym} {leg['tag']} leg filled</b>\n"
                        f"@ {pos['price_open']:.5f}  lots {leg['lots']}  "
                        f"TP {leg['tp']:.5f}")
                alive.append(leg)
                continue

            positions = mt5.positions_get(ticket=leg["position_ticket"]) or []
            if positions:
                alive.append(leg)
                continue
            logger.info("[HVF_V2] %s %s leg closed at broker; reconciliation will "
                        "resolve the record", sym, leg["tag"])
            if leg["tag"] == "TP2":
                tp2_closed = True

        self._legs = alive

        if tp2_closed and not self._breakeven_done:
            self._move_tp3_to_breakeven(sym)
        if not self._legs:
            self._breakeven_done = False

    def _move_tp3_to_breakeven(self, sym: str):
        for leg in self._legs:
            if leg["tag"] != "TP3" or leg["position_ticket"] is None:
                continue
            positions = mt5.positions_get(ticket=leg["position_ticket"]) or []
            if not positions:
                continue
            entry = float(positions[0].price_open)
            if self._cfg["dry_run"]:
                logger.info("[HVF_V2] dry_run breakeven: would move %s TP3 SL to %.5f",
                            sym, entry)
                self._breakeven_done = True
                return
            if self._order_manager.modify_stop_loss(leg["position_ticket"], sym, entry):
                self._breakeven_done = True
                logger.info("[HVF_V2] %s TP2 banked — TP3 leg stop moved to breakeven "
                            "%.5f", sym, entry)
                if leg["trade_id"]:
                    self._trade_logger.log_trade_update(
                        leg["trade_id"], stop_loss=entry, trailing_sl=entry)
                if self._alerter:
                    self._alerter.send_message(
                        f"<b>[HVF_V2] {sym} TP2 banked</b>\n"
                        f"TP3 leg now running on a breakeven stop at {entry:.5f}.")
            else:
                # Retried on the next poll — the market may simply be in its daily close.
                logger.warning("[HVF_V2] %s could not move TP3 stop to breakeven; "
                               "will retry", sym)

    def _position_for_order(self, order_ticket) -> dict | None:
        """The position a triggered pending order became, if it filled."""
        if order_ticket is None:
            return None
        for p in (mt5.positions_get() or []):
            if p.ticket == order_ticket or getattr(p, "identifier", None) == order_ticket:
                return {"ticket": p.ticket, "price_open": float(p.price_open),
                        "volume": float(p.volume), "sl": float(p.sl), "tp": float(p.tp)}
        return None

    # ─── Records ─────────────────────────────────────────────────────

    def _metadata(self, setup, frame) -> str:
        """Shape metrics travel with every record — they are what the self-validation
        loop learns from. A bad trade is only training data if the funnel that produced
        it was measured at the time."""
        return json.dumps({
            "arm_bar": hvf_rules.bar_time(frame, setup.arm).date().isoformat(),
            "entry": setup.entry, "stop": setup.stop, "small_stop": setup.small_stop,
            "centre": setup.centre, "risk": setup.risk,
            "tp1": setup.tps[0], "tp2": setup.tps[1], "tp3": setup.tps[2],
            "rrr_tp3": setup.rrr,
            "t3_t1": setup.t3_t1, "amp3_amp1": setup.amp3_amp1,
            "arm_on": self._cfg["arm_on"], "stop_at": self._cfg["stop_at"],
            "exit_style": self._cfg["exit_style"],
            "pivots": [{"index": int(p.index), "price": float(p.price)}
                       for p in setup.pivots],
        })

    def _record_setup(self, sym, side, setup, frame, risk_usd):
        try:
            self._trade_logger.log_event(
                "HVF_V2_SETUP",
                details=f"{sym} {side} entry={setup.entry:.5f} stop={setup.stop:.5f} "
                        f"rrr={setup.rrr:.2f} risk=${risk_usd:.2f}",
            )
        except Exception as e:                                     # noqa: BLE001
            logger.warning("[HVF_V2] could not log setup event: %s", e)

    def _log_paper_setup(self, sym, side, setup, frame, lots_tp2, lots_tp3, risk_usd):
        """dry_run still writes the record. The whole reason this ships disarmed is to
        accumulate live-outcome data against a rule frozen in advance."""
        try:
            self._trade_logger.log_event(
                "HVF_V2_PAPER",
                details=f"{sym} {side} lots={lots_tp2}+{lots_tp3} risk=${risk_usd:.2f} "
                        f"{self._metadata(setup, frame)}",
            )
        except Exception as e:                                     # noqa: BLE001
            logger.warning("[HVF_V2] could not log paper setup: %s", e)

    def _record_fill(self, sym, leg, pos) -> int | None:
        try:
            record = self._trade_logger.log_trade_open({
                "pattern_id": None,
                "symbol": sym,
                "direction": leg["side"],
                "pattern_type": self.PATTERN_TYPE,
                "mt5_ticket": pos["ticket"],
                "entry_price": pos["price_open"],
                "stop_loss": pos["sl"],
                "target_1": pos["tp"],
                "target_2": 0.0,
                "lot_size": leg["lots"],
                "opened_at": datetime.now(timezone.utc),
                "status": "OPEN",
                "pattern_metadata": json.dumps({"leg": leg["tag"]}),
            })
            return record.id
        except Exception as e:                                     # noqa: BLE001
            logger.warning("[HVF_V2] could not log fill: %s", e)
            return None

    def _render(self, frame, setup, sym, key) -> str | None:
        from hvf_trader.alerts.hvf_chart import render_setup
        stamp = key.split("|")[0]
        return render_setup(frame, setup, sym,
                            self._chart_dir / f"{sym}_{stamp}.png")

    def _alert(self, sym, side, setup, lots_tp2, lots_tp3, risk_usd, dpp, expiry, chart):
        if not (self._cfg.get("alert_on_detection", True) and self._alerter):
            return
        mode = "DRY-RUN" if self._cfg["dry_run"] else "LIVE"
        r = setup.r_multiple
        text = (
            f"<b>[HVF_V2] {side} setup ({mode})</b>\n"
            f"{sym}  entry <b>{setup.entry:.5f}</b>  stop {setup.stop:.5f}\n"
            f"TP1 {setup.tps[0]:.5f} ({r(setup.tps[0]):+.2f}R)\n"
            f"TP2 {setup.tps[1]:.5f} ({r(setup.tps[1]):+.2f}R)  ← half off\n"
            f"TP3 {setup.tps[2]:.5f} ({r(setup.tps[2]):+.2f}R)  ← runs on breakeven\n"
            f"Risk ${risk_usd:,.2f} ({self._cfg['risk_pct']:.2f}%)  "
            f"lots {lots_tp2:.2f}+{lots_tp3:.2f}\n"
            f"Shape t3/t1 {setup.t3_t1:.2f}, amp3/amp1 {setup.amp3_amp1:.2f}  "
            f"RRR {setup.rrr:.1f}:1\n"
            f"Entry rests until {expiry:%d %b %H:%M} UTC"
        )
        try:
            if chart:
                self._alerter.send_photo(chart, caption=text)
            else:
                self._alerter.send_message(text)
        except Exception as e:                                     # noqa: BLE001
            logger.warning("[HVF_V2] alert failed: %s", e)

    # ─── State persistence ───────────────────────────────────────────

    def _save_state(self):
        payload = {
            "instrument": self._cfg["instrument"],
            "acted_key": self._acted_key,
            "legs": self._legs,
            "breakeven_done": self._breakeven_done,
        }
        try:
            tmp = self._state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self._state_file)
        except Exception as e:                                     # noqa: BLE001
            logger.warning("[HVF_V2] failed to save state: %s", e)

    def _adopt_on_startup(self):
        if not self._state_file.exists():
            return
        try:
            saved = json.loads(self._state_file.read_text())
        except Exception as e:                                     # noqa: BLE001
            logger.warning("[HVF_V2] failed to load state: %s", e)
            return
        if saved.get("instrument") != self._cfg["instrument"]:
            return
        self._acted_key = saved.get("acted_key")
        self._breakeven_done = bool(saved.get("breakeven_done"))
        legs = saved.get("legs") or []
        if not legs or not MT5_AVAILABLE:
            self._legs = legs
            return
        # Keep only legs the broker still knows about, so a restart after a close
        # doesn't leave the scanner waiting on a position that no longer exists.
        alive = []
        for leg in legs:
            if leg.get("position_ticket") is not None:
                if mt5.positions_get(ticket=leg["position_ticket"]):
                    alive.append(leg)
            elif self._order_manager.get_pending_order(leg.get("order_ticket")):
                alive.append(leg)
        self._legs = alive
        if alive:
            logger.warning("[HVF_V2] %s startup re-adopt: %d leg(s) still live: %s",
                           self._cfg["instrument"], len(alive),
                           ", ".join(l["tag"] for l in alive))
        elif legs:
            logger.info("[HVF_V2] %s startup: %d saved leg(s) gone at broker; "
                        "reconciliation will resolve", self._cfg["instrument"], len(legs))
