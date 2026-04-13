# Francis Hunt Metals Strategy Research — Synthesis Report

**Date:** 2026-04-13
**Sources:** 5 parallel research agents covering: core strategies, Gold/Silver analysis, wedge automation, recent YouTube content, metals trading characteristics

---

## Executive Summary

Francis Hunt's current focus is heavily on precious metals, particularly Gold ($5,200+ near-term target) and Silver ($90+ near-term, $330 measured move from cup-and-handle). His Silver thesis centers on a **falling wedge / cup-and-handle breakout** pattern on the monthly chart.

Three automatable strategies emerge from this research, ranked by viability:

| Strategy | Instrument | Viability | Effort | Expected Edge |
|----------|-----------|-----------|--------|---------------|
| **Gold KZ_HUNT** (gold-specific kill zones) | XAUUSD | HIGH | LOW | Reuses existing engine, different session times |
| **Wedge Detector** | XAUUSD, XAGUSD, any | MEDIUM | MEDIUM | New pattern type, ~500 lines, D1/W1 timeframe |
| **Silver position trading** | XAGUSD | LOW | HIGH | Spread kills intraday edge, needs different approach |

---

## 1. Hunt's Current Gold & Silver Thesis

### Gold
- **Near-term target**: $5,200+ (Feb 2026 livestream)
- **Medium-term**: Multiple HVF measured moves on weekly/monthly charts
- **Long-term**: $107,000 (extreme fiat-collapse scenario, multi-decade cup-and-handle)
- **Key level identified**: $3,769 (hit and paused)
- **Macro view**: Fiat system in terminal collapse, central banks accumulating, "hyperstagflation"
- **Dips are buying opportunities**: Credit contagion causes liquidation selloffs that reverse

### Silver
- **Pattern**: Falling wedge into cup-and-handle breakout on monthly chart
- **Silver broke $44** — Hunt called this the crucial level
- **Near-term**: $90+ (Feb 2026)
- **Measured move target**: $330/oz from cup-and-handle
- **Gold:Silver ratio thesis**: Currently ~100:1, Hunt predicts collapse to 9:1
- **If gold = $5,200 and ratio = 9:1**: Silver = $577

### Recent YouTube Content (2025-2026)
- Channel has shifted from pure technicals to macro + technicals combined
- Most-viewed recent: "Debt Market Dying - Gold's Crash" (84K views, Mar 2026)
- "The Key Event Horizon for Gold ($5,200+), Silver ($90+) & Platinum Is HERE" (26K, Feb 2026)
- "Rainmaker Trades" — new branding for high-conviction macro plays, not a new pattern type
- Platinum expansion: $30,000/oz thesis (new territory for him)
- Educational: Free "Trade Smart Video Series" at keap.page, paid "Sniper Circle" community

---

## 2. Strategy A: Gold KZ_HUNT (Highest Priority)

### Why This Is Most Viable
- **Already have the engine** — KZ_HUNT is live and validated on forex
- **Gold has institutional session structure** — the London Fix and COMEX create predictable reversal points
- **Previous backtest problem identified**: XAUUSD produced only +9 pips over 1 year with FOREX kill zones. Gold's key liquidity events happen at different times.

### Gold-Specific Kill Zones (UTC)

| Kill Zone | UTC Hours | Rationale |
|-----------|-----------|-----------|
| **London Gold Open** | 07:00-10:30 | European dealers enter, builds to AM Fix at 10:30 |
| **COMEX + PM Fix** | 13:00-16:00 | COMEX open (13:20) through PM Fix (15:00) — highest gold volume |
| **Asian Demand** | 01:00-04:00 | Chinese market open, physical buying window |

### The London Fix Effect (Key Edge)
The LBMA Gold Price is set twice daily:
- **AM Fix (10:30 UTC)**: Gold tends to RISE into the fix, then reverse
- **PM Fix (15:00 UTC)**: Gold tends to DROP after the fix (well-documented anomaly, Caminschi & Heaney 2014)
- Both fixes create **session extremes that get faded** — this is precisely the KZ_HUNT pattern

