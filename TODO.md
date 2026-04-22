# HVF Auto-Trader — Backlog

Last updated: 2026-04-22

## Active Strategies

### KZ Hunt — LIVE (post-fix PF 1.31 on 15 trades)
- [x] Entry confirmation bug fixed (forming bar → completed bar, 2026-04-15)
- Post-fix: 15 trades, **73% WR, PF 1.31**, +$172 DB / +$396 balance Δ (5 days)
- Lifetime since go-live: 79 trades, balance down 8.3% (pre-fix period dominates)
- [ ] Collect 35+ more post-fix trades to confirm edge holds (target: 50 total)
- [ ] If PF drifts below 1.0 at 30+ post-fix trades, stop and rethink

### London Breakout — LIVE (never actually traded yet)
- [x] Built and deployed (GBPUSD Mon-Tue, rng 12-20, TP=1.0x, exit@13)
- [x] Backtested: PF 1.77, 66% WR, +575p over 8 years
- [x] Tested other GBP pairs — only GBPUSD works (GBPAUD/CAD/NZD/CHF all negative)
- [x] bar_time crash fixed (2026-04-21); Tue 4/21 range locked OK, news-filter skipped
- [x] Windowed news filter (00:00–13:00 UTC) — 2026-04-22
- [x] Telegram alerts on range-locked + session-skipped
- [ ] Collect 20+ live trades to validate (next opportunity: Mon 2026-04-27)

### Quantum London — LIVE (captured twice, never triggered)
- [x] Built and deployed (EURGBP Mon-Thu, T8/T5/S18, both dirs, 5% risk)
- [x] Daily open at 22:00 UTC (GMT+2) — critical timezone fix
- [x] Backtested: 95% WR, PF 17.86, +415p over 8 months (119 trades)
- [x] Same-day news filter (skip central bank days)
- [x] Force-exit bug fixed (22>=5 killed session at open) — fixed Apr 17
- [x] Day filter verified: days=[1,2,3,4] at trading time = Mon-Thu nights ✓
- [x] Daily-open reset bug fixed (2026-04-20) — dead-code reset branch, flag never reset
- [x] Telegram alerts on daily-open capture + news-filter skip
- [x] Captured 2026-04-20 (no trigger, 6-pip range), 2026-04-21 (news-filtered by GBP CPI)
- [ ] Collect 50+ live trades to validate

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

### H1 — PnL silently zeroed when MT5 deal lookup fails
- When `mt5.history_deals_get` returns empty for a stopped-out trade, the close handler logs PnL=0 with `pnl_estimated=False`
- Real losses are hidden from DB reporting while balance changes correctly in MT5 (so /balance is right, but trade-level PnL and PF are wrong)
- Observed last week (4/13): 4 KZ_HUNT stop-outs (trades 96, 98, 99, 101) reported PnL=0 in DB but actually lost ~$410 combined per equity_snapshots balance deltas
- Impact: weekly PF 0.96 (reconciled) vs 1.50 (headline from DB sums) — materially misleading for strategy evaluation
- **Fix**: in deal-lookup fallback path, estimate PnL as `pips × pip_value × lot_size`, set `pnl_estimated=True`. Files: `execution/trade_monitor.py`, `execution/deal_utils.py`
- **Priority**: High — distorts every performance metric

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
- [x] JPY-group guard shipped 2026-04-22 (blocks 2nd same-direction JPY-cross entry)
- [ ] Extend to USD group (3+ same-direction USD pairs)
- [ ] Extend to EUR group (3+ same-direction EUR pairs)
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

## Completed (2026-04-22 Session — commit 9aba719)

- ~~QL daily-open reset bug~~ — dead-code reset branch; flag never reset across days
- ~~LB bar_time crash~~ — `df.index[-1]` (int) → `df["time"].iloc[-1]` (Timestamp)
- ~~Per-(pattern, symbol) consecutive-loss circuit breaker~~ — new DB table, auto-seeded from trade history, 3-loss pause for 48h
- ~~record_pattern_result was dead code~~ — now wired from `log_trade_close`, uses pnl_pips so estimation bug doesn't mask losses
- ~~JPY-group correlation guard~~ — blocks 2nd same-direction JPY-cross entry
- ~~LB news filter~~ — tightened to window-based (00:00–13:00 UTC) vs whole-day
- ~~News-cache refresh order~~ — moved to top of scanner loop (no more stale-cache false blocks)
- ~~Scanner-loop fragility~~ — each section in its own try/except (one crash no longer skips the cycle)
- ~~QL/LB Telegram parity~~ — alerts on capture, range-locked, session-skipped
- ~~MT5 heartbeat 60s → 30s~~ — halves disconnect detection latency
- ~~mt5_connector reconnect bug~~ — `_disconnect_since` cleared by `connect()` before elapsed calc; now captured locally
- ~~circuit_breaker._load_state tzinfo crash~~ — DB datetimes normalized to UTC-aware; prevents startup TypeError once any level has tripped
- ~~Daily execution review~~ — new `monitoring/daily_review.py`, automated report at 21:30 UTC + `/review` command
- ~~Demo loss limits~~ — raised to 10/20/30% for data collection (was 5/8/15)

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
