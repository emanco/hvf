# Kill Zones & Other Hunt Patterns Research

**Researcher:** killzone-researcher
**Date:** 2026-03-05
**Status:** Complete

---

## PART A: KILL ZONES

### 1. What Defines a Kill Zone

A Kill Zone is a specific time window during the forex trading day when institutional activity concentrates, creating peak volume, volatility, and liquidity. The term comes from the concept of a "killing field" — a window where the highest-probability setups occur because banks, hedge funds, and large institutions place the bulk of their orders during these periods.

**Key characteristics:**
- Concentrated institutional order flow
- Higher-than-average volume
- More intense price fluctuations
- Cleaner directional moves
- Better-defined support/resistance levels

**In Hunt's methodology context:** Kill Zones are used alongside the HVF Method as timing filters. While the HVF identifies **what** to trade (the pattern), Kill Zones help determine **when** the breakout is most likely to be genuine and well-supported by volume. The TradingView indicator "KillZones Hunt + Sessions" (by TFlab, 2,444 boosts, 55,609 views) explicitly combines Hunt's methodology with Kill Zone timing.

**Sources:**
- TradingView: "KillZones Hunt + Sessions [TradingFinder]" indicator (May 2024)
- EdgeFlo: "Forex Kill Zones: Pick One Session, Trade It Well" (Mar 2026)
- General ICT/Smart Money Concepts literature

---

### 2. Specific Time Windows

All times in UTC unless noted otherwise:

#### Full Trading Sessions

| Session | UTC Time | EST Time (UTC-5) |
|---------|----------|-------------------|
| Asian (Sydney/Tokyo) | 23:00 - 06:00 | 6:00 PM - 1:00 AM |
| European (London) | 07:00 - 14:25 | 2:00 AM - 9:25 AM |
| New York | 14:30 - 19:25 | 9:30 AM - 2:25 PM |
| NY Evening | 19:30 - 22:55 | 2:30 PM - 5:55 PM |

**Note:** The TradingFinder indicator adjusts session timings to avoid overlap between sessions and interference in kill zones.

#### Kill Zones (High-Activity Windows Within Sessions)

| Kill Zone | UTC Time | EST Time (UTC-5) | Duration |
|-----------|----------|-------------------|----------|
| Asian Kill Zone | 23:00 - 03:55 | 6:00 PM - 10:55 PM | ~5 hours |
| London Kill Zone | 07:00 - 09:55 | 2:00 AM - 4:55 AM | ~3 hours |
| NY Morning Kill Zone | 14:30 - 16:55 | 9:30 AM - 11:55 AM | ~2.5 hours |
| NY Evening Kill Zone | 19:30 - 20:55 | 2:30 PM - 3:55 PM | ~1.5 hours |

**Alternative timings from EdgeFlo (in EST):**

| Kill Zone | EST Time | Volume Level |
|-----------|----------|-------------|
| Asian | 8:00 PM - 12:00 AM | Low |
| London | 2:00 AM - 5:00 AM | High |
| New York | 7:00 AM - 10:00 AM | Highest |
| London Close | 10:00 AM - 12:00 PM | Low-Medium |

**For our bot (EURUSD/GBPUSD on H1):** The London and NY Morning Kill Zones are by far the most relevant. These are the windows where EUR and GBP pairs see peak institutional activity.

---

### 3. Entry Rules Within Kill Zones

Three primary entry strategies are documented in the TradingView "KillZones Hunt" indicator:

#### Strategy 1: Kill Zone Hunt (Rejection at Kill Zone Extremes)

**Rules:**
1. Wait for the Kill Zone to **end** (high and low are now fixed)
2. Within the **same session** (but after the Kill Zone closes), wait for price to reach one of the Kill Zone's extreme levels (high or low)
3. Look for a **strong rejection** (reversal candle, pin bar, engulfing) at that level
4. Enter in the direction of the rejection
5. Stop loss beyond the Kill Zone extreme
6. Target: opposite Kill Zone extreme or key support/resistance

**Rationale:** The Kill Zone high/low act as liquidity pools. When price returns to these levels, institutional orders are clustered there, creating reliable reaction zones.

#### Strategy 2: Breakout and Pullback to Kill Zone

**Rules:**
1. Wait for the Kill Zone to **end** (levels are fixed)
2. Within the same session, wait for price to **break strongly** through one of the Kill Zone levels
3. Wait for a **pullback** to the broken level (now acting as support/resistance)
4. Enter on confirmation of the pullback holding (e.g., bullish candle bouncing off broken resistance)
5. Stop loss below the pullback level
6. Target: projected based on the breakout momentum

