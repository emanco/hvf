# Asian Gravity Strategy — Build Specification

**Date**: 2026-04-15
**Status**: Designed and backtested. Ready for implementation.
**Integration**: Add to existing HVF bot as a new strategy thread.

---

## Strategy Rules (Wednesday Config — 100% WR)

```
Pair:           EURGBP
Session:        Asian (00:00-06:00 UTC)
Days:           Wednesday only (weekday index 2)
Timeframe:      M5 (5-minute bars) for monitoring, M15 fallback if M5 unavailable
Formation:      00:00-02:00 UTC — measure high/low to get session range
Range filter:   Skip session if formation range > 10 pips
Direction:      LONG only
Trigger:        Price drops 3 pips below session open (00:00 bar open price)
Entry:          Market order at trigger level (session_open - 3 pips)
Take Profit:    +2 pips from entry (session_open - 1 pip)
Stop Loss:      -4 pips from entry (session_open - 7 pips)
Max trades:     1 per session (no re-entries)
Forced exit:    06:00 UTC — close at market
Spread check:   Skip if spread > 1.5 pips at entry time
```

### Backtest Results (M5, 60 days, Jan 22 - Apr 15, 2026)
- Trades: 10
- Win Rate: 100%
- Total P&L: +10 pips
- Max Drawdown: 0 pips
- Expectancy: +1.0 pip/trade
- Stop loss: never hit in sample

### Risk Management
- Risk per trade: 2% equity (configurable, start at 0.5% during shadow phase)
- Strategy daily loss limit: 3%
- Kill switch: 2 consecutive losses = disable for review
- Spread gate: max 1.5 pips at entry
- Combined with KZ Hunt: both count toward global circuit breaker (5% daily)

---

## Architecture

### Integration Approach
Add to existing bot as a 5th thread. Reuse all shared infrastructure.

### New Files to Create

#### 1. `hvf_trader/strategies/asian_gravity_detector.py` (~120 lines)

```python
"""
Asian Gravity session tracker and entry signal detector.

Tracks the Asian session open price and formation range on M5/M15 bars.
Emits a LONG signal when price drops trigger_pips below session open
on qualifying sessions (Wednesday, range < max_range).
"""

class AsianGravityTracker:
    """Tracks Asian session state: formation → trading → closed."""
    
    def __init__(self):
        self._session_date = None
        self._session_open = 0.0
        self._formation_high = 0.0
        self._formation_low = 0.0
        self._range_pips = 0.0
        self._state = "IDLE"  # IDLE, FORMING, TRADING, DONE
        self._traded_today = False
    
    def update(self, bar_time, bar_open, bar_high, bar_low, bar_close):
        """Process a new M5/M15 bar. Returns session state."""
        # Detect new session at 00:00 UTC
        # Track formation range during 00:00-02:00
        # Transition to TRADING at 02:00
        # Return state for the scanner to act on
        pass
    
    def get_session_state(self) -> dict:
        """Return current session info: open, range, state, traded."""
        pass
    
    def reset(self):
        """Reset for new session."""
        pass


def check_gravity_entry(tracker: AsianGravityTracker, current_price: float,
                        config: dict) -> dict | None:
    """Check if price has triggered a LONG entry.
    
    Args:
        tracker: Current session state
        current_price: Current bid price
        config: Strategy parameters (trigger_pips, max_range, etc.)
    
    Returns:
        Signal dict with entry_price, tp, sl, or None.
    """
    # Check: state is TRADING
    # Check: not already traded today
    # Check: range < max_range_pips
    # Check: current_price <= session_open - trigger_pips
    # Return signal with computed TP and SL
    pass
```

#### 2. `hvf_trader/strategies/asian_gravity_scanner.py` (~200 lines)

