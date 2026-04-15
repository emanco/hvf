# HVF Auto-Trader — Backlog

Last updated: 2026-04-15

## Next Up: Asian Gravity Strategy

Build spec: `ASIAN_GRAVITY_BUILD_SPEC.md`

### Phase 1: Shadow Trading
- [ ] Add ASIAN_GRAVITY config block to config.py
- [ ] Build asian_gravity_detector.py (tracker + entry signal)
- [ ] Build asian_gravity_scanner.py (thread with signal logging, no execution)
- [ ] Register thread in main.py with watchdog
- [ ] Deploy and collect 30+ shadow signals over 8+ Wednesdays

### Phase 2: Live Trading (after shadow validation)
- [ ] Add execution path to scanner
- [ ] Add _check_gravity_trade to trade_monitor.py (time exit)
- [ ] Adapt risk_manager.py gates (spread, same-instrument, RRR)
- [ ] Add per-strategy circuit breaker limits
- [ ] Deploy with 0.5% risk, ramp to 2% after 10+ live trades

### Phase 3: Expansion
- [ ] Add Friday after 50+ trades confirm edge
- [ ] Consider EURUSD as second pair after 100+ trades

---

## Deferred Audit Findings

### M8 — RRR Threshold Review
- RRR minimum of 1.0 may be too tight given spread widening at execution time
- Seeing frequent rejections — need data to determine if this is filtering bad setups or blocking good ones
- **Action**: Revisit after 50+ clean KZ_HUNT trades (from 2026-03-27 onward)

### L1-L5 — Logging & Monitoring Polish
- Better error messages in edge cases
- More granular severity levels
- Minor observability improvements
- **Priority**: Low — do when convenient

## Feature Backlog (Expert Panel Recommendations)

### 1. Portfolio Correlation Guard
- Block if 3+ same-direction USD or EUR exposure open simultaneously
- Prevents correlated drawdowns on macro moves

### 2. Backtest Alternative SL Strategy
- Test 0.3x ATR trailing stop (current: 1.0x ATR for KZ_HUNT)
- May improve risk-adjusted returns

### 3. Regime Filter
- 20-day volatility percentile
- Reduce size or skip entries in extreme low/high vol regimes

### 4. Monte Carlo Simulation
- 10K equity curve runs with randomized trade order
- Quantify drawdown risk and ruin probability

### 5. Per-Pair Daily Trade Limit
- Max 2 KZ_HUNT entries per pair per day
- Prevents overtrading a single instrument in choppy conditions

### 6. Portfolio-Level Backtest
- Run all 8 pairs simultaneously with concurrent trade limits, correlation blocking, and circuit breakers active
- Current per-pair backtests don't capture trade selection effects from risk gates

### 7. Scoring Weight Re-Evaluation
- Use `pattern_metadata` (now being collected since 2026-04-15) to run logistic regression on trade outcomes
- Determine which scoring components actually predict profitability
- Current weights (25/20/20/15/20) are unjustified by data

### 8. Correlation-Aware Position Sizing
- Scale lot size down when multiple correlated pairs are open simultaneously
- e.g., if 3 EUR pairs open, reduce next EUR pair's lot by 50%

## Completed (2026-04-15 Assessment)

- ~~Rolling Sharpe calculation~~ — fixed: uses daily equity returns instead of raw pips
- ~~pattern_metadata never populated~~ — now stores KZ session, range, extremes, rejection price
- ~~pnl_estimated flag~~ — new column on TradeRecord, set at both estimated-close paths
- ~~Performance monitor alerts silenced~~ — re-enabled
- ~~Thread watchdog~~ — scanner checks if trade monitor is alive, auto-restarts
- ~~Volume scorer fallback rewarding missing data~~ — changed from 7.5 to 0
- ~~time.sleep(10) blocking trade monitor~~ — replaced with deferred retry
- ~~Deal matching/PnL estimation duplicated~~ — extracted to shared deal_utils.py
- ~~No DB backup~~ — daily GZip backup at 22:00 UTC, 7-day retention
- ~~Missing news filter for EURJPY/CHFJPY~~ — added to SYMBOL_CURRENCIES
- ~~Entry confirmation using forming bar~~ — aligned to use completed bars like detection
- ~~Telegram summary PnL/equity mismatch with MT5~~ — daily PnL from balance change, equity chart from snapshots
- ~~/equity command broken~~ — updated to use snapshot-based chart method
- ~~_detach_record missing pattern_metadata~~ — caused orphaned MT5 positions with no DB record; fixed with getattr fallback
- ~~4 orphaned EURUSD positions~~ — closed manually (+$59.74), caused by pattern_metadata bug above

## Code Polish (Low Priority)

- Equity snapshot table pruning (~43k records/month, no archival)
- Fix return type annotations on `close_position`/`partial_close` in order_manager.py
- Remove dead imports for disabled pattern detectors in main.py
- Add test coverage: risk manager, deal matching, split-order logic
- Auto-adopt orphan positions: reconciliation detects unknown positions with bot magic number but only logs warnings, doesn't create DB records for them
