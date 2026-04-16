# Strategy Research — ForexFactory Scan Results

**Date**: 2026-04-16
**Objective**: Find strategies to complement KZ Hunt (session reversal, H1) and Asian Gravity (Thursday night EURGBP scalp)

---

## Top 5 Candidates (ranked by fit + feasibility)

### 1. London Breakout (Asian Range Breakout)

**What**: At London open, trade the breakout of the overnight Asian range.
**Rules**: Mark Asian session high/low (00:00-07:00 GMT). Buy stop above + sell stop below at 08:00. SL at opposite side. TP at 1.5x range. Close by end of NY session.
**Pairs**: GBPUSD (best), EURUSD, GBPJPY
**Timeframe**: H1, one trade per day
**Claimed PF**: >1.5 with 1.5:1 RR

**Why it fits**:
- OPPOSITE regime to KZ Hunt — profits from momentum/follow-through, which is exactly when KZ Hunt loses (strong trends)
- Very easy to automate — pending orders + time filter, no indicators
- Trades London open (08:00-11:00), same session as KZ Hunt but different logic
- Natural hedge: when KZ Hunt reversal fails, London Breakout likely wins

**Risk**: Could conflict with KZ Hunt on same pair/session — needs dedup rule
**Build effort**: Very low (~150 lines). Range tracking already exists in killzone_tracker.

