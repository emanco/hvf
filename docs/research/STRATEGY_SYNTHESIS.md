# Multi-Pattern Strategy Synthesis

**Date:** 2026-03-05
**Status:** Strategy design document — ready for implementation planning
**Inputs:** Viper research, KLOS research, Kill Zones research, backtest results (Runs 1-3), existing architecture review

---

## 0. The Elephant in the Room: Walk-Forward PF < 1

Before adding patterns, the synthesis must acknowledge the most important finding from backtesting:

| Metric | EURUSD (Full BT) | EURUSD (Walk-Forward OOS) | GBPUSD (Full BT) | GBPUSD (Walk-Forward OOS) |
|--------|-------------------|---------------------------|-------------------|---------------------------|
| PF | 3.16 | 0.48 | 0.76 | 0.12 |
| Win Rate | 91% | 57% | 83% | 33% |
| Trades | 11 | 7 | 6 | 3 |

The full backtest looks promising, but the walk-forward out-of-sample results show **PF < 1 on both instruments**. This could mean:

1. **Sample size is too small** — 7 and 3 OOS trades are not statistically meaningful. A PF swing from 3.16 to 0.48 on 7 trades can happen from a single bad trade.
2. **The system is overfit** — filter relaxation (convergence 1.5x to 1.2x, RRR 1.5 to 1.0, score 70 to 40) may have allowed lower-quality patterns.
3. **The training window is too short** — 6-month train / 2-month test with ~5 trades/year means most windows have 0-1 trades.
4. **HVF on H1 is genuinely marginal** — Hunt himself says the method "works best over the medium to long term" (4H/Daily).

**Strategy implication:** Adding more patterns is the correct response IF those patterns are independently validated. More patterns = more data points = more statistically meaningful walk-forward results. But we should not assume HVF is profitable until we have 50+ OOS trades. The multi-pattern approach is both a frequency solution AND a validation strategy.

---

## 1. Pattern Portfolio Map

### Market Condition Coverage

```
Market Phase:     Ranging/     Compression/    Breakout    Trending     Pullback/      Session
                  Quiet        Consolidation                            Continuation    Reversals
                  ─────────    ─────────────   ────────    ────────     ────────────    ─────────
HVF:                           ████████████    ████████
Viper:                                                     ████████    ████████████
Kill Zone Hunt:                                                                        ████████
London Sweep:                                                                          ████████

Time Coverage:    Asian        London Open     London      London-NY   NY Session      NY Close
                  23:00-06:00  07:00-09:55     10:00-14:25 14:30-16:55 17:00-19:25     19:30-22:55
                  ─────────    ─────────────   ────────    ────────     ────────────    ─────────
HVF:              (low qual)   ████████████    ████████    ████████    (low qual)
Viper:            (skip)       ████████████    ████████    ████████    (skip)
Kill Zone Hunt:                ████████████                ████████
London Sweep:     (builds range) ███████████
```

### Complementary Nature

| Pattern | When It Fires | What It Needs | Overlaps With |
|---------|---------------|---------------|---------------|
| **HVF** | After 3-wave compression completes | Convergence, volume contraction, ATR contraction | None — unique geometric pattern |
| **Viper** | During established trends, after pullback | Strong impulse, shallow retracement, trend confirmation | None — needs active trend (HVF needs compression) |
| **Kill Zone Hunt** | After KZ ends, at KZ extreme levels | Rejection candle at KZ high/low, session context | Slight overlap with London Sweep timing |
| **London Sweep** | London open sweeps Asian range | Asian range defined, London volume, rejection after sweep | Slight overlap with KZ Hunt timing |

**Gap analysis:** The main gap is **ranging/quiet markets** — none of these patterns trade ranges. This is correct: trading ranges on H1 with 1% risk is a losing proposition for these pairs. The gap is intentional.

---

## 2. Combined Frequency Estimate

### Conservative Estimates (Per Pair, Per Year)

| Pattern | EURUSD | GBPUSD | Confidence | Basis |
|---------|--------|--------|------------|-------|
| HVF (current) | 5-6 | 3-4 | HIGH | Actual backtest data |
| Viper | 8-12 | 6-10 | LOW | Extrapolated, not backtested |
| Kill Zone Hunt | 50-130 | 50-130 | LOW | 2-5/week estimate, heavily dependent on filters |
| London Sweep | 75-130 | 75-130 | LOW | 3-5/week estimate, heavily dependent on filters |

### Realistic Combined Projection

**Scenario A: Conservative (strict filters on all patterns)**

| Pattern | EURUSD/yr | GBPUSD/yr | Weekly Total |
|---------|-----------|-----------|--------------|
| HVF | 5 | 3 | 0.15 |
| Viper | 8 | 6 | 0.27 |
| KZ Hunt | 50 | 50 | 1.9 |
| London Sweep | 50 | 50 | 1.9 |
| **Total** | **113** | **109** | **~4.3/week** |

**Scenario B: Moderate filters (recommended starting point)**

| Pattern | EURUSD/yr | GBPUSD/yr | Weekly Total |
|---------|-----------|-----------|--------------|
| HVF | 5 | 3 | 0.15 |
| Viper | 10 | 8 | 0.35 |
| KZ Hunt | 80 | 80 | 3.1 |
| London Sweep | 100 | 100 | 3.8 |
| **Total** | **195** | **191** | **~7.4/week** |

**Important caveats:**
- KZ Hunt and London Sweep frequencies are speculative — they have NOT been backtested
- Many KZ Hunt and London Sweep signals will be filtered by risk management (max 2 concurrent trades, correlation check, circuit breaker)
- Effective trade count after all filters will be significantly lower than raw signal count
- HVF and Viper frequencies are much more reliable estimates
- The jump from ~0.3/week (HVF+Viper) to ~4-7/week (adding session patterns) is dramatic and needs validation

