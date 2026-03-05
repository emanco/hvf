# HVF Auto-Trader Project Memory

## Project Overview
- HVF (Hunt Volatility Funnel) automated forex trading bot
- Deployed to VPS: 198.244.245.3 (SSH alias: `hvf-vps`, Windows Server, PowerShell)
- MT5 demo: IC Markets, login 52774919 (runs headless via Python, no GUI needed)
- Starting capital: £500, instruments: EURUSD + GBPUSD
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

### Phase 2: Detection — COMPLETE (with post-backtest fixes)
- detector/zigzag.py — ATR-adaptive zigzag pivot detection
- detector/hvf_detector.py — 6-rule validation + 5 filters (relaxed to "funnel shape" geometry)
- detector/pattern_scorer.py — 6-component scorer (0-100), RRR recalibrated to 4:1

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
HVF_MIN_RRR = 1.5
WAVE1_MIN_ATR_MULT = 1.5
WAVE3_MAX_DURATION_MULT = 5.0
ADX_MIN_TREND = 15
PATTERN_EXPIRY_BARS = 100
VOLUME_SPIKE_MULT = 1.2
SCORE_THRESHOLD = 40
RISK_PCT = 1.0
MAX_CONCURRENT_TRADES = 2
```

## Known Limitations & Open Issues
1. **Very low trade frequency**: 5 trades across 2+ years (EURUSD 4, GBPUSD 1)
2. **GBPUSD sizing**: wide ATR-based stops + £500 capital → lots floor to 0.00 for many patterns
3. **Walk-forward**: only 3 OOS trades total — insufficient for statistical confidence
4. **No SHORT trades found**: all detected patterns were LONG in the test period
5. **Demo validation not started**: need the bot running live on demo to accumulate 20+ trades

## What Was Tried During Debugging
- diagnose1-6.py scripts (now deleted) traced the pipeline stage by stage
- Stale filter was killing all full-dataset patterns (only last 100 bars of 20,000 survived)
- Rolling 500-bar window approach works correctly for incremental detection
- Score distribution centered around 35-55 with current config — threshold 40 captures most
- Volume spike at 1.2x passes ~80% of price-confirmed entries

## Potential Next Steps (not yet requested)
- **Increase trade frequency**: lower zigzag multiplier (try 1.5), relax convergence ratio (1.5→1.2), scan additional timeframes
- **Visual validation**: plot detected patterns on candlestick charts to verify quality
- **Start demo run**: launch main.py on VPS to accumulate live demo trades
- **Unit tests**: pytest suite for zigzag, detector, scorer, position sizer