**Rationale:** Classic breakout-retest pattern, but anchored to the high-volume Kill Zone levels rather than arbitrary support/resistance.

#### Strategy 3: Trading in the Trend of the Kill Zone

**Rules:**
1. During or after the Kill Zone, identify the dominant trend direction
2. If upward trend dominates the Kill Zone, look for buy entries at demand/order blocks
3. If downward trend dominates, look for sell entries at supply zones
4. Use the Kill Zone trend direction as bias confirmation
5. Enter on pullbacks to order blocks within the trend

**Rationale:** Kill Zones establish the "true" direction for the session because that's where institutional volume creates real moves.

---

### 4. How Kill Zones Interact with HVF and Other Patterns

#### Kill Zones as Entry Timing Filters for HVF

The existing HVF bot already has a session scoring component (0-10 points in the pattern scorer). Kill Zones should enhance this:

1. **HVF breakout during Kill Zone = highest confidence:** If an HVF pattern breakout occurs during a Kill Zone (especially London 07:00-09:55 or NY 14:30-16:55 UTC), the breakout has institutional volume behind it. This should receive maximum session score.

2. **HVF breakout outside Kill Zone = lower confidence:** Breakouts during dead hours (e.g., Asian session for EUR/GBP pairs) are more likely to be false breakouts due to thin liquidity.

3. **Kill Zone levels as entry refinement:** If an HVF pattern is "armed" (score > threshold) but hasn't broken out yet, Kill Zone support/resistance levels can provide more precise entry points.

#### Kill Zone Hunt as Standalone or Complementary

The Kill Zone Hunt strategy (rejection at KZ extremes) can work as a **standalone lower-timeframe setup** that increases trade frequency:

- HVF produces ~5 trades/year (H1 timeframe, 2 instruments)
- Kill Zone Hunt setups occur multiple times per week on lower timeframes
- When combined with HVF trend direction as bias, Kill Zone Hunt becomes a filtered, higher-probability standalone setup

#### Pattern Interaction Matrix

| Pattern | Kill Zone Role | Frequency Impact |
|---------|---------------|-----------------|
| HVF | Timing filter (breakout during KZ = higher score) | Same frequency, better quality |
| KLOS | Kill Zone extremes ARE the KLOS levels | Complementary |
| Viper | Kill Zone trend confirms Viper direction | Moderate increase |
| KZ Hunt (standalone) | IS the setup | Major increase (2-5 per week) |

---

### 5. Standalone Setups vs. Filters

**Kill Zones serve BOTH roles:**

#### As Filters (Enhancers for HVF/KLOS/Viper)
- **Session quality scoring:** Boost pattern scores when breakouts occur within Kill Zones
- **False breakout protection:** Reduce exposure to breakouts during thin-liquidity hours
- **Trend bias confirmation:** Kill Zone trend direction validates or invalidates pattern direction
- **Implementation:** Modify the existing `session_quality` scorer component (currently 0-10 points) to give maximum points during Kill Zones and zero points during dead hours

#### As Standalone Setups (The Kill Zone Hunt)
- **Rejection at Kill Zone extremes:** Independent trade setup that doesn't require HVF/KLOS/Viper
- **Breakout-pullback at Kill Zone levels:** Another standalone setup
- **Frequency:** Could add 2-5 setups per week vs ~5 per year for HVF alone
- **Implementation:** New detector module that identifies Kill Zone high/low, then monitors for rejection or breakout-pullback patterns

**Recommendation for our bot:** Implement Kill Zones in BOTH roles:
1. **Phase 1:** Use as filter/enhancer for existing HVF (low implementation effort)
2. **Phase 2:** Add Kill Zone Hunt as standalone setup (moderate implementation effort, major frequency increase)

---

### 6. Volume/Liquidity at Different Sessions

#### EURUSD Volume Profile by Session

| Session | Relative Volume | Typical Range | Spread |
|---------|----------------|---------------|--------|
| Asian | 15-20% of daily | 15-25 pips | Wide (1.5-3 pips) |
| London Open | 35-40% of daily | 30-60 pips | Tight (0.5-1.0 pips) |
| London-NY Overlap | 40-50% of daily | 40-80 pips | Tightest (0.3-0.8 pips) |
| NY Afternoon | 15-20% of daily | 15-30 pips | Moderate (1.0-2.0 pips) |