### Net Expected Trades After Risk Filters

With MAX_CONCURRENT_TRADES = 2 and correlation checks, the effective weekly throughput is capped. Assuming average trade duration of 12-24 hours:

- **Max theoretical throughput:** ~7-14 trades/week (2 concurrent, each lasting 12-24h)
- **After correlation filter:** ~5-10/week (EURUSD/GBPUSD same-direction blocks)
- **After circuit breaker:** ~4-8/week (daily loss limit will occasionally trigger)
- **Realistic estimate:** **3-6 trades per week** across all patterns and both pairs

---

## 3. Priority Implementation Order

### Ranking Criteria

Each pattern scored on three axes (1-5 scale):

| Pattern | Ease of Implementation | Frequency Gain | Rule Confidence | Total |
|---------|----------------------|----------------|-----------------|-------|
| Kill Zone Filter | 5 (modify scorer only) | 0 (no new trades) | 5 (well-documented) | 10 |
| KLOS Enhancement | 4 (modify existing) | 1 (marginal) | 3 (behind paywall) | 8 |
| SHORT HVF Fix | 4 (debug existing) | 3 (doubles HVF) | 4 (known gap) | 11 |
| Viper | 3 (new detector + indicators) | 2 (8-12/yr/pair) | 3 (medium confidence) | 8 |
| Kill Zone Hunt | 2 (new detector + KZ tracker) | 5 (50-130/yr/pair) | 4 (TradingView indicator) | 11 |
| London Sweep | 2 (new detector + session tracker) | 5 (50-130/yr/pair) | 4 (well-documented) | 11 |

### Recommended Order

**Phase 0: Foundation (prerequisite for everything)**
- Fix SHORT HVF detection gap (see Section 6)
- Add Kill Zone timing filter to existing HVF scorer
- Add RSI(14), MACD(12,26,9) to data_fetcher.py (needed by Viper and useful for others)
- Estimated effort: 1-2 days
- Independently testable: Yes (re-run backtest, check for SHORT patterns)

**Phase 1: Viper Pattern**
- New `detector/viper_detector.py`
- New `detector/viper_scorer.py`
- Add pattern_type field to database models
- Modify backtest_engine.py to route by pattern type
- Estimated effort: 3-5 days
- Independently testable: Yes (Viper-only backtest)
- Why first: Most aligned with Hunt methodology, clear rules, moderate frequency gain, validates the multi-pattern architecture

**Phase 2: Kill Zone Hunt**
- New `detector/killzone_tracker.py` (tracks KZ high/low formation)
- New `detector/killzone_hunt_detector.py` (rejection/breakout-pullback entry logic)
- New `detector/killzone_hunt_scorer.py`
- Estimated effort: 3-5 days
- Independently testable: Yes (KZ Hunt-only backtest)
- Why second: Biggest frequency gain, well-documented rules from TradingView indicator

**Phase 3: London Sweep**
- New `detector/london_sweep_detector.py` (Asian range tracker + sweep detection)
- New `detector/london_sweep_scorer.py`
- Estimated effort: 2-3 days
- Independently testable: Yes (London Sweep-only backtest)
- Why third: Shares KZ infrastructure, adds to session-based trading coverage

**Phase 4: KLOS Enhancement + Integration Refinement**
- Enhance HVF target placement using multi-TF key levels
- Cross-pattern priority system
- Combined portfolio backtest and walk-forward
- Estimated effort: 2-3 days

### What Each Phase Needs

| Phase | New Modules | Modified Modules | New Indicators | New Config Params |
|-------|-------------|------------------|----------------|-------------------|
| 0 | None | hvf_detector.py, pattern_scorer.py, data_fetcher.py | RSI(14), MACD(12,26,9) | Kill Zone times, RSI/MACD params |
| 1 | viper_detector.py, viper_scorer.py | backtest_engine.py, models.py, config.py | Fibonacci levels | Viper thresholds (see viper_pattern.md Section 12.3) |
| 2 | killzone_tracker.py, kz_hunt_detector.py, kz_hunt_scorer.py | backtest_engine.py, config.py | None new | KZ times, rejection rules, KZ Hunt thresholds |
| 3 | london_sweep_detector.py, london_sweep_scorer.py | backtest_engine.py, config.py | None new | Asian session times, sweep threshold, rejection rules |
| 4 | None | hvf_detector.py, pattern_scorer.py | Multi-TF S/R levels | KLOS level params |

---

## 4. Kill Zone Integration

### Role 1: Quality Filter for Existing HVF

**Current state:** `pattern_scorer.py:_get_session_score()` returns 0-10 based on broad session windows (London=6, NY=6, overlap=10, Asian=2).

**Proposed change:** Replace with Kill Zone-aware scoring.

