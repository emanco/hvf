# HVF Auto-Trader — Backlog

Last updated: 2026-04-16

## Asian Gravity Strategy — LIVE
- [x] Built and deployed (Thursday SHORT EURGBP, T5/T2/S8, rng<20)
- [x] Same-day news filter (skip central bank days)
- [ ] Collect 20+ live trades to validate 79% WR
- [ ] Consider adding Friday after validation
- [ ] Consider tighter range filter (rng<12) if WR holds

## New Strategies Pipeline (research: `STRATEGY_RESEARCH_2026-04-16.md`)

### 1. London Breakout — NEXT BUILD
- [ ] Backtest on H1 data (Asian range high/low breakout at London open)
- [ ] Build detector + scorer
- [ ] Conflict resolution with KZ Hunt (same session, opposite logic)
- [ ] Deploy and validate
- Pairs: GBPUSD, EURUSD, GBPJPY | Timeframe: H1 | Claimed PF: >1.5

### 2. EMA 200 Pullback + ADX
- [ ] Backtest pullback-to-EMA-zone entries when ADX > 25
- [ ] Build detector (uses existing indicators: EMA 200, ADX 14, ATR 14)
- [ ] Natural hedge for KZ Hunt — profits when trends are strong
- Pairs: majors | Timeframe: H1 entry, H4/D1 trend filter

### 3. Keltner Channel Breakout
- [ ] Backtest Keltner (EMA 20 +/- 2x ATR) breakouts with ADX confirmation
- [ ] Zero new indicators — EMA + ATR already computed
- [ ] Fires on volatility expansion (opposite to KZ Hunt's regime)
- Pairs: majors | Timeframe: H4

### 4. Quiet-Hours Mean Reversion (BB + RSI)
- [ ] Verify IC Markets quiet-hour spreads on cross pairs first
- [ ] Backtest BB(20,2) + RSI(14) on AUDNZD, AUDCAD, NZDCAD during 21:00-01:00 UTC
- [ ] New scanner thread for quiet hours
- Pairs: crosses | Timeframe: M15

### 5. Opening Range Breakout (ORB)
- [ ] Backtest first 15-30 min breakout at London/NY open
- [ ] Needs M5 data (same infra as Asian Gravity)
- Pairs: GBPUSD, EURUSD | Timeframe: M5

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