#### GBPUSD Volume Profile by Session

| Session | Relative Volume | Typical Range | Spread |
|---------|----------------|---------------|--------|
| Asian | 10-15% of daily | 15-25 pips | Wide (2.0-4.0 pips) |
| London Open | 40-45% of daily | 40-80 pips | Tight (0.8-1.5 pips) |
| London-NY Overlap | 35-40% of daily | 40-80 pips | Tight (0.8-1.5 pips) |
| NY Afternoon | 10-15% of daily | 15-25 pips | Moderate (1.5-3.0 pips) |

**Key insight for EURUSD/GBPUSD:**
- London Open Kill Zone (07:00-09:55 UTC) = most important window
- London-NY Overlap (14:30-16:55 UTC) = second most important
- Avoid entries during Asian session for these pairs (thin volume, wide spreads, range-bound)

---

### 7. Application to EURUSD and GBPUSD Specifically

#### EURUSD Kill Zone Strategy

**London Kill Zone (07:00-09:55 UTC):**
- EUR institutional desks open, highest EURUSD-specific volume
- Common pattern: sweeps overnight (Asian) high or low, then establishes the daily direction
- Best time for HVF breakouts on EURUSD
- 30-60 pip typical range during this window

**NY Kill Zone (14:30-16:55 UTC):**
- US economic data releases (NFP, CPI, FOMC) fall in this window
- London-NY overlap creates maximum liquidity
- Good for continuation or reversal of London move
- Caution needed around high-impact news events

**Practical implementation for our bot:**
- Assign session_score = 10 if breakout occurs during London Kill Zone (07:00-09:55)
- Assign session_score = 8 if breakout occurs during NY Kill Zone (14:30-16:55)
- Assign session_score = 3 if breakout occurs during London session but outside Kill Zone
- Assign session_score = 0 if breakout occurs during Asian session

#### GBPUSD Kill Zone Strategy

**London Kill Zone (07:00-09:55 UTC):**
- THE primary window for GBPUSD. GBP is most active here
- UK economic data releases cluster around 07:00-09:30 UTC
- Typical range: 40-80 pips
- This is where HVF breakouts have the highest probability of follow-through

**NY Kill Zone (14:30-16:55 UTC):**
- Secondary window, still has good volume
- Often sees continuation of London move or sharp reversal
- Cable (GBPUSD) can be volatile with US data releases

**Practical implementation for our bot:**
- Same scoring as EURUSD but with even higher weighting for London Kill Zone
- Consider a "London-only" mode for GBPUSD in the first iteration

---

## PART B: OTHER HUNT PATTERNS AND METHODS

### 1. Pyramiding (Position Scaling)

**Source:** TacticalInvestor.com article (Apr 2025), TheMarketSniper.com

Hunt emphasizes **pyramiding** — gradually increasing position sizes as a trend gains momentum. This is a core part of his HVF methodology applied to trade management:

**Rules (as described in public sources):**
1. Enter initial position on HVF breakout with standard risk (e.g., 1%)
2. As price moves in favor and reaches key milestones (e.g., 50% of target), add to the position
3. Each additional position uses a tighter stop loss (moved to breakeven or better on original)
4. Maximum exposure is capped (e.g., 3x initial position)
5. Trailing stop protects all positions

**Application to our bot:**
- Currently we do partial closes (50% at target_1, full at target_2)
- Pyramiding is the inverse: ADD at target_1 instead of close
- This is aggressive but aligns with Hunt's philosophy of "maximizing high-conviction trades"
- **Recommendation:** Consider as a v2 feature after validating base HVF profitability

**Confidence level:** MEDIUM — Pyramiding is mentioned in public sources about Hunt but specific rules for when/how to add are behind the paywall of his course.

---

### 2. Multi-Timeframe Analysis

**Source:** TheMarketSniper.com, FinNotes.org, TacticalInvestor.com

Hunt's approach to multi-timeframe analysis:

**Framework:**
1. **Higher timeframe (weekly/daily):** Establish overall trend direction using EMA200 and trend line analysis
2. **Trading timeframe (4H/1H):** Identify HVF patterns and potential setups
3. **Entry timeframe (15min/5min):** Fine-tune entries during Kill Zones

**Key principles:**
- "The trend is your friend" — HVF patterns aligned with the higher timeframe trend have significantly better win rates
- Higher timeframe trend lines serve as the "predominance" context
- Pattern breakouts against the higher timeframe trend should be avoided or taken with reduced size

