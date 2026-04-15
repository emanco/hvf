# Asian Range Scalper — Strategy Design Document

**Date**: 2026-04-15
**Status**: Design phase — backtest required before any live trading
**Complements**: KZ Hunt (session reversals, needs volatility)

---

## Executive Summary

Trade mean-reversion within the Asian session range. Price compresses during 00:00-06:00 UTC when London/NY are closed. Buy at range low, sell at range high, exit before London opens. Small targets (5-15 pips) but high win rate (62-67%) allows larger position sizing. Expected portfolio Sharpe improvement of 50-80% when combined with KZ Hunt.

**Critical risk**: Spread costs. The difference between 1.0 and 2.0 pip round-trip spread represents ~40% of per-trade expectancy. Asian spreads are 2-4x wider than London. The backtest MUST model realistic Asian spreads or results are meaningless.

---

## 1. Session Timing

| Window | UTC Hours | Purpose |
|--------|-----------|---------|
| Range Formation | 00:00 - 02:00 | Establish session high/low from M5 bars. No trades. |
| Trading Window | 02:00 - 06:00 | Execute mean-reversion trades within the range |
| Breakeven Move | 06:15 | Move open SLs to breakeven if 3+ pips in profit |
| Forced Exit | 06:30 | Hard close ALL positions. No exceptions. |

**Monday**: Skip entirely if Sunday open gap > 15 pips. If gap < 15 pips, extend formation to 00:00-03:00 UTC.
**Sunday night**: Skip entirely (gaps, thin liquidity, wide spreads).
**Friday**: Normal trading — session ends well before weekend.

---

## 2. Range Definition

- **Source**: High/low of M5 bars during formation window (00:00-02:00 UTC, 24 bars)
- **Validation**: Range must be touched on both sides during formation (at least one bar within 3 pips of high AND one bar within 3 pips of low). A one-directional drift is a trend, not a range.
- **Minimum range**: 15 pips (below this, spread eats the edge)
- **Maximum range**: 35 pips (above this, session is trending, not ranging)

---

## 3. Entry Rules

Two-step confirmation, not blind limit orders:

1. **Proximity trigger**: Price comes within 2 pips of range extreme
2. **Rejection confirmation**: Current M5 bar closes back inside the range by at least 3 pips
3. **Market order** at M5 bar close price

Entry buffers:
- Long: confirmed close >= Range Low + 3 pips
- Short: confirmed close <= Range High - 3 pips

**Re-entry**: One re-entry allowed per direction per session, but only if the stop was hit by a wick (price returned inside range on same/next bar). If stopped by a body close beyond the range, the range is broken — no re-entry that direction.

**Maximum entries per session**: 4 total (including re-entries)

---

## 4. Exit Rules

**Take Profit** (set on MT5 at order placement):
- Long TP: Range High - 3 pips
- Short TP: Range Low + 3 pips

**Stop Loss** (set on MT5 at order placement):
- Long SL: Range Low - max(5 pips, 0.3 x range width)
- Short SL: Range High + max(5 pips, 0.3 x range width)

**Time-based exit**:
- 06:15 UTC: Move SL to breakeven if 3+ pips in profit
- 06:30 UTC: Force close all positions at market

**No partial close, no trailing stop** — targets are too small for split management.

| Range Width | Net Target | Stop Distance | RRR |
|------------|-----------|--------------|-----|
| 15 pips | ~7 pips | ~9.5 pips | 0.74 |
| 20 pips | ~12.5 pips | ~10 pips | 1.25 |
| 25 pips | ~17.5 pips | ~12.5 pips | 1.40 |
| 35 pips | ~27.5 pips | ~15.5 pips | 1.77 |

Sub-1.0 RRR on narrow ranges is acceptable only because expected win rate is 62-67%.

---

## 5. Pair Selection

**Launch pairs**: EURGBP + USDCHF