### Implementation Plan
1. Add a `KILL_ZONES_BY_SYMBOL` config mapping that overrides default forex KZ times for XAUUSD
2. Add XAUUSD to INSTRUMENTS
3. Backtest with gold-specific KZ times vs forex KZ times — quantify the improvement
4. Optional: DXY direction filter (if EURUSD > EMA200, bias gold LONG)

### Practical Considerations
- **Spread**: IC Markets Raw: $0.10-0.30 (10-30 "pips" at 0.01 pip value). Wider than forex but manageable relative to gold's range.
- **Margin**: 1:200 leverage on gold (vs 1:500 forex). A 0.5 lot XAUUSD position consumes ~$500-1000 margin. Monitor MAX_MARGIN_USAGE_PCT.
- **Trading hours**: Daily 1-2hr break around NY close (23:00-01:00 UTC varies). Health check must tolerate this.
- **Pip value**: Already in config (XAUUSD: 0.01)
- **Volatility**: H1 ATR typically $5-15 vs forex 8-15 pips. ATR-based stops scale correctly.
- **Position sizing**: Risk manager already handles non-USD pairs via `_get_quote_to_account_rate()`. Gold is quoted in USD, so conversion is trivial.

### Estimated Effort
LOW — ~50 lines of config changes + symbol-specific KZ time routing. No new pattern detector needed.

---

## 3. Strategy B: Wedge Pattern Detector

### What It Is
A new pattern type that detects converging trendline formations (rising wedges, falling wedges). This is Hunt's primary tool for metals at higher timeframes (D1/W1).

### Key Distinction from HVF
- **HVF** = symmetrical convergence (both trendlines converge from OPPOSITE sides)
- **Wedge** = both trendlines slope the SAME direction (both up = rising wedge / bearish, both down = falling wedge / bullish)
- Hunt treats both as "compression → measured move" patterns but wedges have directional bias

### Algorithmic Detection Method (from research)
1. **Identify swing points** using existing zigzag infrastructure
2. **Fit trendlines** via linear regression on swing highs and swing lows separately
3. **Classify**:
   - Both slopes positive + converging = Rising Wedge (bearish)
   - Both slopes negative + converging = Falling Wedge (bullish)
   - Opposite slopes + converging = Symmetrical Triangle / HVF territory
4. **Quality filters**: R-squared > 0.85 on both trendlines, min 3 touches each side, volume declining
5. **Breakout confirmation**: Close beyond trendline + volume spike + retest ("Stage 2: Second Chance")