**FF threads**: [London Breakout V2](https://www.forexfactory.com/thread/247220), [EA Breakout Asian Session](https://www.forexfactory.com/thread/210035)

---

### 2. Quiet-Hours Mean Reversion Scalper (BB + RSI)

**What**: During quiet hours (21:00-01:00 GMT), trade mean reversion on cross pairs when price deviates beyond Bollinger Bands with RSI confirmation.
**Rules**: BB(20, 2SD) on M15. Enter when price touches outer band AND RSI(14) > 70 or < 30. TP at middle band (5-15 pips). SL beyond the band + ATR buffer.
**Pairs**: AUDNZD, AUDCAD, NZDCAD, EURCHF — low-volatility crosses
**Timeframe**: M15, multiple trades per night
**Claimed WR**: 70-85%, PF 1.3-1.8

**Why it fits**:
- Fills the biggest TIME GAP — 21:00-01:00 UTC, when neither KZ Hunt nor Asian Gravity trades
- Different PAIRS — cross pairs not in the KZ Hunt universe
- Different REGIME — quiet market mean reversion vs session reversal
- Commercial EAs (Evening Scalper Pro, Night Hunter Pro) prove the concept works

**Risk**: Spread widening during quiet hours can eat the 5-15 pip edge. Must verify IC Markets quiet-hour spreads. Evening Scalper Pro showed PF near 1.0 live (edge is razor-thin).
**Build effort**: Medium (~300 lines). New scanner thread for quiet hours + BB/RSI indicators.

**FF threads**: [Extremely Accurate EA](https://www.forexfactory.com/thread/604951), [Night Owl Scalping](https://www.forexfactory.com/thread/641507)

---

### 3. EMA 200 Pullback + ADX Filter (Trend Following)

**What**: On H1, buy pullbacks to the EMA 100-200 zone when the higher timeframe trend is strong.
**Rules**: Trend filter: price above EMA(200) on H4+D1, ADX(14) > 25. Entry: price pulls back to EMA(100)-EMA(200) zone on H1, then closes bullish. SL below EMA(200). TP at 1:2 RR or trail using EMA(100).
**Pairs**: EURUSD, GBPUSD, any trending major
**Timeframe**: H1 entry, H4/D1 trend filter
**Claimed PF**: ~1.5-1.7

**Why it fits**:
- NATURAL HEDGE for KZ Hunt — profits when trends are strong (ADX > 25), which is when KZ Hunt counter-trend entries are most dangerous
- Uses indicators YOU ALREADY COMPUTE (EMA 200, ADX 14, ATR 14)
- Uses H4 data you already fetch (CONFIRMATION_TIMEFRAME)
- Plugs directly into existing detect/score/arm pipeline
- Running both simultaneously: when KZ Hunt gets stopped by a strong trend, this strategy likely has a profitable position

**Risk**: Both strategies could be active on same pair — needs conflict resolution
**Build effort**: Low (~200 lines). New detector + scorer, reuses existing pipeline completely.

**FF threads**: [100EMA/200EMA Pullback](https://www.forexfactory.com/thread/405237), [Pivot + 200 EMA](https://www.forexfactory.com/thread/641385)

---

### 4. Opening Range Breakout (ORB)

**What**: Trade the breakout of the first 15-30 minutes of London or NY session.
**Rules**: Mark high/low of first 15-30 min after session open. Enter when M5 candle closes outside the range. SL at opposite side. TP at 1.5-3x range width. One trade per session.
**Pairs**: GBPUSD, EURUSD
**Timeframe**: M5 for entry, session-based
**Claimed PF**: 2.5 in one documented backtest, 74% WR

**Why it fits**:
- Captures the INITIAL session move before KZ Hunt's session range forms
- Very simple rules — range + breakout + time filter
- Different PHASE of the session lifecycle than KZ Hunt

**Risk**: Limited verified backtests. "Settings change based on market conditions" noted.
**Build effort**: Low (~200 lines). Needs M5 data (same as Asian Gravity scanner approach).

**FF threads**: [My Breakout Strategy](https://www.forexfactory.com/thread/1021656), [Range Break Out EA](https://www.forexfactory.com/thread/1321779)

---

### 5. Keltner Channel Breakout (Volatility Expansion)

**What**: Trade when price breaks out of the Keltner Channel (EMA 20 +/- 2x ATR), confirmed by ADX > 25.
**Rules**: Enter LONG when close > upper Keltner band + ADX > 25. Enter SHORT when close < lower band. Trail using middle line (EMA 20). Exit when price closes back inside channel.
**Pairs**: GBPUSD, EURUSD, majors
**Timeframe**: H4 (recommended) or H1
**Claimed WR**: 35-50% with positive PF (big winners compensate)

**Why it fits**:
- Zero new indicators needed — Keltner = EMA + ATR, both already computed
- Fires when VOLATILITY EXPANDS (trend starts), which is when KZ Hunt struggles
- H4 timeframe = different from KZ Hunt's H1 = less overlap
- Acts as a "do not take KZ Hunt reversal" signal

**Risk**: Low WR (35-50%) requires strong risk management and patience
**Build effort**: Very low (~150 lines). Just a new detector using existing indicators.

**FF threads**: [Dual Channel/Band System](https://www.forexfactory.com/thread/810605)

---

## Comparison Matrix

| | London Breakout | Quiet-Hours MR | EMA Pullback | ORB | Keltner |
|---|---|---|---|---|---|
| **Complements KZ Hunt** | Excellent (opposite regime) | Excellent (different hours) | Excellent (natural hedge) | Good (different phase) | Very good (vol regime) |
| **Build effort** | Very low | Medium | Low | Low | Very low |
| **New indicators needed** | None | BB, RSI | None | None | None |
| **New timeframe needed** | No | M15 | No (uses H4) | M5 | H4 |
| **Overlap risk with KZ Hunt** | Same session, different logic | None | Same pairs, different direction | Same session | Different timeframe |
| **Verified results** | Moderate | Good (commercial EAs) | Moderate | Limited | Limited |
| **Trades per week** | 5 (1/day) | 10-20 | 2-5 | 5-10 | 2-5 |

## What to Avoid

- **Grid/Martingale systems** (Waka Waka etc.) — incompatible with circuit breaker framework
- **ML black boxes** (Alphabet EA) — can't validate or adapt
- **Strategies without SL** (Connors RSI-2) — incompatible with risk management
- **Anything that also fades session extremes** (Camarilla pivots) — correlated drawdowns with KZ Hunt

## Recommended Build Order

1. **EMA 200 Pullback** — lowest effort, highest synergy, uses existing infrastructure
2. **London Breakout** — very simple, best regime diversification
3. **Keltner Breakout** — trivial to build, good volatility regime complement
4. **Quiet-Hours MR** — fills time gap but needs spread validation first
5. **ORB** — after M5 infrastructure is proven with Asian Gravity

---

*Research compiled from 3 parallel agents scanning ForexFactory forums, MQL5 marketplace, and forex strategy databases. ~150 threads and articles reviewed.*
