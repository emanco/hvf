# HVF Auto-Trader — Backlog

Last updated: 2026-03-30

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