| Rank | Pair | Typical Asian Range | Asian Spread | Spread Margin | Verdict |
|------|------|-------------------|-------------|---------------|---------|
| 1 | **EURGBP** | 15-20 pips | 0.8-1.2 pips | Thin (+1.0 pip) | Primary. Both currencies asleep. Best mean-reversion. |
| 2 | **USDCHF** | 22-28 pips | 1.0-1.5 pips | Good (+3.0 pips) | Secondary. CHF quiet in Asian. Decent ranges. |
| 3 | AUDNZD | 12-22 pips | 1.5-2.5 pips | Moderate | Add after 50+ trades if spreads confirm < 2.0 pips |
| 4 | NZDUSD | 15-30 pips | 1.0-1.5 pips | Good | Conditional — NZD active during Asian, higher skip rate |
| 5 | EURUSD | 15-30 pips | 0.5-1.0 pips | Good (+3.6 pips) | Conditional — prone to directional moves |
| 6 | EURAUD | 35-45 pips | 2.0-3.5 pips | Marginal (+0.6 pips) | Avoid — wide spreads eat the edge |
| 7 | GBPJPY | 25-50 pips | 2.5-4.0 pips | Negative | Avoid — too volatile, BOJ risk, wide spreads |

---

## 6. Filters

All filters are mandatory unless noted:

| Filter | Rule | Purpose |
|--------|------|---------|
| Range width | 15-35 pips | Too narrow = spread-eaten, too wide = trending |
| ADX(14) on M15 | Skip if > 25 | Market is trending, not ranging |
| ATR compression | Skip if ATR(14) > SMA(ATR, 20) | Session more volatile than normal |
| Day-of-week | Skip Sunday night; extend Monday formation to 3h | Sunday gaps distort ranges |
| News filter | Skip if high-impact JPY/AUD/NZD/EUR/USD event 00:00-07:00 UTC | Already exists |
| Prior NY volatility | Skip if NY ATR(14) on M15 > 1.5x its 20-period average | High NY vol spills into Asian |
| USDJPY kill switch | If USDJPY moves > 1% in any 30-min window, disable for session | BOJ intervention detection |

---

## 7. Risk Management

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Risk per trade | 0.5% equity | Half of KZ Hunt — thinner edge, higher frequency |
| Max concurrent (scalper) | 2 (one per pair) | Max 1.0% total exposure |
| Max entries per session | 4 | Cap exposure on choppy nights |
| Daily loss limit (scalper) | 2.0% equity | Separate from global 5% circuit breaker |
| Weekly loss limit (scalper) | 4.0% equity | Prevents week-long bleed |
| Max spread (absolute) | 2.0 pips | Kill trades when spread blows out |

**Portfolio integration with KZ Hunt:**

| Strategy | Risk/Trade | Max Concurrent | Max Exposure |
|----------|-----------|----------------|-------------|
| KZ Hunt | 1.0% | 6 | 6.0% |
| Asian Scalper | 0.5% | 2 | 1.0% |
| **Combined** | — | **8** | **7.0%** |

Both strategies count toward the global circuit breaker (5% daily / 8% weekly / 15% monthly).

---

## 8. Expected Performance

| Metric | Estimate | Notes |
|--------|----------|-------|
| Win rate (net) | 62-67% | After spread costs |
| Profit factor | 1.15-1.45 | Thin edge, high frequency |
| Sharpe (annualized) | 1.5-3.0 | High frequency boosts Sharpe |
| Trades per week | 15-25 | Across 2 pairs, ~3-5/day |
| Portfolio Sharpe uplift | +50-80% | vs KZ Hunt alone |
| Kelly fraction | 12.5% (use 0.5% = quarter-Kelly) | Conservative given thin edge |

**Breakeven spread by pair:**

| Pair | Median Range | Target (50%) | Breakeven RT Spread | Actual RT Spread | Margin |
|------|-------------|-------------|--------------------|--------------------|--------|
| EURUSD | 28 pips | 14 pips | 5.6 pips | 2.0 pips | +3.6 |
| USDCHF | 25 pips | 12.5 pips | 5.0 pips | 2.0 pips | +3.0 |
| EURGBP | 18 pips | 9 pips | 3.6 pips | 2.6 pips | +1.0 |
| EURAUD | 40 pips | 20 pips | 5.6 pips | 5.0 pips | +0.6 |

---

## 9. Pre-Strategy Data Analysis (Before Building Anything)

