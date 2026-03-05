# HVF Auto-Trader Architecture

## File Structure
```
hvf_trader/
    config.py                     # All settings and thresholds (single source of truth)
    main.py                       # 3-thread orchestrator: scanner + monitor + health
    requirements.txt
    .env                          # MT5 credentials, Telegram token (never committed)

    detector/
        zigzag.py                 # ATR-adaptive zigzag pivot detection
        hvf_detector.py           # HVF 6-rule validation + 5 filters
        pattern_scorer.py         # 6-component scorer (0-100)

    execution/
        mt5_connector.py          # Connection, reconnection, heartbeat
        order_manager.py          # Market orders, modify SL, partial/full close
        trade_monitor.py          # 30s loop: partials, trailing, invalidation

    risk/
        position_sizer.py         # Lot size from equity, risk%, stop distance
        risk_manager.py           # Pre-trade gate: 8 sequential checks
        circuit_breaker.py        # Daily/weekly/monthly loss caps with DB persistence

    data/
        data_fetcher.py           # OHLCV from MT5 + ATR/EMA/ADX indicators
        news_filter.py            # mt5.calendar_events() wrapper

    database/
        models.py                 # SQLAlchemy: patterns, trades, events, snapshots
        trade_logger.py           # Log every event to DB + file

    alerts/
        telegram_bot.py           # Trade alerts + daily summary + errors

    monitoring/
        health_check.py           # MT5 heartbeat, resource checks
        reconciliation.py         # Internal state vs MT5 positions sync

    backtesting/
        backtest_engine.py        # Event-driven backtester (reuses detector/risk code)
        walk_forward.py           # Rolling window out-of-sample validation
        run_backtest.py           # Backtest runner script (fetches data, runs both instruments)

    tests/                        # pytest unit tests (mostly stubs, not fleshed out yet)
```

## Detection Pipeline
1. `compute_zigzag()` — ATR-adaptive pivots (threshold = ATR% × ZIGZAG_ATR_MULTIPLIER)
2. `detect_hvf_patterns()` — Slide 6-pivot windows, validate funnel shape + 5 filters
3. `score_pattern()` — 7 components: tightness(20), volume(15), ATR(15), RRR(20), EMA200 trend(10), MTF(10), session(10)
4. Score >= SCORE_THRESHOLD → ARM pattern
5. Entry confirmation: candle close past entry + volume spike > VOLUME_SPIKE_MULT × 20-bar avg
6. 8 risk checks → position sizing → execute market order with SL

## HVF Validation Rules (current "funnel_shape" mode)
**Hard gates (must pass):**
- Bullish: h1>h3 AND h2>h3 (descending highs overall), l3>l1 AND l3>l2 (ascending lows overall)
- Bearish: h3>h1 AND h3>h2 (ascending highs), l1>l3 AND l2>l3 (descending lows)
- Convergence: wave1_range > 1.2 × wave3_range
- ADX > 15 at pattern midpoint
- Wave1 range > 1.5 × ATR
- Wave3 duration ≤ 5 × Wave1 duration
- Pattern not stale (< 100 bars since last pivot)

**Soft components (in scorer):**
- Volume contraction (0-15 pts)
- ATR contraction (0-15 pts)
- EMA200 prior trend (0/5/10 pts) — moved from hard gate
- 4H trend confirmation (0/5/10 pts)
- Session quality (0-10 pts)

## Trade Management
- Partial close: 50% at target_1, move SL to breakeven
- Trailing stop: 1.5 × ATR below highest price since partial (LONG) / above lowest (SHORT)
- Full close at target_2
- End-of-data close in backtest

## Backtest Engine Key Details
- 500-bar rolling window, scans every bar starting from bar 250
- `triggered_pattern_keys` set prevents same pattern triggering multiple trades
- Entry sanity check: skip if price already past target_1
- Stop distance uses actual bar close (not theoretical entry price)
- Position sizing with lot validation (0.00 lots = skip)