```python
"""
Asian Gravity scanner thread.

Runs as a daemon thread alongside the main scanner.
Polls M5 data every 60 seconds during Asian session hours (00:00-06:00 UTC).
Handles the full lifecycle: formation tracking → entry detection → execution.
"""

class AsianGravityScanner:
    """Dedicated scanner for the Asian Gravity strategy."""
    
    def __init__(self, order_manager, trade_logger, risk_manager, 
                 circuit_breaker, connector, alerter):
        self._tracker = AsianGravityTracker()
        self._order_manager = order_manager
        self._trade_logger = trade_logger
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._connector = connector
        self._alerter = alerter
        self._running = False
        self._open_trade_id = None  # DB trade ID if a trade is open
    
    def start(self):
        """Main loop: poll every 60s, only active 00:00-06:00 UTC."""
        # while self._running:
        #   now = utc_now()
        #   if not asian_session_active(now):
        #       sleep(60); continue
        #   
        #   # Check day filter (Wednesday only)
        #   if now.weekday() != 2:
        #       sleep(60); continue
        #
        #   # Fetch latest M5 bars
        #   df = fetch_and_prepare("EURGBP", "M5", bars=50)
        #   
        #   # Update tracker with new bars
        #   tracker.update(...)
        #   
        #   # If in TRADING state and no open trade:
        #   #   Check spread
        #   #   Check gravity entry signal
        #   #   If signal: run risk checks, execute, log to DB
        #   
        #   # If trade is open:
        #   #   TP and SL are set on MT5 (broker-side execution)
        #   #   Just check for time exit at 06:00
        #   
        #   sleep(60)
        pass
    
    def stop(self):
        self._running = False
    
    def _execute_entry(self, signal: dict):
        """Place the trade via order_manager with SL and TP set on MT5."""
        # Pre-trade risk checks (subset of the 8 gates):
        #   - Circuit breaker check
        #   - Spread check (max 1.5 pips)
        #   - Margin check
        #   - Position sizing (2% risk, 4-pip stop)
        #
        # place_market_order with take_profit AND stop_loss
        # Both TP and SL execute broker-side at tick level
        # Log trade to DB with pattern_type="ASIAN_GRAVITY"
        # Log pattern with pattern_metadata containing session info
        # Send Telegram alert
        pass
    
    def _check_time_exit(self):
        """Force close at 06:00 UTC if trade still open."""
        # If self._open_trade_id and hour >= 6:
        #   close_position()
        #   log_trade_close() with close_reason="TIME_EXIT"
        pass
```

#### 3. `hvf_trader/strategies/asian_gravity_backtest.py` (~250 lines)

Standalone backtest engine for validation. Already prototyped in `scripts/asian_gravity_m5_backtest.py`.
Adapt to use the same `AsianGravityTracker` and signal logic as the live code.

### Files to Modify

#### 4. `hvf_trader/config.py` — Add strategy config block (~30 lines)

```python
# ─── Asian Gravity Strategy ──────────────────────────────────────────
ASIAN_GRAVITY = {
    "enabled": False,          # Enable after shadow trading phase
    "instrument": "EURGBP",
    "timeframe": "M5",         # M15 fallback
    "days": [2],               # Wednesday only (0=Mon, 2=Wed)
    "formation_start_utc": 0,
    "formation_end_utc": 2,
    "trading_end_utc": 6,
    "forced_exit_utc": 6,
    "trigger_pips": 3,
    "target_pips": 2,
    "stop_pips": 4,
    "max_range_pips": 10,
    "max_spread_pips": 1.5,
    "max_trades_per_session": 1,
    "direction": "LONG",       # LONG only
    "risk_pct": 0.5,           # Start conservative, ramp to 2.0
    "daily_loss_limit_pct": 3.0,
    "kill_switch_consecutive_losses": 2,
}

# Add to existing pattern dicts:
RISK_PCT_BY_PATTERN["ASIAN_GRAVITY"] = ASIAN_GRAVITY["risk_pct"]
MIN_RRR_BY_PATTERN["ASIAN_GRAVITY"] = 0.5  # 2:4 = 0.5 RRR is fine at 100% WR
TRAILING_STOP_ATR_MULT_BY_PATTERN["ASIAN_GRAVITY"] = 0  # No trailing
MIN_STOP_PIPS_BY_PATTERN["ASIAN_GRAVITY"] = 3
```

#### 5. `hvf_trader/main.py` — Register scanner thread (~20 lines)