Run these analyses to validate the edge exists. If any pair fails, exclude it.

| Metric | Threshold to Include Pair |
|--------|--------------------------|
| Median Asian range | 12-50 pips |
| Range coefficient of variation | < 0.7 |
| Asian/London range ratio | 0.2-0.7 |
| Containment rate (2h formation) | > 65% |
| Mean-reversion rate (touch to midpoint) | > 60% |
| Median reversion time | < 90 minutes |
| Touches per session | >= 1.5 |
| Round-trip spread / range | < 25% |
| Net expectancy (after spread) | > 1.5 pips |
| Breakout rate | < 30% |
| Hurst exponent (M5, Asian only) | < 0.47 |

**Go/no-go for the strategy**: At least 2 pairs must pass ALL thresholds.

---

## 10. Backtest Validation Criteria

| Criterion | Threshold |
|-----------|-----------|
| OOS trades | >= 250 |
| OOS profit factor | >= 1.15 |
| OOS win rate | >= 58% |
| Max drawdown (at 0.5% risk) | <= 15% |
| Positive OOS windows | >= 65% |
| Cross-pair consistency | >= 2/5 pairs individually profitable |
| Spread stress test (1.5x base spread) | Still profitable |
| Bootstrap PF 5th percentile | > 1.0 |
| Daily PnL correlation with KZ Hunt | < 0.25 |

**Walk-forward design**: 6m train / 2m test / anchored (expanding window). Minimum 5 years M5 data.

---

## 11. Architecture & Implementation

### What works as-is (no changes)
- Data fetcher (`fetch_ohlcv` supports M5/M15)
- Order manager (`place_market_order` with SL+TP)
- Database schema (`pattern_type = "ASIAN_RANGE"`, `pattern_metadata` for range data)
- Trade logger, position sizer, Telegram alerts, health check, reconciliation

### What needs small modifications
- `config.py` — add ASIAN_RANGE entries to all `_BY_PATTERN` dicts (~30 lines)
- `risk_manager.py` — spread tolerance per pattern type, remove same-instrument block for scalper (~40 lines)
- `trade_monitor.py` — pattern_type dispatch + `_check_scalper_trade` for time-based exit (~50 lines)
- `main.py` — register new scanner thread + watchdog (~30 lines)

### What needs building from scratch
- `asian_range_detector.py` — range tracker + boundary touch detection (~200 lines)
- `asian_range_scorer.py` — range quality, time remaining, spread check (~80 lines)
- `asian_range_scanner.py` — live scanner thread with M5 data, own execution loop (~250 lines)
- `asian_range_backtest.py` — M5 backtest engine with session-aware spread model (~400 lines)

**Total estimated new/modified code: ~1,085 lines**

### Build order

**Phase 1: Validate the edge (backtest only)**
1. Config entries for ASIAN_RANGE
2. Asian range detector (range construction + touch detection on M5)
3. Asian range scorer
4. Asian range backtest engine (M5, session-aware spread, time-based exit)
5. Walk-forward validation script
6. **STOP and evaluate.** If PF < 1.15 or WR < 58%, abandon.

**Phase 2: Live infrastructure (only if backtest passes)**
7. Risk manager modifications
8. Trade monitor `_check_scalper_trade`
9. Asian range scanner (live thread)
10. Main.py thread registration + watchdog
11. Per-strategy circuit breaker limits

**Phase 3: Phased go-live**
12. Shadow trading (2 weeks, 0 lots — log signals only)
13. Micro-live (4 weeks, 0.1% risk)
14. Ramp to production (4 weeks, 0.25% then 0.5% risk)

---

## 12. Kill Criteria (When to Shut Down Live)

1. Live PF drops below 1.0 over 100+ trades
2. Live drawdown exceeds 10% at 0.5% risk/trade
3. Daily PnL correlation with KZ Hunt exceeds 0.40 over 60+ days
4. Spread costs exceed 50% of gross profit for 30+ consecutive trades
5. Rolling 30-trade win rate drops below 55%

---

*Compiled from parallel analysis by 5 specialized agents: Infrastructure Researcher, Expert Trader, Quant Analyst, Data Analyst, Senior Software Engineer.*