```python
# config.py additions
KILL_ZONES_UTC = {
    'london':     {'start_hour': 7, 'start_min': 0,  'end_hour': 9,  'end_min': 55},
    'ny_morning': {'start_hour': 14, 'start_min': 30, 'end_hour': 16, 'end_min': 55},
    'ny_evening': {'start_hour': 19, 'start_min': 30, 'end_hour': 20, 'end_min': 55},
    'asian':      {'start_hour': 23, 'start_min': 0,  'end_hour': 3,  'end_min': 55},
}

# Scoring: breakout during Kill Zone = maximum confidence
# pattern_scorer.py replacement for _get_session_score()
def _get_session_score(timestamp: pd.Timestamp) -> float:
    hour, minute = timestamp.hour, timestamp.minute
    time_minutes = hour * 60 + minute

    # London Kill Zone: 07:00-09:55 UTC
    if 420 <= time_minutes <= 595:
        return 10.0

    # NY Morning Kill Zone: 14:30-16:55 UTC
    if 870 <= time_minutes <= 1015:
        return 8.0

    # London session (outside KZ): 10:00-14:25 UTC
    if 600 <= time_minutes <= 865:
        return 5.0

    # NY session (outside KZ): 17:00-19:25 UTC
    if 1020 <= time_minutes <= 1165:
        return 3.0

    # NY Evening Kill Zone: 19:30-20:55 UTC
    if 1170 <= time_minutes <= 1255:
        return 2.0

    # Asian session / off-hours
    return 0.0
```

This is a drop-in replacement that improves HVF quality scoring without any structural changes. Implement immediately.

### Role 2: Standalone Kill Zone Hunt Setup

**Strategy: Rejection at Kill Zone Extremes**

Rules (codeable):
1. Track the Kill Zone high and low as they form in real-time
2. When the Kill Zone period ends, lock the KZ high and KZ low as reference levels
3. Within the SAME session (not next day), monitor price approaching KZ extremes
4. Entry trigger: price touches KZ high/low AND forms a rejection candle
   - Rejection candle definition: candle with wick > 2x body length, body closes in rejection direction
   - For short at KZ high: bearish candle with upper wick > 2x body, close below open
   - For long at KZ low: bullish candle with lower wick > 2x body, close above open
5. Stop loss: beyond the KZ extreme + 0.5x ATR(14) buffer
6. Target 1: opposite KZ extreme (partial close 50%)
7. Target 2: 1.5x the KZ range from entry (full target)
8. Filter: only trade in direction aligned with EMA(200) trend on H1

**Strategy: Breakout-Pullback at Kill Zone Levels**

Rules (codeable):
1. After KZ ends, monitor for price breaking strongly through KZ high or low
   - "Strong break" = candle closes beyond KZ level with body > 0.5x ATR(14)
2. Wait for pullback to the broken level (now S/R)
   - Pullback must touch or come within 0.2x ATR of the broken level
3. Entry: next candle that confirms the pullback is holding
   - Bullish: candle closes above broken resistance after pullback
   - Bearish: candle closes below broken support after pullback
4. Stop loss: below pullback low (long) or above pullback high (short) + 0.3x ATR buffer
5. Targets: same as rejection strategy

### Kill Zone Session Expiry

Kill Zone Hunt signals expire when the session changes. A London KZ signal does not carry over to NY. This prevents stale levels from generating false signals.

---

## 5. KLOS Enhancement

KLOS (Key Levels of Significance) is NOT a separate pattern. It is a framework for identifying significant price levels within the HVF methodology.

### How to Apply KLOS to Improve Existing HVF

**Enhancement 1: Multi-Timeframe Key Level Confluence**

Before arming an HVF pattern, check if the breakout level aligns with a key level from a higher timeframe:

```python
# Pseudocode for KLOS confluence check
def check_klos_confluence(pattern, df_4h, df_daily):
    breakout_level = pattern.entry_price

    # Identify key levels from 4H: recent swing highs/lows (last 50 bars)
    klos_4h = get_swing_levels(df_4h, lookback=50)

    # Identify key levels from Daily: recent swing highs/lows (last 20 bars)
    klos_daily = get_swing_levels(df_daily, lookback=20)

    # Check if breakout level is near a KLOS (within 0.3x ATR)
    atr = df_4h['atr'].iloc[-1]
    confluence_zone = 0.3 * atr

    near_4h = any(abs(breakout_level - kl) < confluence_zone for kl in klos_4h)
    near_daily = any(abs(breakout_level - kl) < confluence_zone for kl in klos_daily)

    # Score boost: +5 for 4H confluence, +5 for Daily confluence
    bonus = 0
    if near_4h: bonus += 5
    if near_daily: bonus += 5
    return bonus
```

**Enhancement 2: KLOS-Based Target Refinement**

Instead of using raw Wave 1 range for targets, check if a KLOS sits between entry and target. If a strong resistance/support level exists before target_2, consider adjusting the target or at least flagging it as a reduced-probability target.

```python
# Pseudocode
def refine_target_with_klos(entry, target_2, direction, klos_levels):
    obstacles = []
    for kl in klos_levels:
        if direction == "LONG" and entry < kl < target_2:
            obstacles.append(kl)
        elif direction == "SHORT" and target_2 < kl < entry:
            obstacles.append(kl)

    if obstacles:
        # First obstacle becomes effective target_2
        # Original target_2 becomes "aspirational target"
        nearest_obstacle = min(obstacles) if direction == "LONG" else max(obstacles)
        return nearest_obstacle
    return target_2
```

**Enhancement 3: KLOS as Rejection Filter**

If a KLOS level sits very close to the entry (within 0.5x ATR on the wrong side), the breakout may fail because it hits a wall of institutional orders. Score penalty: -10 points.

### Implementation Note

KLOS enhancements are low priority because the full KLOS methodology is behind Hunt's paywall. The above implementations use standard swing high/low identification as a proxy. The real KLOS methodology may use different criteria. Implement as a best-effort approximation and refine if Hunt's course material becomes available.

---

## 6. SHORT Pattern Gap

### The Problem

Across 2+ years of H1 data (20,000 bars) on EURUSD and GBPUSD, **zero SHORT HVF patterns were detected**. All 17 trades were LONG. This means the bot is only trading in one direction, missing roughly half the opportunity set.

### Possible Causes

**Cause 1: Code Bug in SHORT Detection (MOST LIKELY)**