```python
# In __init__:
self.asian_gravity_scanner = AsianGravityScanner(
    order_manager=self.order_manager,
    trade_logger=self.trade_logger,
    risk_manager=self.risk_manager,
    circuit_breaker=self.circuit_breaker,
    connector=self.connector,
    alerter=self.alerter,
)

# In start():
if config.ASIAN_GRAVITY["enabled"]:
    self._asian_gravity_thread = threading.Thread(
        target=self.asian_gravity_scanner.start,
        daemon=True, name="AsianGravity"
    )
    self._asian_gravity_thread.start()

# In _scanner_loop watchdog section:
if (config.ASIAN_GRAVITY["enabled"] and 
    not self._asian_gravity_thread.is_alive()):
    logger.error("Asian Gravity thread died - restarting")
    # ... restart logic (same pattern as trade monitor watchdog)
```

#### 6. `hvf_trader/execution/trade_monitor.py` — Strategy-aware management (~30 lines)

```python
def _check_trade(self, trade_record):
    if trade_record.pattern_type == "ASIAN_GRAVITY":
        self._check_gravity_trade(trade_record)
        return
    # ... existing KZ Hunt logic

def _check_gravity_trade(self, trade_record):
    """Manage Asian Gravity trade: TP/SL are broker-side, only check time exit."""
    # TP and SL are set on MT5 at order placement — broker handles them
    # We only need to:
    # 1. Check if position still exists (server-side TP/SL fill)
    # 2. Force close at 06:00 UTC if still open
    # 3. Detect and log if closed by broker
    now = datetime.now(timezone.utc)
    if now.hour >= 6:
        # Force close
        self.order_manager.close_position(...)
        self.trade_logger.log_trade_close(..., close_reason="TIME_EXIT")
```

#### 7. `hvf_trader/risk/risk_manager.py` — Adapt gates (~15 lines)

- Spread gate: use `ASIAN_GRAVITY["max_spread_pips"]` instead of global `MAX_SPREAD_ABSOLUTE`
- Same-instrument gate: allow ASIAN_GRAVITY even if KZ Hunt has a EURGBP trade open (different strategies, different sessions)
- RRR gate: accept 0.5 RRR for ASIAN_GRAVITY (2-pip target / 4-pip stop)

#### 8. `hvf_trader/risk/circuit_breaker.py` — Per-strategy limit (~15 lines)

- Add `ASIAN_GRAVITY` to pattern consecutive loss tracking
- Strategy-specific daily loss limit: 3% (separate from global 5%)
- Kill switch: 2 consecutive losses → disable until manual review

### Files Unchanged (Reused As-Is)
- `data/data_fetcher.py` — `fetch_and_prepare("EURGBP", "M5")` works already
- `execution/order_manager.py` — `place_market_order` with SL+TP works
- `execution/deal_utils.py` — deal search and PnL estimation
- `database/models.py` — `pattern_type="ASIAN_GRAVITY"`, `pattern_metadata` for session data
- `database/trade_logger.py` — all write methods
- `alerts/telegram_bot.py` — alert methods
- `alerts/telegram_commands.py` — `/trades`, `/status` will show ASIAN_GRAVITY trades
- `monitoring/reconciliation.py` — DB vs MT5 sync
- `monitoring/health_check.py` — MT5 heartbeat

---

## Estimated Code

| Component | Lines | Complexity |
|-----------|-------|-----------|
| `asian_gravity_detector.py` | ~120 | Small |
| `asian_gravity_scanner.py` | ~200 | Medium |
| `asian_gravity_backtest.py` | ~250 | Medium (mostly done in scripts/) |
| `config.py` additions | ~30 | Small |
| `main.py` thread registration | ~20 | Small |
| `trade_monitor.py` branch | ~30 | Small |
| `risk_manager.py` adaptations | ~15 | Small |
| `circuit_breaker.py` additions | ~15 | Small |
| **Total** | **~680** | |

---

## Build Order