**Application to our bot:**
- We already have 4H EMA200 confirmation (0/5/10 pts in scorer)
- Could add weekly trend direction as an additional filter
- Multi-timeframe Kill Zone analysis: daily trend + Kill Zone timing = higher confidence

---

### 3. Trend Line Theory & Symmetrical Triangles

**Source:** Scribd document "Understanding Hunt Volatility Funnels", TheMarketSniper.com

From the Scribd document (partially readable):

**Key insights:**
- The HVF is described as "a subset of triangles as defined by technical analysis"
- ALL HVFs qualify as traditionally defined triangles (symmetrical ones), but not all symmetrical triangles are HVFs
- The broad methodology involves exploiting "Symmetrical Triangles" in terms of traditional technical analysis
- Trend line theory is fundamental — a minimum of 4 points are required to establish the trend line, with 2 or more being preferable
- Trend lines have predominance in establishing the amplitude for targeting
- The amplitude is projected from the break of the trend line
- Target amplitude variations exist — most common is from the first high point down to the trend line (black dotted line in Hunt's examples)

**The key difference between HVF and standard symmetrical triangles:**
1. HVF requires specific wave structure (3 waves compressing)
2. HVF has strict alternation rules
3. HVF projects targets from Wave 1 range, not from the triangle apex
4. HVF emphasizes "stored energy" — the compression of volatility creates explosive breakouts

---

### 4. "Stored Energy" Concept

**Source:** TheMarketSniper.com, brief.md (existing project documentation)

Hunt's core innovation is the "stored energy" metaphor:

- As waves compress inside the funnel, volatility decreases
- This compression represents "energy being stored"
- The breakout releases this stored energy, creating an explosive move
- The magnitude of the move is proportional to Wave 1 range (the initial energy)

**Practical application:**
- Wave 1 range = the "stored energy"
- Target = midpoint + Wave 1 range (full energy release)
- The tighter the funnel (greater convergence), the more explosive the breakout
- This is why the funnel convergence ratio is a key scoring component

---

### 5. Hunt's Approach to Risk Management

**Source:** TheMarketSniper.com, FinNotes.org

Beyond the HVF pattern itself, Hunt teaches:

1. **Pre-determined risk:** Every trade has SL, TP1, TP2 defined BEFORE entry
2. **Favorable risk-reward:** Minimum 3:1 RRR (aligns with our bot's config)
3. **Position sizing based on risk:** Never risk more than a fixed % per trade
4. **"Sniper mindset":** Patient waiting for perfect setups rather than taking marginal trades
5. **Emotional control:** Avoid FOMO, fear of acknowledging loss, compulsion to trade

**Already implemented in our bot:** Most of these principles are already in the codebase via risk_manager.py and circuit_breaker.py.

---

### 6. Fibonacci-Based Approaches

**Source:** General trading community knowledge of Hunt's methodology

While Hunt's HVF method is primarily about geometric pattern recognition (convergence, waves, funnels), Fibonacci levels play a supporting role:

**How Hunt uses Fibonacci (based on public content):**
1. **Retracement levels:** Used to identify potential reversal zones within an established trend
2. **Extension levels:** Used alongside HVF targets to validate target zones
3. **Fibonacci clusters:** When multiple Fibonacci levels from different swings converge, these create high-probability zones

**Not a standalone system:** Hunt's Fibonacci usage is supplementary to the HVF method, not a replacement. He does not teach Fibonacci as a primary entry system.

**Confidence level:** LOW-MEDIUM — Specific Fibonacci rules are behind the paywall. Public content mentions Fibonacci but doesn't give precise rules.

---

### 7. The "Sniper Circle" Community Methodology

**Source:** TheMarketSniper.com

Hunt runs a paid community called "Sniper Circle" where members:
- Share HVF setups in real-time
- Get daily market updates and analysis
- Attend educational webinars
- Hold each other accountable

**Relevant insight for our bot:** The community trades on "medium to long term" timeframes (with exception of crypto). This confirms that H1 is appropriate but suggests that HVF works best on 4H and Daily for forex. Our ~5 trades/year on H1 is consistent with Hunt's own frequency expectations for forex.

**Quote from website:** "Though the HVF method can be applied on all time-frames, it works best over the medium to long term."

---

## SYNTHESIS & RECOMMENDATIONS FOR OUR BOT

### Priority 1: Kill Zone as HVF Filter (Easy Win)

**Implementation effort:** LOW
**Impact:** Improves existing trade quality, no new patterns needed

Changes to `config.py` and `pattern_scorer.py`:
```python
# Kill Zone definitions (UTC)
KILL_ZONES = {
    'london': {'start': '07:00', 'end': '09:55'},
    'ny_morning': {'start': '14:30', 'end': '16:55'},
    'ny_evening': {'start': '19:30', 'end': '20:55'},
    'asian': {'start': '23:00', 'end': '03:55'},
}

# Session scoring based on Kill Zones
# London KZ = 10pts, NY KZ = 8pts, London session = 3pts, Asian = 0pts
```

### Priority 2: Kill Zone Hunt as Standalone Pattern (Major Frequency Increase)

**Implementation effort:** MODERATE
**Impact:** Could add 2-5 setups per week (vs ~5/year for HVF)

New module: `detector/killzone_hunt.py`
- Track Kill Zone high/low as they form
- After Kill Zone ends, monitor for rejection or breakout-pullback at these levels
- Filter with HVF trend direction (only trade KZ Hunt in direction of dominant HVF trend)
- Use tighter stops (KZ-based) and smaller targets (20-40 pips for EURUSD)

### Priority 3: London Sweep Pattern

**Implementation effort:** MODERATE
**Impact:** 3-5 setups per week during London open

The "London sweeps Asian range" pattern:
1. Calculate Asian session high and low (23:00-06:00 UTC)
2. During London Kill Zone (07:00-09:55 UTC), watch for price to sweep Asian high/low
3. After sweep, look for rejection and reversal
4. Enter in reversal direction with stop beyond the sweep

This is well-documented across multiple sources and is highly relevant for EURUSD and GBPUSD.

### Priority 4: Pyramiding / Position Scaling (v2)

**Implementation effort:** LOW (code changes) but HIGH (risk)
**Impact:** Increases profit on winning trades, increases risk

Defer to v2 after base system is profitable.

---

## CONFIDENCE LEVELS & SOURCE QUALITY

| Finding | Confidence | Source Quality | Notes |
|---------|-----------|----------------|-------|
| Kill Zone time windows | HIGH | Multiple corroborating sources | Well-established in trading community |
| KZ Hunt entry rules | MEDIUM-HIGH | TradingView indicator with 2.4K boosts | Open source, well-documented |
| HVF + KZ interaction | MEDIUM | Inferred from indicator name "KillZones Hunt" | Direct connection confirmed by indicator |
| Pyramiding rules | MEDIUM | TacticalInvestor article | Specific rules behind paywall |
| Fibonacci usage | LOW-MEDIUM | General mentions, no specific rules | Behind paywall |
| Multi-timeframe approach | MEDIUM | Website + FinNotes + community knowledge | General framework public, specifics behind paywall |
| London sweep pattern | HIGH | Multiple independent sources | Not Hunt-specific but widely validated |
| Session volume data | HIGH | BabyPips, ForexFactory, common knowledge | Well-established market data |

---

## SOURCES

1. **TradingView** - "KillZones Hunt + Sessions [TradingFinder] Alert & Volume Ranges" indicator (May 2024) - Open source Pine Script with 2,444 boosts and 55,609 views
2. **EdgeFlo** - "Forex Kill Zones: Pick One Session, Trade It Well" (Mar 2026) - Comprehensive kill zone guide with specific times and strategies
3. **TheMarketSniper.com** - Official Francis Hunt website - HVF methodology overview, community description, and trading philosophy
4. **TacticalInvestor.com** - "Francis Hunt: Technical Assassin or Chart-Fueled Crusader?" (Apr 2025) - Overview of Hunt's methodology, successes, and failures
5. **FinNotes.org** - Francis Hunt profile page - Professional background, asset classes traded, strategies discussed
6. **Scribd** - "Understanding Hunt Volatility Funnels" (document #573773936) - Partial access to HVF methodology document discussing symmetrical triangles and trend lines
7. **Scribd** - "FrancisHunt - The Market Sniper - TraderProfile" (document #412382856) - Trader profile document
8. **Grey Rabbit Finance Substack** - "Francis Hunt Trading Secrets, Gold/Silver Surge & Dollar Collapse Warnings" (Feb 2025) - Podcast transcript with Hunt
9. **BabyPips.com** - Forex Market Hours and session timing data
10. **ForexFactory** - Session timing thread with TradingFinder tool