The HVF detector validates funnel shape with direction-specific rules. The SHORT validation path may have a logic error that prevents patterns from qualifying.

Evidence for this theory:
- 0 SHORT patterns in 2+ years is statistically improbable on EUR/GBP (these pairs trend both ways)
- The validation rules for SHORT are the mirror of LONG but may have been implemented incorrectly
- Bearish HVF requires: h3 > h1 AND h3 > h2 (ascending highs) AND l1 > l3 AND l2 > l3 (descending lows) — the logic is inverted from LONG and easy to get wrong

**Action:** Audit `hvf_detector.py` SHORT validation path. Specifically:
1. Check the bearish direction detection logic
2. Check the entry/stop/target calculations for SHORT patterns
3. Add explicit logging when a pattern is considered for SHORT but rejected, with the specific reason
4. Create synthetic SHORT pattern data and unit test the detection

**Cause 2: EMA200 Soft Gate Bias**

The EMA200 trend score gives 10 points if price is on the "correct" side of EMA200. For SHORT, this means price must be below EMA200. During strong uptrends (which EUR and GBP have experienced in parts of the dataset), SHORT patterns near EMA200 would get 0-5 points, bringing total scores below threshold.

Evidence: The score threshold was lowered to 40. With a 0 on EMA200 (10 points lost) and a 0 on session (10 points lost), a SHORT pattern would need 40/80 from remaining components — still achievable but harder.

**Action:** This is less likely to be the sole cause but compound with other issues.

**Cause 3: Zigzag Detection Bias**

The ATR-adaptive zigzag may be more sensitive to upward pivots than downward pivots, or the pivot detection may favor patterns that form in uptrends.

**Action:** Run zigzag on the dataset and count the ratio of high pivots to low pivots. Should be roughly 50/50.

**Cause 4: Market Regime**

EURUSD and GBPUSD may have been in a predominantly bullish regime during the test period, making SHORT compressions genuinely rarer.

**Action:** Check EMA200 slope over the dataset. If predominantly positive, SHORT HVFs would naturally be less common, but "zero" still seems too few.

### Recommended Investigation Order

1. **Add diagnostic logging** to hvf_detector.py for SHORT candidates that fail validation
2. **Run backtest with logging** and count how many SHORT candidates are found vs rejected (and why)
3. **Write unit tests** with known SHORT pattern data to verify the detection logic
4. **If code is correct**, run the detector on H4 timeframe where patterns are cleaner
5. **If still zero**, accept that HVF SHORT on H1 may be genuinely rare and rely on Viper and KZ Hunt for SHORT exposure

### Expected Impact of Fix

If the SHORT gap is a code bug, fixing it could add 3-8 trades/year on EURUSD and 2-5 on GBPUSD (roughly mirroring LONG counts). This would be the single highest-value fix per line of code changed.

---

## 7. Scoring & Priority System

### Cross-Pattern Scoring Architecture

Each pattern type has its own scorer with different components but the same 0-100 scale:

```
HVF Score (0-100):
  Tightness (20) + Volume (15) + ATR (15) + RRR (20) + EMA200 (10) + MTF (10) + Session (10)

Viper Score (0-100):
  Impulse Quality (20) + Retrace Depth (20) + Volume Profile (15) + RSI (15) + ADX (10) + EMA200 (10) + Session (10)

KZ Hunt Score (0-100):
  Rejection Strength (25) + KZ Range Quality (15) + Volume at Rejection (15) + EMA200 Trend (15) + Session Overlap (10) + RRR (10) + ATR Context (10)

London Sweep Score (0-100):
  Sweep Depth (20) + Rejection Candle (20) + Asian Range Quality (15) + Volume (15) + EMA200 Trend (10) + Time Precision (10) + RRR (10)
```

### When Multiple Patterns Signal Simultaneously

**Priority rules:**

1. **HVF always takes priority** over other patterns on the same instrument/direction. HVF is the core methodology with the best theoretical RRR. If an HVF is armed and about to trigger, no other pattern should take the trade slot.

2. **Higher score wins** when two patterns of different types signal on the SAME instrument. Example: Viper(72) on EURUSD BUY vs KZ Hunt(65) on EURUSD BUY — take the Viper.

3. **Different instruments are independent.** A Viper on EURUSD and a KZ Hunt on GBPUSD can both trigger, subject to correlation and concurrent trade limits.

4. **Same-direction correlation block still applies.** If a Viper BUY is open on EURUSD, a KZ Hunt BUY on GBPUSD is blocked (same direction, correlated pairs).

5. **Pattern-type diversification bonus.** When choosing between two equal-score signals, prefer the pattern type that does NOT already have an open trade. This prevents portfolio concentration in one pattern type.

### Implementation: Unified Signal Queue

```python
@dataclass
class TradeSignal:
    pattern_type: str      # "HVF", "VIPER", "KZ_HUNT", "LONDON_SWEEP"
    symbol: str
    direction: str         # "BUY" or "SELL"
    score: float
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    timestamp: pd.Timestamp
    metadata: dict         # Pattern-specific data

def prioritize_signals(signals: list[TradeSignal], open_trades: list) -> list[TradeSignal]:
    """Sort signals by priority, filter conflicts."""
    # 1. Remove signals conflicting with open trades (same symbol+direction)
    # 2. Sort by: pattern_type priority (HVF=1, Viper=2, KZ=3, LS=4), then score DESC
    # 3. Apply correlation filter
    # 4. Return top N that fit within MAX_CONCURRENT_TRADES
    pass
```

---

## 8. Risk Management Updates

### Max Concurrent Trades

**Current:** MAX_CONCURRENT_TRADES = 2 (appropriate for £500 capital with HVF only)