### Target Calculation (Hunt's Method)
- **Widest point** of the wedge = measured move distance
- **Projection anchor** = midpoint of the breakout zone (Hunt's modification of standard TA which projects from the breakout point)
- **T1** = 50% of measured move (close 60%)
- **T2** = 100% of measured move (full target)
- **Bulkowski stats**: 50% projection hits 72-78% of the time, full projection only 46-55%

### Multi-Timeframe Challenge
Hunt's Silver wedge is on the MONTHLY chart. Automating this on H1 is problematic:
- A monthly wedge takes weeks/months to form
- H1 execution within a weekly wedge is really just trend-following during the breakout phase
- **Practical approach**: Detect wedges on D1, use them as a directional bias filter for H1 KZ_HUNT entries

### Scoring Framework (fits existing architecture)
| Component | Weight | Description |
|-----------|--------|-------------|
| Trendline R-squared | 0-20 | Quality of line fit |
| Touch count | 0-15 | More touches = stronger |
| Convergence rate | 0-15 | How much range narrows |
| Volume contraction | 0-15 | Declining volume during formation |
| RSI divergence | 0-15 | Classic wedge confirmation |
| Duration | 0-10 | Not too short, not too stale |
| EMA200 alignment | 0-10 | Breakout direction matches trend |

### Estimated Effort
MEDIUM — ~500 lines new code (detector + scorer), reuses existing infrastructure (zigzag, scoring pipeline, risk management). Full implementation spec in `docs/research/wedge_pattern_detection.md`.

---

## 4. Strategy C: Silver Position Trading

### Why Silver Is Hard for Intraday
- **Spread**: IC Markets XAGUSD spread is $0.02-0.05, which is 3-8% of daily range
- **For comparison**: Forex spreads are 0.5-2% of daily range, and that's already eroding your live edge
- **With KZ_HUNT's current live PF of 0.39 on forex**: adding an instrument with 3-5x worse spread economics would be destructive

### What Could Work Instead
Silver's edge is in **position trading** (days to weeks), not intraday:
- Hunt's cup-and-handle and wedge targets are monthly-chart patterns
- The spread cost is amortized over a multi-day hold
- Entry at wedge breakout, hold for measured move target
- This is fundamentally different from KZ_HUNT's session-reversal approach

### Implementation Challenge
The current bot architecture is designed for intraday H1 trading with 30-second monitoring. Position trading needs:
- Different timeframe (D1 or W1 for detection)
- Multi-day holds (current trailing stop logic would chop out)
- Different risk management (smaller position, wider stops, longer time horizon)
- Swap cost consideration (holding silver overnight has financing costs)

### Estimated Effort
HIGH — would need a separate position-trading module with different lifecycle management. Not recommended as first metals expansion.

---

## 5. Gold vs Silver: Which First?

**Gold, without question.**

| Factor | Gold (XAUUSD) | Silver (XAGUSD) |
|--------|---------------|-----------------|
| Spread impact | 0.5-1.5% of range | 3-8% of range |
| KZ_HUNT compatibility | HIGH (institutional sessions) | LOW (spread kills edge) |
| Existing infrastructure | Already in PIP_VALUES | Not in config |
| Backtest data | Previous run showed +9p (wrong KZs) | Never tested |
| Diversification | r = -0.46 vs existing portfolio | Unknown but likely similar |
| Hunt's methodology fit | KZ_HUNT + Fix-based reversals | Wedge/position only |
| Implementation effort | ~50 lines config | New trading paradigm |

---

## 6. DXY Correlation Filter (Optional Enhancement)

Gold has ~-0.80 correlation with USD. A simple filter:
- If EURUSD > EMA200 (USD weakening): boost gold LONG scores / penalize SHORT
- If EURUSD < EMA200 (USD strengthening): boost gold SHORT scores / penalize LONG

Could be implemented as a ±10 score modifier in the KZ_HUNT scorer. EURUSD data is already being fetched.

---

## 7. Hunt's Other Patterns — Assessment for Automation

| Pattern | Status | Metals Viability |
|---------|--------|-----------------|
| **HVF** | Coded, DISABLED (PF=0.06 live) | Very rare on H1. Better on D1/W1 for metals. |
| **Viper** | Coded, DISABLED (net negative) | Untested on metals. Continuation pattern — could work on gold trends. |
| **KZ_HUNT** | LIVE, validated | Best candidate for gold with custom KZs |
| **London Sweep** | Coded, net negative | Not applicable to metals (different session structure) |
| **Wedge** | Not coded | New build required. D1/W1 timeframe. Best for silver position trading |
| **Cup & Handle** | Not coded | Hunt's primary silver pattern. Very long timeframe (monthly). Not suitable for automated intraday. |
| **Pyramiding** | Not coded | Hunt teaches adding to winners. Could enhance any pattern but adds complexity. Behind paywall. |

---

## 8. Recommended Roadmap

### Phase 1: Gold KZ_HUNT (This Week)
1. Add `KILL_ZONES_BY_SYMBOL` config for XAUUSD-specific session times
2. Add XAUUSD to INSTRUMENTS
3. Backtest on VPS with gold KZ times vs forex KZ times
4. If positive: deploy live alongside existing 8 pairs

### Phase 2: Wedge Detector (After 50+ Gold Trades)
1. Implement wedge detection using existing zigzag infrastructure
2. Start on D1 timeframe for XAUUSD and XAGUSD
3. Use as directional filter for H1 KZ_HUNT (not standalone)
4. Backtest on gold D1 — does wedge direction improve KZ_HUNT PF?

### Phase 3: Silver Evaluation (After Wedge Validation)
1. Check XAGUSD availability on IC Markets
2. Backtest gold-style KZ_HUNT on silver (likely negative due to spreads)
3. If wedge detector validated: consider silver position trading module
4. This is the highest-effort, lowest-certainty phase

---

## 9. CRITICAL: Contract Size Bug in Gold Backtesting

The metals research agent identified a **critical bug** in the position sizer for gold backtests.

Your `calculate_lot_size()` uses `contract_size=100_000` as default. For XAUUSD:
- 1 standard lot = **100 troy ounces** (not 100,000 units)
- At gold ~$3,000, 1 lot = $300,000 notional
- 1 "pip" ($0.01 move) on 1 lot = $1

With `contract_size=100_000` and `pip_size=0.01`:
```
pip_value_per_lot = 100_000 * 0.01 = 1000  (WRONG — should be 100 * 0.01 = 1.0)
```

This means the previous XAUUSD backtest (+9 pips) calculated lots 1000x too small. The equity curve and PnL numbers are wrong. **Fix this before any gold backtesting.**

Required config addition:
```python
CONTRACT_SIZES = {
    "XAUUSD": 100,      # 100 troy ounces
    "XAGUSD": 5000,     # 5000 troy ounces
    # All forex pairs default to 100_000
}
```

Also need per-symbol overrides for:
- `MAX_SPREAD_ABSOLUTE`: Gold needs 0.30 ($0.30 = 30 pips), not 0.00020
- `MIN_STOP_PIPS`: Gold needs ~300 ($3 minimum stop), not 8

---

## 10. Hunt's Metals vs Forex Philosophy

A critical insight from the research: **Hunt treats metals and forex as fundamentally different**:

| Aspect | Forex (KZ_HUNT) | Metals (Gold/Silver) |
|--------|-----------------|---------------------|
| **Timeframe** | H1, intraday | Weekly/Monthly/Quarterly |
| **Holding period** | Hours to days | Weeks to years |
| **Pattern** | KZ session reversal | HVF, wedge, cup-and-handle |
| **Risk management** | 1% equity per trade | Balance-sheet allocation |
| **Purpose** | Income generation (tactical) | Wealth preservation (strategic) |
| **Physical component** | None | Physical metal + vaulting |

This means automating his metals approach on H1 is NOT what Hunt himself does. His gold/silver trades are position trades on weekly+ charts. However, **applying KZ_HUNT session reversal to gold intraday** (with gold-specific kill zones) is our own adaptation — not Hunt's methodology. It may still work, but it's a different beast.

---

## 11. Hunt's Specific Price Targets (from YouTube 2025-2026)

| Metal | Target | Pattern/Basis | Source |
|-------|--------|---------------|--------|
| Gold | $3,769 | Measured move (hit Sept 2025) | Liberty and Finance, Sept 2025 |
| Gold | $5,200+ | "Event horizon" level | Market Sniper livestream, Feb 2026 |
| Gold | $107,000 | Full fiat collapse scenario | Reinvent Money, Oct 2025 |
| Silver | $44 | Key breakout level (hit Sept 2025) | Liberty and Finance, Sept 2025 |
| Silver | $64+ | Current price area | Elijah K. Johnson, Apr 2026 |
| Silver | $90+ | Medium-term | Market Sniper, Feb 2026 |
| Silver | $333 | Profit management zone | Triangle Investor, Dec 2025 |
| Silver | $330 | Cup-and-handle measured move | Multiple Sept-Dec 2025 |
| Platinum | $30,000 | HVF + underperformance reversion | GoldRepublic, Jul 2025 |
| Au:Ag Ratio | 9:1 | "At least single digits" | Metals and Miners, Nov 2025 |

---

## 12. Information Gaps

| Area | Confidence | Source |
|------|-----------|--------|
| Hunt's core HVF rules | HIGH | Public YouTube, Alvaro Rivero writeups, Scribd docs |
| Hunt's Silver wedge thesis | HIGH | Multiple recent videos, interviews confirm |
| Gold-specific KZ times | HIGH | LBMA Fix schedule, COMEX hours, well-documented |
| Wedge detection algorithms | HIGH | Academic papers, open-source implementations |
| Hunt's exact wedge entry rules | MEDIUM | General approach is public, specific rules behind paywall |
| Silver spread impact | HIGH | IC Markets data, community forums |
| XAGUSD availability on IC Markets | UNKNOWN | Need to verify on VPS |
| Hunt's "Rainmaker" trades | LOW | Appears to be branding, not a new pattern |
| Pyramiding specific rules | LOW | Behind Sniper Circle paywall |
| Contract sizes for metals on IC Markets | MEDIUM | Need to verify via mt5.symbol_info() |
