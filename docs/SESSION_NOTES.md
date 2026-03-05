# HVF Auto-Trader Project Memory

## Project Overview
- HVF (Hunt Volatility Funnel) automated forex trading bot
- Deployed to VPS: 198.244.245.3 (SSH alias: `hvf-vps`, Windows Server, PowerShell)
- MT5 demo: IC Markets, login 52774919 (runs headless via Python, no GUI needed)
- Starting capital: £500, instruments: EURUSD only (GBPUSD at ~£750, AUDUSD at £1K+, USDJPY at £3K+)
- Tech: Python, MetaTrader5 lib, SQLAlchemy, Telegram alerts
- Repo: https://github.com/emanco/hvf.git (branch: main)

## Key Files
- See [architecture.md](architecture.md) for full file structure
- Core pipeline: zigzag → detect_hvf → score → arm → confirm entry → execute
- Backtest engine reuses same detector/risk code

## VPS Details
- SSH: `ssh hvf-vps` (alias configured locally)
- Project path on VPS: `C:\hvf_trader\` (NOT /root/hvf_trader/)
- Sync files via: `scp <local_file> hvf-vps:"C:/hvf_trader/<path>"`
- Python venv at `C:\hvf_trader\venv\`
- Run scripts: `ssh hvf-vps "cd C:\hvf_trader && venv\Scripts\python <script>"`

---

## Build Phases & Progress

### Phase 1: Foundation — COMPLETE
- config.py, .env, requirements.txt
- database/models.py + trade_logger.py (SQLAlchemy)
- execution/mt5_connector.py + data/data_fetcher.py (MT5 connection, OHLCV + indicators)

### Phase 2: Detection — COMPLETE (with post-backtest tuning)
- detector/zigzag.py — ATR-adaptive zigzag pivot detection
- detector/hvf_detector.py — 6-rule validation + 5 filters (funnel shape geometry, EMA200 moved to scorer)
- detector/pattern_scorer.py — 7-component scorer (20+15+15+20+10+10+10=100), RRR calibrated to 4:1

### Phase 3: Risk — COMPLETE
- risk/position_sizer.py — lot sizing from equity, risk%, stop distance
- risk/risk_manager.py — 8-check pre-trade gate
- risk/circuit_breaker.py — daily/weekly/monthly loss caps

### Phase 4: Execution — COMPLETE
- execution/order_manager.py — market orders, modify SL, partial/full close
- execution/trade_monitor.py — 30s loop: partials, trailing, invalidation

### Phase 5: Integration — COMPLETE
- main.py — 3-thread orchestrator (scanner, monitor, health), graceful shutdown
- monitoring/health_check.py + reconciliation.py
- data/news_filter.py
- alerts/telegram_bot.py — detection, entry, partial, exit, daily summary, errors

### Phase 6: Validation — IN PROGRESS
- backtesting/backtest_engine.py — DONE, debugged and working
- backtesting/walk_forward.py — DONE, implemented
- backtesting/run_backtest.py — DONE, runner script
- **Demo full validation** — NOT STARTED (need 20+ demo trades over 2+ weeks)
- **Backtest results so far**: see [backtest-results.md](backtest-results.md)

### Phase 7: Go Live — NOT STARTED
- Windows service via NSSM
- Switch to live credentials
- Start EURUSD only for 2 weeks then add GBPUSD

---

## Current Config Values
```
ZIGZAG_ATR_MULTIPLIER = 2.0
HVF_ATR_STOP_MULT = 0.5
HVF_MIN_RRR = 1.0                # relaxed from 1.5
WAVE1_MIN_ATR_MULT = 1.5
WAVE3_MAX_DURATION_MULT = 5.0
ADX_MIN_TREND = 15
PATTERN_EXPIRY_BARS = 100
VOLUME_SPIKE_MULT = 1.2
SCORE_THRESHOLD = 40
RISK_PCT = 1.0
MAX_CONCURRENT_TRADES = 2
# Convergence ratio: 1.2x (in hvf_detector.py, relaxed from 1.5x)
# EMA200 prior trend: moved from hard gate to soft scorer component (0-10 pts)
```

## Known Limitations & Open Issues
1. **Trade frequency still low**: 18 trades across 2+ years (EURUSD 11, GBPUSD 6, AUDUSD 1, USDJPY 0)
2. **GBPUSD net negative**: PF 0.76, -10.2 pips. Many patterns blocked by position sizing (lots=0.00)
3. **Walk-forward weak**: EURUSD 7 OOS trades/57% WR/PF 0.48, GBPUSD 3 OOS trades/33% WR/PF 0.12
4. **All trades LONG**: no SHORT patterns detected in 2+ years of data
5. **USDJPY untradeable at £500**: pip_value_per_lot=1000, all lot sizes floor to 0.00
6. **AUDUSD too infrequent**: only 1 trade in available history (~1 year of data)
7. **Demo validation not started**: need the bot running live on demo to accumulate 20+ trades

## What Was Tried During Debugging & Tuning
- diagnose1-6.py scripts (now deleted) traced the pipeline stage by stage
- Stale filter was killing all full-dataset patterns (only last 100 bars of 20,000 survived)
- Rolling 500-bar window approach works correctly for incremental detection
- Score distribution centered around 35-55 with current config — threshold 40 captures most
- Volume spike at 1.2x passes ~80% of price-confirmed entries
- **Filter diagnostic** (filter_diagnostic.py, deleted): tested each filter independently on all 6-pivot windows
  - Top blockers: RRR (94% rejection), convergence (75%), geometry (62%), EMA200 (34%)
  - Marginal kills were 0 for all except stale — filters overlap heavily
  - Led to 3 relaxations: convergence 1.5→1.2, EMA200 to scorer, RRR 1.5→1.0
  - Result: trade count tripled (5→17), EURUSD PF 3.16
- **4-pair diversification test** (Run 3): tested EURUSD, GBPUSD, AUDUSD, USDJPY
  - AUDUSD: 1 trade (+25.4 pips), too infrequent to matter
  - USDJPY: 0 trades, all lots floor to 0.00 at £500 (pip_value_per_lot=1000)
  - Conclusion: stick with EURUSD-only at £500, scale instruments with account growth

## Potential Next Steps (not yet requested)
- **Visual validation**: plot detected patterns on candlestick charts to verify quality
- **Start demo run**: launch main.py on VPS to accumulate live demo trades
- **Unit tests**: pytest suite for zigzag, detector, scorer, position sizer
- **Further frequency improvements**: lower zigzag multiplier (try 1.5), add H4 timeframe
- **Investigate GBPUSD losses**: why PF < 1? Position sizing or pattern quality?