**With 4 pattern types:** Consider increasing to 3 when capital reaches £750+.

| Capital | Max Concurrent | Rationale |
|---------|---------------|-----------|
| £500 | 2 | 1% risk each = 2% total exposure. Sufficient for HVF + 1 other. |
| £750 | 3 | 1% risk each = 3% total exposure. Can run HVF + Viper + session pattern. |
| £1,000+ | 4 | 1% risk each = 4% total. Full pattern portfolio. |

### Correlation Between Pattern Types

| Pattern A | Pattern B | Correlation Risk | Action |
|-----------|-----------|-----------------|--------|
| HVF LONG EURUSD | Viper LONG EURUSD | HIGH (same instrument, same direction) | Block — would double position |
| HVF LONG EURUSD | KZ Hunt LONG GBPUSD | MEDIUM (different instrument, same direction, 80% correlated) | Block — existing correlation check handles this |
| HVF LONG EURUSD | KZ Hunt SHORT GBPUSD | LOW (opposite directions on correlated pair) | Allow — provides natural hedge |
| Viper LONG EURUSD | London Sweep SHORT EURUSD | CONFLICTING | Block — contradictory signals on same instrument |

**New rule needed:** No two trades on the same instrument, regardless of pattern type. The existing correlation check only blocks same-direction on correlated pairs. We also need:

```python
# Add to risk_manager.py _check_correlation():
# Block any trade on same instrument if already have an open trade
for trade in open_trades:
    if trade['symbol'] == symbol:
        return False, f"Already have open trade on {symbol}"
```

### Position Sizing Per Pattern Type

Different patterns have different typical RRRs and win rates. Consider pattern-specific risk:

| Pattern | Expected Win Rate | Expected RRR | Risk Per Trade |
|---------|-------------------|--------------|----------------|
| HVF | 60-70% | 2-4:1 | 1.0% (standard) |
| Viper | 55-65% | 1.5-2.5:1 | 0.75% (lower RRR, reduce risk) |
| KZ Hunt | 50-60% | 1.5-2:1 | 0.5% (unproven, start small) |
| London Sweep | 50-60% | 1.5-2:1 | 0.5% (unproven, start small) |

**Implementation:** Add `RISK_PCT_BY_PATTERN` to config.py. The risk_manager.py pre_trade_check should accept pattern_type and use the appropriate risk percentage.

```python
# config.py
RISK_PCT_BY_PATTERN = {
    "HVF": 1.0,
    "VIPER": 0.75,
    "KZ_HUNT": 0.5,
    "LONDON_SWEEP": 0.5,
}
```

### Circuit Breaker Updates

The current circuit breaker tracks daily/weekly/monthly loss caps as percentages. With more frequent trading, the circuit breaker will trigger more often, which is correct and protective.

**One addition needed:** Pattern-type circuit breaker. If a specific pattern type generates 3 consecutive losses, pause THAT pattern type for 48 hours while others continue. This prevents one faulty pattern from consuming the daily loss budget.

```python
# config.py
PATTERN_CONSECUTIVE_LOSS_LIMIT = 3
PATTERN_PAUSE_HOURS = 48
```

---

## 9. Infrastructure Reuse Assessment

### Code Reuse by Module

| Existing Module | HVF | Viper | KZ Hunt | London Sweep |
|----------------|-----|-------|---------|--------------|
| `data_fetcher.py` | AS-IS | MODIFY (add RSI, MACD) | AS-IS | AS-IS |
| `zigzag.py` | AS-IS | REUSE (swing detection) | NOT NEEDED | NOT NEEDED |
| `hvf_detector.py` | AS-IS | NOT REUSED | NOT REUSED | NOT REUSED |
| `pattern_scorer.py` | MODIFY (KZ filter) | NEW SCORER | NEW SCORER | NEW SCORER |
| `risk_manager.py` | MODIFY (pattern_type) | REUSE | REUSE | REUSE |
| `position_sizer.py` | AS-IS | REUSE | REUSE | REUSE |
| `circuit_breaker.py` | MODIFY (per-pattern) | REUSE | REUSE | REUSE |
| `order_manager.py` | AS-IS | REUSE | REUSE | REUSE |
| `trade_monitor.py` | AS-IS | REUSE | REUSE | REUSE |
| `mt5_connector.py` | AS-IS | AS-IS | AS-IS | AS-IS |
| `models.py` | MODIFY (pattern_type) | REUSE | REUSE | REUSE |
| `trade_logger.py` | AS-IS | REUSE | REUSE | REUSE |
| `telegram_bot.py` | AS-IS | REUSE | REUSE | REUSE |
| `backtest_engine.py` | MODIFY (multi-pattern) | REUSE | REUSE | REUSE |
| `main.py` | MODIFY (multi-detector) | REUSE | REUSE | REUSE |
| `config.py` | MODIFY (add params) | REUSE | REUSE | REUSE |
| `news_filter.py` | AS-IS | REUSE | REUSE | REUSE |
| `health_check.py` | AS-IS | AS-IS | AS-IS | AS-IS |
| `reconciliation.py` | AS-IS | AS-IS | AS-IS | AS-IS |

### Reuse Percentages

| Pattern | Reuse % | New Code Needed |
|---------|---------|-----------------|
| Viper | ~75% | viper_detector.py (~300 lines), viper_scorer.py (~150 lines), RSI/MACD in data_fetcher.py (~40 lines) |
| KZ Hunt | ~70% | killzone_tracker.py (~150 lines), kz_hunt_detector.py (~250 lines), kz_hunt_scorer.py (~120 lines) |
| London Sweep | ~75% | london_sweep_detector.py (~200 lines), london_sweep_scorer.py (~120 lines) |

