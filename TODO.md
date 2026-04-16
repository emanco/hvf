# HVF Auto-Trader — Backlog

Last updated: 2026-04-16

## Active Strategies

### KZ Hunt — LIVE (collecting post-fix data)
- [x] Entry confirmation bug fixed (forming bar → completed bar)
- [ ] Collect 30-50 post-fix trades to validate WR improvement
- [ ] If WR stays below 45% after 50 trades, needs fundamental review
- Live WR: 36% (69 trades) vs 61% backtest. Bug fix should improve this.

### London Breakout — LIVE (first trade next Monday)
- [x] Built and deployed (GBPUSD Mon-Tue, rng 12-20, TP=1.0x, exit@13)
- [x] Backtested: PF 1.77, 66% WR, +575p over 8 years
- [ ] Collect 20+ live trades to validate

### Quantum London — LIVE (first trade tonight)
- [x] Built and deployed (EURGBP Mon-Thu, T8/T5/S18, both dirs, 5% risk)
- [x] Daily open at 22:00 UTC (GMT+2) — critical timezone fix
- [x] Backtested: 95% WR, PF 17.86, +415p over 8 months (119 trades)
- [x] Same-day news filter (skip central bank days)
- [ ] Collect 50+ live trades to validate
- [ ] Consider EURCHF as second pair (backtested negative — needs more research)

### Asian Gravity — DISABLED
- Superseded by Quantum London (same pair, better params, 95% vs 79% WR)

## Infrastructure

### Local Backtesting
- [x] CSV data exported from VPS: 9 pairs x H1 (8yr) + M5 (8mo) at backtests/data/
- [ ] Fix KZ Hunt local backtest — needs full indicator pipeline matching fetch_and_prepare
- [ ] Periodic re-export of newer data from VPS

### Strategy Research Pipeline
- Research report: `STRATEGY_RESEARCH_2026-04-16.md`
- Quantum London report: `QUANTUM_LONDON_REPORT.md`

### 1. EMA 200 Pullback + ADX (backtested negative — needs refinement)
- Backtested with basic params: PF 0.86, -5,424p. Needs additional filters or different approach.

### 2. Keltner Channel Breakout (backtested negative)
- Backtested: PF 0.90, -11,839p. Simple trend-following doesn't work on forex H1.

### 3. ICT Silver Bullet (high potential, moderate complexity)
- Three 1-hour windows per day for liquidity sweep reversals
- Similar to KZ Hunt (fade fake moves) but on M1-M5 with tight time windows
- Active ForexFactory thread with MT5 EAs: thread #1343550
- Challenge: automating Fair Value Gap detection
- Pairs: EURUSD, GBPUSD | Timeframe: M1-M5

### 4. Asian Range False-Breakout (natural London Breakout hedge)
- Price breaks Asian range at London open then reverses back inside
- Opposite of London Breakout — catches the days LB hits SL
- Structurally anti-correlated with London Breakout
- GitHub reference implementation exists
- Pairs: GBPUSD | Timeframe: M5-H1

### 5. Quiet-Hours Mean Reversion (BB + RSI)
- [ ] Verify IC Markets quiet-hour spreads on cross pairs
- [ ] Backtest BB(20,2) + RSI(14) during 21:00-01:00 UTC
- Fills time gap between London close and Asian open
- Pairs: AUDNZD, NZDCAD, AUDCAD | Timeframe: M15

### 6. Opening Range Breakout (ORB)
- [ ] Backtest first 15-30 min breakout at London/NY open
- Needs M5 data infrastructure
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
