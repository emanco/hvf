# HVF Auto-Trader — Project Brief (Revised)
**Date:** March 2026
**Status:** v1 implementation complete, ready for demo testing

---

## What We Are Building

A fully automated trading bot based on **Francis Hunt's Hunt Volatility Funnel (HVF)** methodology. The bot:

- Scans EURUSD and GBPUSD on 1H timeframe for valid HVF patterns
- Scores each pattern using a rule-based 6-component scorer (0-100)
- Executes trades via MetaTrader 5 with professional risk management
- Uses confirmed candle-close entry (not pending stop orders) for fewer false breakouts
- Targets 1:3+ reward-to-risk ratios with systematic partial closes and trailing stops

---

## Key Decisions (Revised from Expert Review)

| Decision | Original | Revised | Reason |
|----------|----------|---------|--------|
| Starting capital | £1,000 | £500 | Realistic starting point |
| Risk per trade | 2% | 1% | Conservative until system validated |
| Instruments | XAUUSD, EURUSD, BTCUSD, GBPJPY, US30 | EURUSD, GBPUSD only | Properly sizeable at £500 |
| Max concurrent | 3 | 2 | Capital constraint |
| AI/ML layer | XGBoost after 50 trades | Deferred to v2 (200+ trades) | Insufficient data for ML |
| Nightly optimization | Optuna 100 trials | Monthly manual review | Avoids curve-fitting |
| Entry method | Pending stop above 3H | Confirmed candle close + volume spike | Fewer false breakouts |
| Zigzag method | scipy argrelextrema | ATR-adaptive percentage zigzag | Adapts to volatility |
| Return projections | 22%/month | Not projected | Unrealistic to forecast |

---

## HVF Theory — Core Logic

Three waves compress inside a funnel. Each wave is smaller than the last. Entry fires on breakout from the tightest wave, with the stored energy (Wave 1 range) projected as the target.

### 6 Rules (All Must Pass)
1. Three descending highs: `1H > 2H > 3H`
2. Three ascending lows: `1L < 2L < 3L`
3. Strict alternation: H-L-H-L-H-L chronologically
4. Funnel converges: `(1H-1L) > (2H-2L) > (3H-3L)`
5. Prior trend: price at 1H above 200 EMA (bullish)
6. Volume contracts during funnel

### 5 Additional Filters
1. Wave 1 minimum range > 2x ATR14
2. Wave 3 duration <= 3x Wave 1 duration
3. ADX(14) > 20 (trending market)
4. 4H EMA200 trend confirmation
5. Pattern expires after 48 bars with no breakout

### Entry/Exit
```python
# LONG
entry  = confirmed 1H candle close above (3H + 3 pip buffer)
       + volume > 1.5x 20-bar average
sl     = 3L - (1.0 * ATR_14)
target_1 = midpoint + (full_range * 0.5)   # close 50%
target_2 = midpoint + full_range            # full target
# Only trade if RRR >= 3.0
```

---

## Risk Management

```
RISK_PCT                  = 1.0%    per trade
DAILY_LOSS_LIMIT          = 3.0%    pause until midnight UTC
WEEKLY_LOSS_LIMIT         = 5.0%    pause until Monday 00:00 UTC
MONTHLY_LOSS_LIMIT        = 10.0%   pause until 1st 00:00 UTC
MAX_CONCURRENT_TRADES     = 2
MAX_SPREAD_PCT_OF_STOP    = 5%
MAX_MARGIN_USAGE          = 50%
```

Correlation guard: EURUSD/GBPUSD — only take the higher-scored if both trigger same direction.

---

## Project Structure

```
hvf_trader/
    config.py                     # All settings and thresholds
    main.py                       # 3-thread orchestrator
    requirements.txt
    .env.example                  # Credentials template

    detector/
        zigzag.py                 # ATR-adaptive zigzag
        hvf_detector.py           # 6-rule + 5-filter validation
        pattern_scorer.py         # 6-component scorer (0-100)

    execution/
        mt5_connector.py          # Connection, reconnection, heartbeat
        order_manager.py          # Market orders, modify, partial/full close
        trade_monitor.py          # 30s loop: partials, trailing, invalidation

    risk/
        position_sizer.py         # Lot size calculator
        risk_manager.py           # 8-check pre-trade gate
        circuit_breaker.py        # Daily/weekly/monthly loss caps

    data/
        data_fetcher.py           # OHLCV + ATR/EMA/ADX indicators
        news_filter.py            # calendar_events wrapper

    database/
        models.py                 # SQLAlchemy: patterns, trades, events, snapshots
        trade_logger.py           # Log every event to DB + rotating files

    alerts/
        telegram_bot.py           # Trade alerts + daily summary

    monitoring/
        health_check.py           # MT5 heartbeat, reconnection
        reconciliation.py         # Internal vs MT5 position sync

    backtesting/
        backtest_engine.py        # Event-driven, reuses detector/risk code
        walk_forward.py           # 6mo train / 2mo test sliding windows

    tests/
        test_position_sizer.py
        test_zigzag.py
        test_circuit_breaker.py
```

---

## Instruments Scaling Roadmap

| Account Size | Instruments | Timeframes |
|---|---|---|
| £500 (start) | EURUSD, GBPUSD | 1H primary, 4H confirmation |
| £1,000+ | AUDUSD, USDJPY | Same |
| £3,000+ | XAUUSD, GBPJPY | 4H primary for gold/GBPJPY |
| £10,000+ | BTCUSD, US30 | Daily for indices |

---

## Next Steps

1. **Demo testing**: Connect to MT5 demo account, run for 2+ weeks
2. **Visual validation**: Plot detected patterns on charts, verify against TradingView
3. **Walk-forward backtest**: 2+ years of data, confirm positive OOS profit factor
4. **Go-live checklist**: 30+ items covering detection, execution, risk, operations
5. **Production**: Windows service via NSSM on AccuWebHosting VPS