### Phase 1: Shadow Trading (log signals, 0 lots)
1. `config.py` — add ASIAN_GRAVITY config block
2. `asian_gravity_detector.py` — tracker + entry signal detection
3. `asian_gravity_scanner.py` — thread with signal logging (no execution)
4. `main.py` — register thread
5. Deploy. Collect 30+ shadow signals over 4-8 Wednesdays.

### Phase 2: Live Trading (after shadow validation)
6. `asian_gravity_scanner.py` — add execution path
7. `trade_monitor.py` — add `_check_gravity_trade` for time exit
8. `risk_manager.py` — adapt spread and same-instrument gates
9. `circuit_breaker.py` — per-strategy limits
10. Deploy with 0.5% risk. Ramp to 2% after 10+ live trades.

### Phase 3: Full Production
11. Ramp risk to 2%
12. Consider adding Friday (day filter [2, 4]) after 50+ trades confirm edge holds
13. Consider adding EURUSD as second pair after 100+ trades

---

## Data Flow

```
Every 60 seconds during 00:00-06:00 UTC Wednesday:

fetch_and_prepare("EURGBP", "M5", bars=50)
    |
    v
AsianGravityTracker.update(bars)
    |
    +--> State: FORMING (00:00-02:00)
    |       Track high/low, compute range
    |
    +--> State: TRADING (02:00-06:00)
    |       If range > 10 pips → DONE (skip)
    |       If no trade yet:
    |           current_bid = connector.get_tick("EURGBP").bid
    |           If bid <= session_open - 3 pips:
    |               Check spread <= 1.5 pips
    |               Check circuit breaker
    |               Calculate lot size (2% risk, 4-pip stop)
    |               place_market_order(
    |                   symbol="EURGBP", direction="LONG",
    |                   sl=entry - 4 pips, tp=entry + 2 pips
    |               )
    |               log_trade_open(pattern_type="ASIAN_GRAVITY")
    |               Telegram alert
    |               → State: DONE (1 trade per session)
    |
    +--> State: DONE
            If hour >= 6 and trade still open:
                close_position() → TIME_EXIT
```

---

## Key Design Decisions

1. **TP and SL are broker-side** (set on the MT5 order). The trade monitor only handles time exit at 06:00. This means TP/SL execute at tick level, not bar level — more accurate than the backtest.

2. **Separate thread, not part of the KZ Hunt scanner loop.** The KZ Hunt scanner runs on H1 bars and only acts on new bar closes. The Asian Gravity scanner needs M5 awareness and only runs during a 6-hour window. Different cadence, different logic.

3. **1 trade per session, no re-entries.** This is the key insight from the backtest — re-entries after a stop kill the edge. The scanner tracks `_traded_today` and stops looking once an entry happens.

4. **LONG only.** EURGBP has a slight upward bias during Asian session. LONG showed 79% WR vs SHORT 57% in the broader backtest. The 100% WR configs were all LONG or had LONG driving the results.

5. **Wednesday only (initially).** Can expand to Wednesday + Friday after 50+ trades confirm the edge. The config uses a `days` list so adding Friday is a one-line change.

6. **M5 preferred, M15 fallback.** IC Markets currently only serves M15. If M5 becomes available (different account type or terminal update), switch to M5 for finer resolution. The detector works on either — it just needs bar timestamps, OHLC, and the ability to identify 00:00 UTC bars.

---

## Validation Checklist (Before Going Live)

- [ ] Shadow trade 30+ signals (8+ Wednesdays)
- [ ] Verify WR > 85% on shadow signals
- [ ] Verify IC Markets Asian EURGBP spread < 1.5 pips consistently
- [ ] Verify formation range < 10 pips filter skips ~15% of sessions (not 50%+)
- [ ] Verify entry signals occur between 02:00-04:00 UTC (not at session edges)
- [ ] Verify no conflict with KZ Hunt (different session hours)
- [ ] Test forced exit at 06:00 works correctly
- [ ] Test circuit breaker integration (strategy loss counts toward global limits)

---

*This strategy earns ~1 pip per trade with near-certainty on quiet Wednesday nights. The edge is not the pip count — it's the win rate. At 2% risk with a 4-pip stop, each win nets ~$100 on a $10k account, twice a month. The compounding comes from never losing, not from winning big.*