### Key Architectural Changes Needed (One-Time)

1. **Abstract pattern interface:** All detectors should return a common `TradeSignal` dataclass (not just `HVFPattern`). The risk manager, order manager, and trade monitor should work with `TradeSignal` instead of `HVFPattern`.

2. **Pattern-type routing in main.py:** The scanner thread currently calls hvf_detector directly. It needs a dispatcher that runs all active detectors and merges their signals.

3. **Database schema update:** Add `pattern_type` column to patterns and trades tables. All existing records become "HVF".

4. **Backtest engine multi-pattern support:** The engine needs to run multiple detectors per bar and handle signal prioritization.

### Estimated Lines of Code

| Category | Lines |
|----------|-------|
| New detector modules | ~1,100 |
| New scorer modules | ~390 |
| Indicator additions | ~60 |
| Existing module modifications | ~200 |
| Config additions | ~80 |
| Tests | ~500 |
| **Total** | **~2,330** |

---

## 10. Realistic Return Projections

### Honest Assessment: We Don't Have Enough Data

The backtest has 17 trades over 2+ years. Walk-forward has 10 OOS trades. These sample sizes are too small for statistical confidence. Any return projection is unreliable.

### What the Data Actually Shows

**Full backtest (in-sample, likely optimistic):**
- EURUSD: +109.0 pips over 2+ years (11 trades)
- GBPUSD: -10.2 pips over 2+ years (6 trades)
- Net: +98.8 pips over 2+ years on 2 instruments

**Walk-forward (out-of-sample, small sample):**
- EURUSD: -62.0 pips OOS (7 trades)
- GBPUSD: -52.1 pips OOS (3 trades)
- Net: -114.1 pips OOS

### Conservative Projection for Multi-Pattern System

Assumptions (deliberately conservative):
- 3-5 trades/week effective (after all filters)
- 50% win rate (lower than any individual pattern estimate)
- Average winner: +15 pips (most trades close via trailing stop, not full target)
- Average loser: -25 pips (full stop loss)
- Risk per trade: 0.5-1.0% of equity

| Scenario | Trades/Week | Win Rate | Avg Win | Avg Loss | Weekly Expectancy (pips) | Monthly (pips) |
|----------|-------------|----------|---------|----------|--------------------------|----------------|
| Pessimistic | 3 | 45% | +12 | -30 | -10.3 | -44 |
| Conservative | 4 | 50% | +15 | -25 | -5.0 | -20 |
| Moderate | 4 | 55% | +18 | -22 | -0.4 | -2 |
| Optimistic | 5 | 58% | +20 | -20 | +16.8 | +67 |

**Key observation:** Even the "optimistic" scenario produces modest returns. The system is NOT a get-rich-quick setup. At £500 with 0.5-1.0% risk per trade, monthly P&L in GBP would be:

- Conservative: -£1 to -£4/month
- Moderate: roughly breakeven
- Optimistic: +£5 to +£15/month

### What Would Make This Profitable

The system becomes clearly profitable if:
1. Win rate exceeds 55% with average RRR of 1.5:1 or better
2. Trade frequency reaches 4+ per week (enough to overcome fixed costs like spread)
3. Trailing stop logic improves (currently most exits are small winners via trailing stop)

### Confidence Interval

With the data we have, the 95% confidence interval for the system's edge (per trade) ranges from approximately -15 pips to +10 pips. We genuinely do not know yet if the system is profitable. More data (more patterns, more trades, longer OOS period) is required to answer this question.

---

## 11. Implementation Roadmap

### Phase 0: Foundation & Fixes (Week 1)

**Goal:** Fix known issues, add infrastructure for multi-pattern support.

| Task | Deliverable | Test Criteria |
|------|-------------|---------------|
| Audit SHORT HVF detection | Diagnostic log showing SHORT candidates found/rejected | Run backtest with logging, count SHORT candidates |
| Fix SHORT HVF bug (if found) | Working SHORT detection | Backtest shows SHORT trades in dataset |
| Add Kill Zone filter to scorer | Updated `_get_session_score()` | Backtest re-run shows score distribution change |
| Add RSI(14) to data_fetcher.py | New `rsi` column in DataFrame | Unit test: known RSI values for synthetic data |
| Add MACD(12,26,9) to data_fetcher.py | New `macd`, `macd_signal`, `macd_hist` columns | Unit test: known MACD values for synthetic data |
| Create TradeSignal dataclass | Common interface for all patterns | Existing HVF tests still pass |
| Add pattern_type to DB models | Migration for patterns/trades tables | DB test: can store and query by pattern_type |

**Exit criteria:** Backtest re-run with KZ filter shows changed scores. SHORT investigation complete with findings documented.

### Phase 1: Viper Pattern (Weeks 2-3)

**Goal:** Viper detection and scoring, independently backtested.

| Task | Deliverable | Test Criteria |
|------|-------------|---------------|
| Implement impulse detection | Function identifying strong directional moves | Unit test: detects impulse in synthetic H1 data |
| Implement Fibonacci retracement analysis | Function measuring pullback depth | Unit test: correct Fib levels for known swing |
| Build viper_detector.py | Full detector returning TradeSignal | Integration test: finds Vipers in real EURUSD data |
| Build viper_scorer.py | 0-100 scorer with 7 components | Unit test: scoring edge cases |
| Integrate with backtest engine | Viper-only backtest runner | Backtest: Viper-only results on EURUSD 20K bars |
| Tune and validate | Walk-forward on Viper-only | Walk-forward PF > 1.0 on Viper trades |

