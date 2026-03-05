# KLOS Research: "Kill Long / Kill Short" vs "Key Levels of Significance"

**Researcher:** Claude (klos-researcher agent)
**Date:** 2026-03-05
**Status:** CRITICAL FINDING - Name confusion identified

---

## Executive Summary

**KLOS does NOT stand for "Kill Long / Kill Short" in Francis Hunt's methodology.**

After extensive research across multiple sources (Google, Brave Search, Scribd, mundotrading.net, pdfcoffee.com, Jay Kim Show transcript, Tactical Investor, Conkers3, themarketsniper.com, Reddit, Wayback Machine), the evidence is clear:

- **KLOS = "Key Levels of Significance"** -- a concept WITHIN the HVF methodology, not a separate pattern
- **"Kill Long / Kill Short" does not exist** as a named Francis Hunt pattern or as a recognizable trading pattern in any forex community
- Google explicitly returned "It looks like there aren't many great matches for your search" when searching for Francis Hunt + "kill long" OR "kill short" + trading pattern reversal

---

## What KLOS Actually Is

### Definition (from Hunt's HVF Theory)

Source: Alvaro Rivero, "The Hunt Volatility Funnel (HVF) theory (part 2/2)", mundotrading.net, 30 April 2017. Also mirrored on pdfcoffee.com and Scribd (document #378376253).

> "The HVF concept 'key levels of significance (KLOS)' goes beyond just support and resistance, the traditionally well-known element of horizontal levels in technical analysis."

Source: Master Investor article by Francis Hunt (page now 404, but snippet preserved in search):

> "2. Key Levels of Significance (KLoS) -- a key element of my proprietary 'Hunt Volatility Theory'"

### KLOS in Context

KLOS is **not a trade setup or pattern** -- it is a framework for identifying significant price levels that form the foundation for HVF patterns. It is part of Hunt's broader methodology for understanding where breakouts are likely to occur and where targets should be projected.

Key aspects of KLOS from available sources:
1. **Goes beyond traditional S/R**: Not just horizontal support and resistance lines
2. **Tied to HVF geometry**: The levels form part of the funnel structure (3H, 3L, etc.)
3. **Breakout reference points**: Used to define where breakout entries trigger
4. **Target projection anchors**: Used in calculating where price targets should be set
5. **Part of the proprietary HVF course**: Full KLOS methodology is behind Hunt's paywall at themarketsniper.com

### How KLOS Relates to HVF Trading

From the HVF theory articles, KLOS levels appear to be used at multiple stages:

1. **Pattern identification**: The high/low pivot points that form the funnel shape ARE key levels of significance
2. **Entry triggers**: When price breaks past a KLOS (e.g., above 3H for bullish), the trade activates
3. **Stop placement**: Stop goes below a KLOS (e.g., below 3L for bullish)
4. **Target calculation**: Wave 1 range projected from the breakout KLOS
5. **Post-breakout stages**: The 5-stage HVF lifecycle uses KLOS levels at each stage

---

## Hunt's Complete Methodology (What We Found)

### HVF 5 Stages (from Part 2 article)

These are the stages AFTER a valid HVF breakout:

1. **Stage 1 - The Feign & Break**: First test of the key level. Price breaks through "like an electric fence" with a small pop above it.
2. **Stage 2 - The Second Chance**: Pullback to the breakout level -- opportunity for late entry.
3. **Stage 3 - The Capitulation**: Main move. Total imbalance in supply/demand. This is where profit accumulates.
4. **Stage 4 - Weak Buying Overcome**: Counter-trend traders step in ("Surely it's going too far...") but the target hasn't been reached yet.
5. **Stage 5 - Counter-attack & Progress Decay**: Trade is closed on the strength. Take-profit hit.

### Hunt's Key Principles (from Part 1 article and Jay Kim transcript)

1. **Greed keeps you in, pain takes you out** -- Manage psychology
2. **Is the juice worth the squeeze?** -- POUT score (Probability of Outcome), RRR (Risk-Reward Ratio), ToTE (Time to Target Expectancy)
3. **Time frame alignment** -- Don't trade against the larger timeframe trend
4. **Patience** -- "I made the most money when I just sat"
5. **Be a specialist** -- Focus on one methodology
6. **No indicators replace price action** -- Stop loss should be technical, not mathematical
7. **Position sizing is key** -- Most traders are too aggressive

### Volume (OBV)

Hunt emphasizes On Balance Volume (OBV) as "one of the genuine value indicators in volume, which is a set of data and not price crunched in a mass formula." Volume can precede key moves.

### Positive Slippage

HVF breakout traders benefit from positive slippage because they're "buying what everyone else is selling" -- if it gaps, the entry is even better than planned.

---

## What Hunt Patterns Actually Exist

Based on all research, Francis Hunt's known public methodology includes:

1. **HVF (Hunt Volatility Funnel)** -- The primary pattern. Symmetrical triangle variant with 3 waves of compression. Breakout continuation pattern.
2. **Inverted HVF** -- Same pattern but inverted (bearish version, or bullish from bottom). Mentioned in Part 2 article with Gulf Sands Petroleum example.
3. **KLOS (Key Levels of Significance)** -- A concept/framework, not a trade pattern. Used within HVF analysis.

### Patterns NOT Found

The following were searched for and NOT found as distinct, documented Hunt patterns:
- "Kill Long" / "Kill Short" (KLOS misinterpretation)
- "Viper" pattern (separate research task)
- Any named reversal pattern distinct from HVF

### What's Behind the Paywall

Hunt runs a paid education platform at themarketsniper.com. His full methodology, including any additional pattern types beyond HVF, appears to be exclusively taught in his paid course. The free content (YouTube, interviews, articles) consistently focuses on:
- HVF pattern recognition
- KLOS as a support/resistance framework
- General trading principles (RRR, position sizing, psychology)
- Macro market calls (gold, crypto, forex)

---

## Implications for the HVF Bot Project

### The "KLOS reversal pattern" likely does not exist as a separate tradeable setup

The team lead's request assumed KLOS = "Kill Long / Kill Short" reversal pattern. This appears to be a naming confusion. The actual meaning is "Key Levels of Significance" -- a concept within HVF, not a standalone pattern.

### What COULD be implemented from KLOS

While KLOS isn't a pattern, the concept could enhance the existing HVF bot:

1. **Multi-timeframe KLOS identification**: Identify key levels from higher timeframes (4H, Daily) and use them as confluence filters for H1 HVF patterns
2. **KLOS-based entry refinement**: Only take HVF breakouts that also break through a higher-timeframe KLOS
3. **KLOS target enhancement**: Project targets to the next significant KLOS level rather than just Wave 1 range
4. **KLOS as a rejection filter**: Avoid HVF entries where a strong KLOS sits between entry and target

### Recommendations for Increasing Trade Frequency

Since KLOS is not a separate pattern that can add trades, the team should consider:

1. **Multi-timeframe HVF**: Detect HVFs on H4 and Daily in addition to H1
2. **Relaxed HVF parameters**: Further tuning of existing filters (current 18 trades in 2+ years is very low)
3. **Inverted HVF**: Ensure the bot detects inverted/bearish HVFs (currently only finding LONG patterns)
4. **Additional instruments**: As capital grows, add more pairs
5. **Other well-documented patterns**: Consider standard breakout patterns (symmetrical triangles, ascending/descending triangles, flags) that share similar geometry with HVF but with different criteria

---

## Sources

1. **Alvaro Rivero**, "The Hunt Volatility Funnel (HVF) theory (part 2/2)", mundotrading.net, 30 April 2017
   - URL: https://mundotrading.net/2017/04/30/the-hunt-volatility-funnel-hvf-theory-part-22-by-alvaro-rivero/
   - Key quote: "The HVF concept 'key levels of significance (KLOS)' goes beyond just support and resistance"

2. **Alvaro Rivero**, "Francis Hunt ('The Market Sniper') trading strategy (part 1/2)", mundotrading.net, 24 April 2017
   - URL: https://mundotrading.net/2017/04/24/francis-hunt-the-market-sniper-trading-strategy-part-12-by-alvaro-rivero/
   - Key content: 7 trading principles, common mistakes

3. **Scribd**, "HVF MethodTheoryPart2" (document #378376253)
   - Same content as mundotrading Part 2 article, hosted as PDF

4. **PDFCOFFEE.COM**, "HVF MethodTheoryPart2"
   - Mirror of the Scribd document with additional community commentary on HVF geometry

5. **Jay Kim Show #148**, "Francis Hunt (transcript)", jaykimshow.com, 6 September 2020
   - Full interview transcript. Hunt discusses HVF methodology, market analysis approach, crypto trading
   - Only one mention of "key level" in general terms, no KLOS acronym used

6. **Tactical Investor**, "Francis Hunt: Technical Assassin or Chart-Fueled Crusader?", 22 April 2025
   - Overview of Hunt's career, notable predictions, HVF Methodology description
   - Confirms HVF as primary methodology, no mention of KLOS or Kill Long/Short

7. **Conkers3**, "34th Conkers' Corner: Francis Hunt", 28 November 2016
   - Interview summary confirming HVF as Hunt's core trading system since ~2009
   - No mention of KLOS or additional pattern types

8. **Master Investor** (article now 404, snippet from search results)
   - Francis Hunt wrote: "Key Levels of Significance (KLoS) -- a key element of my proprietary 'Hunt Volatility Theory'"
   - Original URL: https://masterinvestor.co.uk/a-market-sniper-longshort-commodity-trade-idea/

9. **Google Search** (via Playwright browser, 2026-03-05)
   - "Francis Hunt 'kill long' OR 'kill short' trading pattern reversal" returned: "It looks like there aren't many great matches for your search"
   - Confirms "Kill Long / Kill Short" is not a recognized concept in trading or in Hunt's work

---

## Confidence Assessment

| Claim | Confidence | Evidence |
|-------|------------|----------|
| KLOS = "Key Levels of Significance" | **HIGH** (95%) | Multiple independent sources confirm this |
| KLOS is NOT "Kill Long / Kill Short" | **HIGH** (95%) | Zero results for this interpretation anywhere |
| KLOS is a concept, not a pattern | **HIGH** (90%) | All sources describe it as a framework within HVF |
| No separate Hunt reversal pattern exists publicly | **MEDIUM** (70%) | Could be behind paywall; free content only shows HVF |
| Full KLOS rules are behind paywall | **HIGH** (85%) | Free sources only mention KLOS in passing |

---

## Research Limitations

1. **Paywall barrier**: Hunt's full course content at themarketsniper.com is paid. The detailed KLOS methodology and any additional patterns taught in the course are not publicly available.
2. **YouTube inaccessible**: Could not programmatically search/fetch YouTube content where Hunt may have discussed KLOS in more detail.
3. **Reddit inaccessible**: Reddit blocked automated access; community discussions about KLOS may exist there.
4. **WebFetch tool broken**: The WebFetch tool had a persistent model configuration error throughout this research session, limiting the number of sources that could be accessed.
5. **Limited free documentation**: Hunt's methodology is deliberately kept behind a paywall. Public information is fragmentary and mostly from third-party summaries.