**Exit criteria:** Viper-only backtest produces 10+ trades on EURUSD with documented PF/WR. Walk-forward results documented.

### Phase 2: Kill Zone Hunt (Weeks 3-4)

**Goal:** KZ Hunt detection, independently backtested.

| Task | Deliverable | Test Criteria |
|------|-------------|---------------|
| Build killzone_tracker.py | Module tracking KZ high/low formation per session | Unit test: correct KZ levels for known H1 data |
| Build rejection candle detector | Function identifying reversal candles at KZ extremes | Unit test: classifies known candle patterns |
| Build kz_hunt_detector.py | Full detector returning TradeSignal | Integration test: finds KZ Hunt setups in real data |
| Build kz_hunt_scorer.py | 0-100 scorer | Unit test: scoring edge cases |
| Integrate with backtest engine | KZ Hunt-only backtest runner | Backtest: KZ Hunt-only results on EURUSD 20K bars |
| Tune filters | Walk-forward on KZ Hunt-only | Walk-forward results documented |

**Exit criteria:** KZ Hunt-only backtest produces frequency estimate. Walk-forward results documented. If PF < 0.8 OOS, reassess before proceeding.

### Phase 3: London Sweep (Week 5)

**Goal:** London Sweep detection, independently backtested.

| Task | Deliverable | Test Criteria |
|------|-------------|---------------|
| Build Asian session range tracker | Calculates Asian high/low daily | Unit test: correct ranges for known data |
| Build sweep detection | Identifies when London price exceeds Asian range then reverses | Integration test: finds sweeps in real data |
| Build london_sweep_detector.py | Full detector returning TradeSignal | Backtest: London Sweep-only results |
| Build london_sweep_scorer.py | 0-100 scorer | Walk-forward results documented |

**Exit criteria:** London Sweep-only backtest documented. Combined with Phase 2 KZ Hunt for session-pattern portfolio assessment.

### Phase 4: Integration & Optimization (Week 6)

**Goal:** All patterns running together, portfolio-level validation.

| Task | Deliverable | Test Criteria |
|------|-------------|---------------|
| Multi-pattern backtest | Combined backtest with signal prioritization | All 4 pattern types trading in same simulation |
| KLOS enhancement | Multi-TF key level confluence scoring | A/B test: HVF with vs without KLOS bonus |
| Cross-pattern priority system | Signal queue with conflict resolution | No duplicate trades on same instrument |
| Risk management updates | Pattern-specific risk, per-pattern circuit breaker | Stress test: rapid consecutive signals handled correctly |
| Portfolio walk-forward | Full system walk-forward validation | Combined OOS PF documented with confidence interval |
| Production deployment prep | Updated main.py with multi-detector dispatcher | Successful 24h demo run on VPS |

**Exit criteria:** Combined walk-forward OOS results documented. Go/no-go decision for live deployment of each pattern type.

### Go/No-Go Decision Points

After each phase, evaluate:
- Is the pattern producing trades? (frequency check)
- Is the walk-forward PF > 0.8? (profitability check)
- Does adding this pattern improve the combined portfolio? (diversification check)

If a pattern fails these checks, shelve it and move to the next phase. Do not deploy unprofitable patterns to production just to increase frequency.

---

## 12. Open Questions & Risks

### High Priority — Must Resolve Before Live Trading

| Question | Impact | How to Resolve |
|----------|--------|----------------|
| Why zero SHORT HVF patterns in 2+ years? | Missing ~50% of HVF opportunities | Code audit of hvf_detector.py bearish path |
| Is HVF genuinely profitable OOS? | Core viability of the system | Need 30+ OOS trades (requires more data or more patterns) |
| Are Viper parameters correct? | Viper trades on wrong signals | Verify against Hunt's course material or backtest extensively |
| Do KZ Hunt rules translate to H1? | KZ Hunt designed for lower TF | Backtest will reveal; may need to use 15M data for entry timing |

### Medium Priority — Should Resolve During Implementation

| Question | Impact | How to Resolve |
|----------|--------|----------------|
| What is the optimal Kill Zone Hunt filter strictness? | Too loose = many losers; too strict = few trades | Parameter sweep in backtest |
| Should trailing stop logic be pattern-specific? | Current 1.5x ATR may not suit Viper or KZ Hunt | Test different trailing multipliers per pattern type |
| How does the system behave during high-impact news? | All patterns may produce false signals around NFP/FOMC | Extend news filter to cover all pattern types |
| Is the Asian session range reliable for London Sweep on all days? | Monday Asian range may differ from Friday | Check day-of-week effects in backtest |

### Low Priority — Can Resolve After Initial Deployment

| Question | Impact | How to Resolve |
|----------|--------|----------------|
| Does Hunt use MACD specifically for Viper? | Might be using different momentum indicator | Check course material |
| Can pyramiding improve results? | Could increase returns on winners | v2 feature after base profitability confirmed |
| Should we add more instruments? | More pairs = more signals | After proving profitability on EURUSD/GBPUSD |
| Is there a seasonal effect on pattern frequency? | Some months may produce more patterns | Need 3+ years of data |

### Known Risks

1. **Overfitting risk:** Every new pattern adds parameters. More parameters = more overfitting potential. Mitigate with strict walk-forward validation.

2. **Correlation risk:** All patterns trade the same 2 instruments. A black swan EUR or GBP event affects everything simultaneously. Mitigate with circuit breaker and position limits.

3. **Execution risk:** More frequent trading means more spread costs, more slippage, more MT5 connectivity issues. Mitigate with spread checks and health monitoring.

4. **Complexity risk:** Going from 1 pattern to 4 patterns significantly increases code complexity, debugging difficulty, and maintenance burden. Mitigate with clean interfaces, comprehensive tests, and independent pattern backtests.

5. **Strategy decay risk:** Market microstructure changes over time. Patterns that work in 2023-2025 may not work in 2026-2027. Mitigate with ongoing walk-forward monitoring and pattern-type circuit breakers.

6. **Knowledge gap risk:** Hunt's specific rules for Viper are behind a paywall. Our implementation is a best-effort approximation. The KZ Hunt and London Sweep are not Hunt-specific patterns. If the goal is specifically to trade Hunt's methodology, only HVF is truly validated as his approach.

---

## Appendix A: Config Additions Summary

All new config parameters needed across all phases:

```python
# ─── Kill Zone Timing (UTC) ──────────────────────────────────────────────
KILL_ZONES_UTC = {
    'london':     {'start_hour': 7,  'start_min': 0,  'end_hour': 9,  'end_min': 55},
    'ny_morning': {'start_hour': 14, 'start_min': 30, 'end_hour': 16, 'end_min': 55},
    'ny_evening': {'start_hour': 19, 'start_min': 30, 'end_hour': 20, 'end_min': 55},
    'asian':      {'start_hour': 23, 'start_min': 0,  'end_hour': 3,  'end_min': 55},
}

# ─── Viper Detection ────────────────────────────────────────────────────
VIPER_MIN_IMPULSE_ATR_MULT = 2.0
VIPER_MAX_RETRACE_FIB = 0.618
VIPER_IDEAL_RETRACE_FIB = 0.500
VIPER_MIN_RETRACE_FIB = 0.236
VIPER_RETRACE_MIN_BARS = 3
VIPER_RETRACE_MAX_BARS = 8
VIPER_IMPULSE_VOLUME_MULT = 1.5
VIPER_ADX_MIN = 25
VIPER_RSI_BULL_MIN = 40
VIPER_RSI_BEAR_MAX = 60
VIPER_MIN_RRR = 1.5
VIPER_TARGET_1_MULT = 1.0
VIPER_TARGET_2_MULT = 1.618
VIPER_SL_ATR_BUFFER = 0.3

# ─── Kill Zone Hunt ─────────────────────────────────────────────────────
KZ_HUNT_REJECTION_WICK_MULT = 2.0       # Wick must be > 2x body for rejection
KZ_HUNT_BREAKOUT_BODY_ATR = 0.5         # Breakout candle body > 0.5x ATR
KZ_HUNT_PULLBACK_ATR_TOLERANCE = 0.2    # Pullback must come within 0.2x ATR of level
KZ_HUNT_SL_ATR_BUFFER = 0.5             # SL beyond KZ extreme + buffer
KZ_HUNT_TARGET_2_KZ_RANGE_MULT = 1.5    # T2 = 1.5x KZ range from entry
KZ_HUNT_MIN_RRR = 1.5
KZ_HUNT_MIN_KZ_RANGE_ATR = 0.5          # KZ must have min range (filters dead sessions)

# ─── London Sweep ───────────────────────────────────────────────────────
LONDON_SWEEP_ASIAN_START_HOUR = 23       # Asian session start (UTC)
LONDON_SWEEP_ASIAN_END_HOUR = 6          # Asian session end (UTC)
LONDON_SWEEP_WINDOW_START_HOUR = 7       # London open (UTC)
LONDON_SWEEP_WINDOW_END_HOUR = 10        # Window to detect sweep (UTC)
LONDON_SWEEP_MIN_RANGE_ATR = 0.3         # Asian range must be > 0.3x ATR
LONDON_SWEEP_REJECTION_WICK_MULT = 1.5   # Rejection wick > 1.5x body
LONDON_SWEEP_SL_ATR_BUFFER = 0.3
LONDON_SWEEP_TARGET_1_MULT = 0.5         # T1 = opposite Asian extreme
LONDON_SWEEP_TARGET_2_MULT = 1.0         # T2 = Asian range projected from entry
LONDON_SWEEP_MIN_RRR = 1.5

# ─── Multi-Pattern Risk ─────────────────────────────────────────────────
RISK_PCT_BY_PATTERN = {
    "HVF": 1.0,
    "VIPER": 0.75,
    "KZ_HUNT": 0.5,
    "LONDON_SWEEP": 0.5,
}
PATTERN_CONSECUTIVE_LOSS_LIMIT = 3
PATTERN_PAUSE_HOURS = 48

# ─── RSI ────────────────────────────────────────────────────────────────
RSI_PERIOD = 14

# ─── MACD ───────────────────────────────────────────────────────────────
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
```

## Appendix B: New File Structure

```
hvf_trader/
    detector/
        zigzag.py                    # Existing — reused by HVF and Viper
        hvf_detector.py              # Existing — FIX SHORT detection
        pattern_scorer.py            # Existing — MODIFY KZ filter
        viper_detector.py            # NEW Phase 1
        viper_scorer.py              # NEW Phase 1
        killzone_tracker.py          # NEW Phase 2
        kz_hunt_detector.py          # NEW Phase 2
        kz_hunt_scorer.py            # NEW Phase 2
        london_sweep_detector.py     # NEW Phase 3
        london_sweep_scorer.py       # NEW Phase 3
        signal_prioritizer.py        # NEW Phase 4 — cross-pattern priority queue

    data/
        data_fetcher.py              # MODIFY — add RSI, MACD

    risk/
        risk_manager.py              # MODIFY — pattern_type routing
        circuit_breaker.py           # MODIFY — per-pattern tracking

    database/
        models.py                    # MODIFY — pattern_type column

    backtesting/
        backtest_engine.py           # MODIFY — multi-pattern support
```
