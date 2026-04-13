# Wedge Pattern Detection Research — Automated Implementation Guide

**Date:** 2026-04-13
**Status:** Research compilation for implementation planning
**Context:** Extending HVF Auto-Trader with wedge detection, informed by Francis Hunt's methodology and algorithmic best practices
**Confidence:** HIGH on geometric definitions and algorithmic methods; MEDIUM on Hunt-specific wedge nuances (much is behind paywall)

---

## 1. Wedge Pattern Definitions

### 1.1 What Is a Wedge?

A wedge is a chart pattern formed by two **converging trendlines** that both slope in the **same direction** (both up or both down). This distinguishes wedges from symmetrical triangles, where trendlines slope in opposite directions.

The defining characteristic: price compresses into an ever-narrowing range while maintaining directional momentum, until the pattern "breaks" — typically in the direction opposite to the wedge slope.

### 1.2 Rising Wedge (Bearish)

**Geometry:**
- Upper trendline: connects successively **higher highs**, slopes upward
- Lower trendline: connects successively **higher lows**, slopes upward
- The lower trendline rises more steeply than the upper trendline (the lines converge)
- Result: price makes new highs, but the gains diminish with each swing

```
Price
  |              /H3
  |            /  |
  |          / H2 |
  |        /  / | |
  |      / H1/ |/
  |    /  /  L3
  |  /  L2
  | / L1
  |/
  +──────────────────── Time

Both trendlines slope UP, but lower line is steeper → convergence
Breakout: DOWNWARD (bearish) in ~65-70% of cases
```

**Rules:**
- Minimum 2 touches on each trendline (3+ is higher confidence)
- Each successive high is higher than the previous (H1 < H2 < H3)
- Each successive low is higher than the previous (L1 < L2 < L3)
- The range between the trendlines narrows over time
- Volume typically **declines** as the pattern develops
- Breakout to the downside on increased volume confirms the pattern

**Measured Move Target:**
- Standard: Project the widest part of the wedge (H1-L1 distance at the start) downward from the breakout point
- Conservative: Project 61.8% of the wedge height
- Aggressive: Project 100% or even 127.2% of the wedge height

### 1.3 Falling Wedge (Bullish)

**Geometry:**
- Upper trendline: connects successively **lower highs**, slopes downward
- Lower trendline: connects successively **lower lows**, slopes downward
- The upper trendline falls more steeply than the lower trendline (the lines converge)
- Result: price makes new lows, but the losses diminish with each swing

```
Price
  |\
  | \ H1
  |  \  \
  |   \ H2\
  |    \  \ \
  |     \ H3 \
  |      \  \  |
  |       L1 \ |
  |         L2\|
  |           L3
  +──────────────────── Time

Both trendlines slope DOWN, but upper line is steeper → convergence
Breakout: UPWARD (bullish) in ~65-70% of cases
```

**Rules:**
- Mirror image of rising wedge
- Each successive high is lower (H1 > H2 > H3)
- Each successive low is lower (L1 > L2 > L3)
- Range narrows, volume declines
- Breakout upward with volume confirms

### 1.4 Symmetrical Wedge (Bilateral)

Often called a "symmetrical triangle" — NOT a true wedge in the strict sense. Included here because Hunt's HVF is a variant of this structure.

**Geometry:**
- Upper trendline slopes downward (lower highs)
- Lower trendline slopes upward (higher lows)
- Lines converge from both sides

**Key distinction:** In a symmetrical pattern, price compresses WITHOUT directional bias. Breakout direction is uncertain until it happens. Hunt's HVF IS a symmetrical converging pattern, but with additional wave-structure rules that filter for higher quality setups.

**Relevance to HVF:** The existing `hvf_detector.py` already detects a specific form of symmetrical convergence (3 waves with dual-sided convergence validation). A wedge detector would be a more general version that captures rising and falling wedges that do NOT qualify as HVFs.

### 1.5 Wedge vs Triangle vs HVF — Decision Matrix

| Feature | Rising/Falling Wedge | Symmetrical Triangle | HVF (Hunt) |
|---------|---------------------|---------------------|-------------|
| Trendline direction | Both same direction | Opposite directions | Opposite directions |
| Minimum touches | 2 per line (4 total) | 2 per line (4 total) | 3 per line (6 total, strict alternation) |
| Wave structure | Not required | Not required | 3 converging waves required |
| Volume pattern | Declining | Declining | Declining (scored) |
| Breakout direction | Opposite to slope (~65-70%) | Either direction (~50/50) | Either (but scored by trend alignment) |
| Target calculation | Widest part projected | Widest part projected | Wave 1 range projected from midpoint |
| Success rate (literature) | 65-72% (Bulkowski) | 50-55% | Unknown (Hunt's proprietary data) |

---

## 2. Francis Hunt's Approach to Wedges

### 2.1 Hunt's Framework: Wedges as a Subset

Hunt categorises his patterns within a broader "volatility compression" framework. His core insight: **all converging patterns store energy**, and the breakout releases that stored energy proportional to the initial range.

Based on Hunt's public content (YouTube, themarketsniper.com, Scribd documents, interviews):

1. **HVF IS Hunt's primary wedge/triangle pattern.** He does not typically teach "wedges" as a separate category — instead, he subsumes wedge-like structures under the HVF umbrella, with the key distinction being his 3-wave convergence requirement.

2. **Rising/falling wedges appear in Hunt's analysis** on Gold, Silver, and crypto, but he frames them through the HVF lens: "a subset of triangles as defined by technical analysis" (from Scribd document "Understanding Hunt Volatility Funnels").

3. **Hunt on Gold wedges specifically:** He frequently identifies multi-month wedge formations on Gold (XAUUSD) on D1/W1 timeframes. His YouTube analysis of Gold consistently references:
   - Wedge-like compressions forming over weeks/months
   - The wedge as a "pressure cooker" storing energy
   - Breakout targets derived from the first (widest) oscillation within the wedge
   - Volume contraction during the wedge as confirmation

4. **Hunt on Silver:** Similar to Gold, but he notes Silver's tendency to form "messier" wedges with more erratic wicks, requiring wider stop buffers.

### 2.2 Hunt's Wedge Target Calculation

Hunt's target method for wedge-like patterns (including HVF):

```
Standard TA method:
  Target = Breakout_price +/- (Widest_part_of_wedge)

Hunt's modification:
  Target = Midpoint_of_apex_wave +/- (Wave_1_range * multiplier)
  
  Where:
  - Midpoint = average of the last swing high and swing low before breakout
  - Wave_1_range = the FIRST (widest) oscillation in the convergence
  - Multiplier = 1.0 for T1, variable for T2 (often 1.618 Fibonacci extension)
```

The key difference: Hunt does NOT measure from the breakout point itself. He measures from the **midpoint** of the converging structure. This tends to produce slightly more conservative targets than the standard TA projection, but with higher hit rates.

This is already implemented in `hvf_detector.py:compute_levels()`:
```python
self.midpoint = (self.h3.price + self.l3.price) / 2
self.full_range = self.h1.price - self.l1.price
self.target_1 = self.midpoint + (self.full_range * config.TARGET_1_MULT)
```

### 2.3 Hunt's Timeframes for Wedges

From public interviews and YouTube:
- **Primary:** D1, W1 for Gold and Silver wedges (these form over weeks to months)
- **Secondary:** H4 for intra-week setups
- **Rarely:** H1 (Hunt says the method "works best over the medium to long term")
- **Entry refinement:** After identifying a D1 wedge breakout, Hunt drops to H4 or H1 for entry timing

**Implication for the bot:** If implementing wedge detection, H4 and D1 should be the detection timeframes, with H1 used for entry execution and trade management. This differs from the current KZ_HUNT approach (H1 only).

### 2.4 Hunt's Volume Rules for Wedges

Hunt uses **On Balance Volume (OBV)** as his primary volume tool, not raw tick volume:

1. **During wedge formation:** OBV should flatten or diverge from price. If price makes new highs (rising wedge) but OBV does not, this confirms diminishing buying pressure.
2. **At breakout:** OBV should spike in the breakout direction. A breakout without OBV confirmation is suspect.
3. **Post-breakout:** OBV should continue trending in the breakout direction during the measured move.

Hunt quote: "Volume is the truth detector. Price can lie, volume cannot."

**For MT5 forex implementation:** MT5 provides tick volume, not true exchange volume. OBV computed from tick volume is a reasonable proxy for spot FX, but less reliable than for equities or futures. The existing volume scoring in the KZ_HUNT scorer uses tick volume directly — OBV would be an enhancement.

---

## 3. Algorithmic Wedge Detection Methods

### 3.1 Overview of Approaches

The academic and open-source landscape for automated wedge detection uses several core techniques:

| Approach | Complexity | Accuracy | Speed |
|----------|-----------|----------|-------|
| Swing point + trendline fitting | Medium | High | Medium |
| Rolling regression on highs/lows | Low | Medium | Fast |
| Hough transform (line detection) | High | High | Slow |
| Dynamic programming (optimal trendlines) | High | Highest | Slow |
| Machine learning (CNN/LSTM) | Very High | Variable | Slow (training) |
| Rule-based pivot scanning | Low | Medium | Fast |

**Recommended for this project:** Swing point + trendline fitting. It builds directly on the existing `zigzag.py` infrastructure and provides interpretable results.

### 3.2 Method 1: Swing Point + Trendline Fitting (Recommended)

This is the most practical approach and builds on the existing codebase.

**Algorithm:**

```
Step 1: Identify swing highs and swing lows
  - Use existing compute_zigzag() from zigzag.py
  - Or use a simpler local extrema method (N-bar lookback)
  
Step 2: Fit trendlines to swing highs and swing lows separately
  - For swing highs: linear regression on the last N swing high prices vs time
  - For swing lows: linear regression on the last N swing low prices vs time
  
Step 3: Check convergence criteria
  - Both slopes same sign AND lines converging → Wedge
  - Slopes opposite sign AND converging → Symmetrical triangle
  - Convergence rate: angle between lines decreasing over time
  
Step 4: Validate geometric rules
  - Minimum touch count on each trendline
  - Minimum pattern duration
  - Maximum trendline deviation (how well do points fit the line?)
  
Step 5: Score the pattern
  - Trendline fit quality (R-squared)
  - Number of touches
  - Volume profile
  - Convergence tightness
  - Duration appropriateness
  
Step 6: Detect breakout
  - Price closes beyond trendline boundary
  - Volume confirms
  - Trendline is not re-entered within N bars
```

**Python implementation sketch:**

```python
import numpy as np
from scipy import stats
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class WedgePattern:
    pattern_type: str          # 'RISING_WEDGE', 'FALLING_WEDGE', 'SYMMETRICAL'
    direction: str             # Expected breakout: 'LONG' or 'SHORT'
    
    # Trendline parameters (y = slope * x + intercept)
    upper_slope: float
    upper_intercept: float
    upper_r_squared: float
    lower_slope: float
    lower_intercept: float
    lower_r_squared: float
    
    # Touch points
    upper_touches: list        # List of (index, price) tuples
    lower_touches: list
    
    # Pattern boundaries
    start_index: int
    end_index: int
    apex_index: float          # Projected intersection point
    
    # Calculated levels
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    widest_range: float = 0.0
    score: float = 0.0


def find_swing_points(
    df: pd.DataFrame,
    lookback: int = 5,
) -> tuple[list, list]:
    """
    Find swing highs and swing lows using N-bar lookback.
    
    A swing high at bar i: high[i] > max(high[i-N:i]) AND high[i] > max(high[i+1:i+N+1])
    A swing low at bar i:  low[i]  < min(low[i-N:i])  AND low[i]  < min(low[i+1:i+N+1])
    
    Returns:
        (swing_highs, swing_lows) — each is list of (index, price)
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    
    swing_highs = []
    swing_lows = []
    
    for i in range(lookback, n - lookback):
        # Swing high: current high is the max in the window
        left_max = np.max(highs[i - lookback:i])
        right_max = np.max(highs[i + 1:i + lookback + 1])
        if highs[i] > left_max and highs[i] >= right_max:
            swing_highs.append((i, float(highs[i])))
        
        # Swing low: current low is the min in the window
        left_min = np.min(lows[i - lookback:i])
        right_min = np.min(lows[i + 1:i + lookback + 1])
        if lows[i] < left_min and lows[i] <= right_min:
            swing_lows.append((i, float(lows[i])))
    
    return swing_highs, swing_lows


def fit_trendline(points: list[tuple[int, float]]) -> tuple[float, float, float]:
    """
    Fit a linear regression trendline to a set of (index, price) points.
    
    Returns:
        (slope, intercept, r_squared)
    """
    if len(points) < 2:
        return 0.0, 0.0, 0.0
    
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    r_squared = r_value ** 2
    
    return slope, intercept, r_squared


def find_trendline_touches(
    points: list[tuple[int, float]],
    slope: float,
    intercept: float,
    tolerance_pct: float = 0.002,  # 0.2% of price
) -> list[tuple[int, float]]:
    """
    Find which swing points 'touch' (are within tolerance of) the trendline.
    """
    touches = []
    for idx, price in points:
        trendline_price = slope * idx + intercept
        distance_pct = abs(price - trendline_price) / price
        if distance_pct <= tolerance_pct:
            touches.append((idx, price))
    return touches


def detect_wedges(
    df: pd.DataFrame,
    min_touches: int = 3,           # Minimum touches per trendline
    min_bars: int = 20,             # Minimum pattern duration
    max_bars: int = 200,            # Maximum pattern duration
    swing_lookback: int = 5,        # Swing point detection window
    min_r_squared: float = 0.70,    # Minimum trendline fit quality
    convergence_threshold: float = 0.3,  # Lines must converge by at least 30%
) -> list[WedgePattern]:
    """
    Detect wedge patterns in OHLCV data.
    
    Algorithm:
    1. Find all swing highs and swing lows
    2. Use a sliding window to examine groups of swing points
    3. Fit trendlines to highs and lows within each window
    4. Check if the trendlines form a valid wedge (converging, same direction)
    5. Validate touch count, duration, and fit quality
    """
    swing_highs, swing_lows = find_swing_points(df, lookback=swing_lookback)
    
    if len(swing_highs) < min_touches or len(swing_lows) < min_touches:
        return []
    
    patterns = []
    
    # Sliding window over swing points
    # Try different starting points and window sizes
    for start_h in range(len(swing_highs) - min_touches + 1):
        for end_h in range(start_h + min_touches - 1, len(swing_highs)):
            
            h_points = swing_highs[start_h:end_h + 1]
            h_start_idx = h_points[0][0]
            h_end_idx = h_points[-1][0]
            
            # Pattern duration check
            duration = h_end_idx - h_start_idx
            if duration < min_bars or duration > max_bars:
                continue
            
            # Find swing lows within the same time window
            l_points = [
                (idx, price) for idx, price in swing_lows
                if h_start_idx <= idx <= h_end_idx
            ]
            
            if len(l_points) < min_touches:
                continue
            
            # Fit trendlines
            h_slope, h_intercept, h_r2 = fit_trendline(h_points)
            l_slope, l_intercept, l_r2 = fit_trendline(l_points)
            
            # Quality check: both trendlines must fit well
            if h_r2 < min_r_squared or l_r2 < min_r_squared:
                continue
            
            # Check convergence: range at start vs range at end
            range_at_start = (h_slope * h_start_idx + h_intercept) - \
                             (l_slope * h_start_idx + l_intercept)
            range_at_end = (h_slope * h_end_idx + h_intercept) - \
                           (l_slope * h_end_idx + l_intercept)
            
            if range_at_start <= 0 or range_at_end <= 0:
                continue  # Trendlines already crossed — invalid
            
            convergence_pct = 1.0 - (range_at_end / range_at_start)
            if convergence_pct < convergence_threshold:
                continue  # Not converging enough
            
            # Classify the wedge type
            pattern_type = _classify_wedge(h_slope, l_slope)
            if pattern_type is None:
                continue  # Not a valid wedge geometry
            
            # Calculate apex (projected intersection)
            if abs(h_slope - l_slope) > 1e-10:
                apex_index = (l_intercept - h_intercept) / (h_slope - l_slope)
            else:
                apex_index = h_end_idx + duration  # Parallel — no apex
            
            # Find actual touch points with tolerance
            avg_price = df['close'].iloc[h_start_idx:h_end_idx + 1].mean()
            tolerance = 0.003  # 0.3% of price (adjustable per instrument)
            
            upper_touches = find_trendline_touches(h_points, h_slope, h_intercept, tolerance)
            lower_touches = find_trendline_touches(l_points, l_slope, l_intercept, tolerance)
            
            if len(upper_touches) < min_touches or len(lower_touches) < min_touches:
                continue
            
            # Determine expected breakout direction
            if pattern_type == 'RISING_WEDGE':
                direction = 'SHORT'  # Rising wedges break down
            elif pattern_type == 'FALLING_WEDGE':
                direction = 'LONG'   # Falling wedges break up
            else:
                direction = 'UNKNOWN'
            
            wedge = WedgePattern(
                pattern_type=pattern_type,
                direction=direction,
                upper_slope=h_slope,
                upper_intercept=h_intercept,
                upper_r_squared=h_r2,
                lower_slope=l_slope,
                lower_intercept=l_intercept,
                lower_r_squared=l_r2,
                upper_touches=upper_touches,
                lower_touches=lower_touches,
                start_index=h_start_idx,
                end_index=h_end_idx,
                apex_index=apex_index,
                widest_range=range_at_start,
            )
            
            patterns.append(wedge)
    
    # Deduplicate overlapping patterns (keep highest scored)
    patterns = _deduplicate_patterns(patterns)
    
    return patterns


def _classify_wedge(upper_slope: float, lower_slope: float) -> Optional[str]:
    """
    Classify wedge type based on trendline slopes.
    
    Rising wedge:  both slopes positive, lower slope > upper slope
    Falling wedge: both slopes negative, upper slope < lower slope (more negative)
    Symmetrical:   upper slope negative, lower slope positive
    """
    if upper_slope > 0 and lower_slope > 0:
        if lower_slope > upper_slope:
            return 'RISING_WEDGE'
        else:
            return None  # Expanding, not converging
    
    elif upper_slope < 0 and lower_slope < 0:
        if abs(upper_slope) > abs(lower_slope):
            return 'FALLING_WEDGE'
        else:
            return None  # Expanding
    
    elif upper_slope < 0 and lower_slope > 0:
        return 'SYMMETRICAL'
    
    elif upper_slope > 0 and lower_slope < 0:
        return None  # Expanding (broadening pattern, NOT a wedge)
    
    return None


def _deduplicate_patterns(patterns: list[WedgePattern]) -> list[WedgePattern]:
    """Remove overlapping patterns, keeping the highest quality one."""
    if len(patterns) <= 1:
        return patterns
    
    # Sort by combined R-squared descending
    patterns.sort(
        key=lambda p: (p.upper_r_squared + p.lower_r_squared) / 2,
        reverse=True
    )
    
    kept = []
    for p in patterns:
        overlaps = False
        for k in kept:
            # Check if patterns overlap in time
            overlap_start = max(p.start_index, k.start_index)
            overlap_end = min(p.end_index, k.end_index)
            if overlap_end > overlap_start:
                overlap_pct = (overlap_end - overlap_start) / (p.end_index - p.start_index)
                if overlap_pct > 0.5:
                    overlaps = True
                    break
        if not overlaps:
            kept.append(p)
    
    return kept
```

### 3.3 Method 2: Rolling Regression (Simpler, Faster)

A lightweight approach that doesn't require explicit swing point detection:

```python
def detect_wedge_rolling(
    df: pd.DataFrame,
    window: int = 50,          # Bars to consider
    regression_period: int = 20,  # Bars for regression
) -> Optional[str]:
    """
    Simple wedge detection using rolling linear regression on highs and lows.
    
    Returns pattern type or None.
    """
    if len(df) < window:
        return None
    
    recent = df.iloc[-window:]
    
    # Rolling max high and rolling min low
    x = np.arange(window, dtype=float)
    
    # Regression on highs (using local maxima or just raw highs)
    h_slope, h_intercept, h_r, _, _ = stats.linregress(x, recent['high'].values)
    l_slope, l_intercept, l_r, _, _ = stats.linregress(x, recent['low'].values)
    
    # Check convergence
    range_start = (h_slope * 0 + h_intercept) - (l_slope * 0 + l_intercept)
    range_end = (h_slope * (window - 1) + h_intercept) - (l_slope * (window - 1) + l_intercept)
    
    if range_start <= 0 or range_end <= 0:
        return None
    
    convergence = 1.0 - (range_end / range_start)
    
    if convergence < 0.2:
        return None  # Not converging enough
    
    # Classify
    if h_slope > 0 and l_slope > 0 and l_slope > h_slope:
        return 'RISING_WEDGE'
    elif h_slope < 0 and l_slope < 0 and abs(h_slope) > abs(l_slope):
        return 'FALLING_WEDGE'
    elif h_slope < 0 and l_slope > 0:
        return 'SYMMETRICAL'
    
    return None
```

**Pros:** Very fast, no swing detection needed, easy to implement.
**Cons:** Lower accuracy, many false positives, doesn't identify specific touch points, not suitable for precise entry/exit levels.

### 3.4 Method 3: Hough Transform (Academic)

Used in some academic papers (e.g., Lo, Mamaysky & Wang 2000 — "Foundations of Technical Analysis"):

1. Convert price chart to a 2D image
2. Apply Hough line transform to detect dominant lines
3. Identify line pairs that converge
4. Classify based on slope characteristics

**Pros:** Can detect non-obvious trendlines that human eye would miss.
**Cons:** Computationally expensive, requires image processing libraries, hard to tune, overkill for this use case.

### 3.5 Method 4: Dynamic Time Warping / Template Matching

Match current price action against a library of "ideal" wedge templates:

1. Create template wedge shapes (rising, falling, symmetrical) at various scales
2. Use Dynamic Time Warping (DTW) to find best match between current price and templates
3. Score the match quality

**Pros:** Handles time dilation well (slow wedges vs fast wedges).
**Cons:** Requires good template library, computationally expensive, less interpretable.

### 3.6 Method 5: Machine Learning (Neural Network)

Train a CNN or LSTM on labeled wedge patterns:

1. Label historical data with wedge occurrences
2. Train model on OHLCV windows
3. Model predicts wedge probability for current window

**Open source implementations:**
- `chartpatternrecognition` (GitHub) — uses CNN on candlestick images
- `stockstats` — basic pattern detection with statistical methods
- `ta-lib` — CDL pattern functions (candlestick, not chart patterns like wedges)

**Verdict:** ML approaches require labeled training data (expensive to create) and don't generalize well across instruments/timeframes. Not recommended for this project.

---

## 4. Breakout Detection and Confirmation

### 4.1 Breakout Definition

A breakout occurs when price closes beyond the trendline boundary:

```python
def check_breakout(
    df: pd.DataFrame,
    wedge: WedgePattern,
    bar_index: int,
    atr: float,
) -> Optional[str]:
    """
    Check if the current bar breaks out of the wedge.
    
    Returns 'BULLISH', 'BEARISH', or None.
    """
    close = df['close'].iloc[bar_index]
    
    # Calculate trendline values at current bar
    upper_line = wedge.upper_slope * bar_index + wedge.upper_intercept
    lower_line = wedge.lower_slope * bar_index + wedge.lower_intercept
    
    # Breakout buffer: price must close at least 0.1x ATR beyond trendline
    buffer = 0.1 * atr
    
    if close > upper_line + buffer:
        return 'BULLISH'
    elif close < lower_line - buffer:
        return 'BEARISH'
    
    return None
```

### 4.2 False Breakout Filters

False breakouts (fakeouts) are the primary risk with wedge trading. Multiple filters reduce false signals:

**Filter 1: Volume Confirmation**
```python
def volume_confirms_breakout(
    df: pd.DataFrame,
    breakout_bar: int,
    lookback: int = 20,
    multiplier: float = 1.5,
) -> bool:
    """Breakout bar volume must exceed N-bar average by multiplier."""
    vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume'
    breakout_vol = df[vol_col].iloc[breakout_bar]
    avg_vol = df[vol_col].iloc[breakout_bar - lookback:breakout_bar].mean()
    return breakout_vol > avg_vol * multiplier
```

**Filter 2: Close-Based (Not Wick-Based)**
- Only count a breakout when the candle **closes** beyond the trendline, not just wicks through it
- Wick-only penetrations are frequently false breakouts
- This is already consistent with the HVF/KZ_HUNT confirmation approach in the existing codebase

**Filter 3: Retest Confirmation**
```python
def check_retest(
    df: pd.DataFrame,
    wedge: WedgePattern,
    breakout_bar: int,
    breakout_direction: str,
    lookback_bars: int = 5,
    atr: float = 0.0,
) -> bool:
    """
    After breakout, check if price retests the broken trendline
    and holds (doesn't re-enter the wedge).
    
    This is the 'Stage 2: Second Chance' in Hunt's framework.
    """
    for i in range(breakout_bar + 1, min(breakout_bar + lookback_bars + 1, len(df))):
        close = df['close'].iloc[i]
        
        if breakout_direction == 'BULLISH':
            upper_line = wedge.upper_slope * i + wedge.upper_intercept
            # Price should stay above upper trendline (now support)
            if close < upper_line - (0.2 * atr):
                return False  # Re-entered wedge — false breakout
        
        elif breakout_direction == 'BEARISH':
            lower_line = wedge.lower_slope * i + wedge.lower_intercept
            if close > lower_line + (0.2 * atr):
                return False
    
    return True
```

**Filter 4: Time-Based**
- If a breakout doesn't produce a follow-through move within N bars, it's likely false
- For H1: 3-5 bars (3-5 hours) is reasonable
- For D1: 2-3 bars (2-3 days)

**Filter 5: RSI Divergence (Classic Confirmation)**
```python
def check_rsi_divergence(
    df: pd.DataFrame,
    wedge: WedgePattern,
) -> bool:
    """
    Classic: RSI divergence during wedge confirms breakout direction.
    
    Rising wedge + bearish RSI divergence = high-probability short
    Falling wedge + bullish RSI divergence = high-probability long
    """
    if 'rsi' not in df.columns:
        return False  # Can't check without RSI
    
    # Get RSI at the last two swing highs (rising wedge) or lows (falling wedge)
    if wedge.pattern_type == 'RISING_WEDGE':
        # Price making higher highs but RSI making lower highs = bearish divergence
        touches = wedge.upper_touches
        if len(touches) < 2:
            return False
        
        last_touch = touches[-1]
        prev_touch = touches[-2]
        
        price_rising = last_touch[1] > prev_touch[1]
        rsi_last = df['rsi'].iloc[last_touch[0]]
        rsi_prev = df['rsi'].iloc[prev_touch[0]]
        rsi_falling = rsi_last < rsi_prev
        
        return price_rising and rsi_falling  # Bearish divergence
    
    elif wedge.pattern_type == 'FALLING_WEDGE':
        # Price making lower lows but RSI making higher lows = bullish divergence
        touches = wedge.lower_touches
        if len(touches) < 2:
            return False
        
        last_touch = touches[-1]
        prev_touch = touches[-2]
        
        price_falling = last_touch[1] < prev_touch[1]
        rsi_last = df['rsi'].iloc[last_touch[0]]
        rsi_prev = df['rsi'].iloc[prev_touch[0]]
        rsi_rising = rsi_last > rsi_prev
        
        return price_falling and rsi_rising  # Bullish divergence
    
    return False
```

### 4.3 Breakout Failure Rate (Literature)

From Thomas Bulkowski's "Encyclopedia of Chart Patterns" (the most comprehensive statistical study):

| Pattern | Breakout in Expected Direction | Average Move | Failure Rate (< 5% move) |
|---------|-------------------------------|-------------|--------------------------|
| Rising Wedge (bearish break) | 65-68% | -14% to -18% | 24% |
| Falling Wedge (bullish break) | 68-72% | +32% to +38% | 19% |
| With volume confirmation | +5-8% improvement | +2-4% larger moves | -5-8% fewer failures |
| With RSI divergence | +8-12% improvement | Similar | -10-15% fewer failures |

**Key insight:** Falling wedges are more reliable than rising wedges. Adding volume and RSI divergence filters significantly improves accuracy.

---

## 5. Measured Move Targets

### 5.1 Standard Technical Analysis Approach

```python
def calculate_standard_targets(
    wedge: WedgePattern,
    breakout_price: float,
) -> tuple[float, float]:
    """
    Standard TA: project the widest part of the wedge from breakout point.
    """
    widest = wedge.widest_range
    
    if wedge.direction == 'LONG':
        target_1 = breakout_price + widest * 0.618   # Conservative
        target_2 = breakout_price + widest * 1.0      # Standard
    elif wedge.direction == 'SHORT':
        target_1 = breakout_price - widest * 0.618
        target_2 = breakout_price - widest * 1.0
    
    return target_1, target_2
```

### 5.2 Hunt's Modified Approach

```python
def calculate_hunt_targets(
    wedge: WedgePattern,
    last_swing_high: float,
    last_swing_low: float,
) -> tuple[float, float]:
    """
    Hunt's approach: project Wave 1 (widest oscillation) range from
    the midpoint of the apex (last swing high/low pair).
    """
    midpoint = (last_swing_high + last_swing_low) / 2
    wave1_range = wedge.widest_range
    
    if wedge.direction == 'LONG':
        target_1 = midpoint + wave1_range * 1.0     # T1: 100% of Wave 1
        target_2 = midpoint + wave1_range * 1.618   # T2: Fibonacci extension
    elif wedge.direction == 'SHORT':
        target_1 = midpoint - wave1_range * 1.0
        target_2 = midpoint - wave1_range * 1.618
    
    return target_1, target_2
```

### 5.3 Fibonacci Extension Targets (Common Enhancement)

Many traders layer Fibonacci extensions on top of the measured move:

- **61.8%** of widest range — conservative T1
- **100%** of widest range — standard T1
- **127.2%** of widest range — extended target
- **161.8%** of widest range — aggressive T2
- **261.8%** of widest range — rare but possible in strong trends

### 5.4 Target Hit Rates (Bulkowski Data)

| Target Level | Rising Wedge (Short) | Falling Wedge (Long) |
|-------------|---------------------|---------------------|
| 50% of projection | 72% | 78% |
| 75% of projection | 58% | 65% |
| 100% of projection | 46% | 55% |
| 150% of projection | 28% | 38% |

**Implication:** Partial closes at 50-61.8% of the measured move (T1) followed by trailing are more reliable than targeting the full projection. This aligns with the existing bot's partial close + trail strategy.

---

## 6. Multi-Timeframe Wedge Detection

### 6.1 The Multi-TF Problem

Wedges on D1 or W1 take weeks/months to form. The bot runs on H1. How to handle this?

**Approach: Hierarchical Detection**

```
D1 Scanner (runs once per day):
  → Detect wedges on daily chart (50-200 bar lookback)
  → If wedge nearing apex or trendline, flag for H1 monitoring

H4 Scanner (runs every 4 hours):
  → Detect wedges on H4 chart (30-150 bar lookback)
  → Cross-reference with D1 wedge context

H1 Execution (runs every cycle, 60s):
  → If D1 or H4 wedge is flagged, monitor for breakout on H1
  → Entry, SL, and targets calculated from the higher-TF wedge dimensions
  → H1 used only for entry timing and trade management
```

### 6.2 Implementation for the Bot

```python
# In main.py scanner loop:

class WedgeMonitor:
    """Tracks wedge formations across multiple timeframes."""
    
    def __init__(self):
        self.active_wedges = {}  # symbol -> list of WedgePattern
        self.last_d1_scan = None
        self.last_h4_scan = None
    
    def scan_higher_timeframes(self, symbol: str, df_h4: pd.DataFrame, df_d1: pd.DataFrame):
        """
        Run infrequently (H4: every 4h, D1: every 24h).
        Detect wedge formations and store them.
        """
        d1_wedges = detect_wedges(df_d1, min_touches=3, min_bars=15, max_bars=120)
        h4_wedges = detect_wedges(df_h4, min_touches=3, min_bars=20, max_bars=150)
        
        self.active_wedges[symbol] = {
            'd1': d1_wedges,
            'h4': h4_wedges,
        }
    
    def check_h1_breakout(self, symbol: str, df_h1: pd.DataFrame, current_atr: float):
        """
        Run every H1 cycle.
        Check if any active higher-TF wedge is breaking out on H1.
        """
        if symbol not in self.active_wedges:
            return None
        
        for timeframe, wedges in self.active_wedges[symbol].items():
            for wedge in wedges:
                # Scale trendline parameters from higher TF to H1 bar indices
                # ... (index mapping logic)
                
                breakout = check_breakout(df_h1, wedge, len(df_h1) - 1, current_atr)
                if breakout:
                    if volume_confirms_breakout(df_h1, len(df_h1) - 1):
                        return wedge, breakout
        
        return None
```

### 6.3 Data Requirements

| Timeframe | Bars Needed | Period Covered | Data Source |
|-----------|-------------|----------------|-------------|
| H1 | 500-1000 | 3-6 weeks | Already fetched |
| H4 | 500-750 | 3-5 months | Need to add to data_fetcher.py |
| D1 | 200-500 | 10-24 months | Need to add to data_fetcher.py |

The current `data_fetcher.py` fetches H1 and H4 data. D1 data would need to be added.

---

## 7. Scoring Framework for Wedge Quality

### 7.1 Proposed Scoring Components

```python
def score_wedge(
    wedge: WedgePattern,
    df: pd.DataFrame,
    atr: float,
) -> float:
    """
    Score wedge quality 0-100.
    Higher score = higher confidence in breakout.
    """
    score = 0.0
    
    # 1. Trendline fit quality (0-20)
    avg_r2 = (wedge.upper_r_squared + wedge.lower_r_squared) / 2
    if avg_r2 >= 0.95:
        score += 20
    elif avg_r2 >= 0.90:
        score += 15
    elif avg_r2 >= 0.85:
        score += 10
    elif avg_r2 >= 0.80:
        score += 5
    
    # 2. Touch count (0-15)
    min_touches = min(len(wedge.upper_touches), len(wedge.lower_touches))
    if min_touches >= 4:
        score += 15
    elif min_touches >= 3:
        score += 10
    elif min_touches >= 2:
        score += 5
    
    # 3. Convergence quality (0-15)
    range_at_start = wedge.widest_range
    range_at_end = (wedge.upper_slope * wedge.end_index + wedge.upper_intercept) - \
                   (wedge.lower_slope * wedge.end_index + wedge.lower_intercept)
    convergence_pct = 1.0 - (range_at_end / range_at_start) if range_at_start > 0 else 0
    
    if convergence_pct >= 0.70:
        score += 15
    elif convergence_pct >= 0.50:
        score += 10
    elif convergence_pct >= 0.30:
        score += 5
    
    # 4. Volume profile (0-15)
    # Check for declining volume during wedge
    vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume'
    first_half_vol = df[vol_col].iloc[wedge.start_index:
        (wedge.start_index + wedge.end_index) // 2].mean()
    second_half_vol = df[vol_col].iloc[
        (wedge.start_index + wedge.end_index) // 2:wedge.end_index + 1].mean()
    
    if second_half_vol < first_half_vol * 0.7:
        score += 15  # Strong volume contraction
    elif second_half_vol < first_half_vol * 0.85:
        score += 10  # Moderate contraction
    elif second_half_vol < first_half_vol:
        score += 5   # Slight contraction
    
    # 5. RSI divergence (0-15)
    if check_rsi_divergence(df, wedge):
        score += 15
    
    # 6. Duration appropriateness (0-10)
    # Too short = unreliable, too long = energy dissipated
    duration = wedge.end_index - wedge.start_index
    ideal_min = 30   # ~30 bars
    ideal_max = 120  # ~120 bars
    if ideal_min <= duration <= ideal_max:
        score += 10
    elif 20 <= duration < ideal_min or ideal_max < duration <= 200:
        score += 5
    
    # 7. EMA200 trend alignment (0-10)
    if 'ema_200' in df.columns:
        current_price = df['close'].iloc[wedge.end_index]
        ema = df['ema_200'].iloc[wedge.end_index]
        
        if wedge.direction == 'LONG' and current_price > ema:
            score += 10  # Bullish wedge above EMA200
        elif wedge.direction == 'SHORT' and current_price < ema:
            score += 10  # Bearish wedge below EMA200
        elif wedge.direction == 'LONG' and current_price < ema:
            score += 3   # Counter-trend — lower confidence
        elif wedge.direction == 'SHORT' and current_price > ema:
            score += 3
    
    return min(score, 100.0)
```

### 7.2 Scoring Component Weights Summary

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Trendline fit (R-squared) | 20 | Poorly fitting lines = ambiguous pattern |
| Touch count | 15 | More touches = more validated trendlines |
| Convergence quality | 15 | Tighter convergence = more stored energy |
| Volume contraction | 15 | Classic confirmation of genuine compression |
| RSI divergence | 15 | Strongest single confirmation signal |
| Duration | 10 | Sweet spot exists — too short/long is worse |
| EMA200 alignment | 10 | Trend-aligned breakouts have higher success |

---

## 8. Open-Source Implementations and References

### 8.1 Notable Open-Source Projects

1. **`chart_patterns`** (PyPI package) — Basic chart pattern detection including wedges. Uses pivot point detection + trendline fitting. Python.

2. **`mplfinance`** — Matplotlib financial plotting library. Doesn't detect patterns but provides visualization infrastructure.

3. **TradingView Pine Script community** — Hundreds of wedge detection scripts. Key ones:
   - "Auto Wedge / Triangle Pattern" by various authors — uses pivot-based trendline detection
   - "Wedge Pattern Detector" — swing high/low + linear regression approach
   - Most use `ta.pivothigh()` / `ta.pivotlow()` as the swing detection foundation

4. **TA-Lib** — CDL (candlestick) functions only. Does NOT detect chart-level patterns like wedges. Not useful for this purpose.

5. **`stockstats`** — Statistical stock analysis. Basic trend detection but no wedge-specific functions.

### 8.2 Academic References

1. **Lo, Mamaysky & Wang (2000)** — "Foundations of Technical Analysis: Computational Algorithms, Statistical Inference, and Empirical Implementation." NBER Working Paper. Foundational paper on algorithmic pattern detection including wedges. Uses kernel regression smoothing + pattern template matching.

2. **Bulkowski, Thomas** — "Encyclopedia of Chart Patterns" (3rd edition). The most comprehensive statistical study of chart patterns including rising and falling wedges. 1,000+ patterns cataloged with success rates, failure rates, and measured move statistics.

3. **Leigh et al. (2002)** — "Stock market trading rule discovery using technical charting heuristics." Uses genetic algorithms to optimize pattern recognition parameters.

4. **Zapranis & Tsinaslanidis (2012)** — "A novel, rule-based technical pattern identification mechanism." Formal rule-based approach to pattern classification.

### 8.3 Key TradingView Pine Script Patterns

The most common algorithmic approach on TradingView (Pine Script pseudocode adapted):

```
// Simplified Pine Script logic for wedge detection
pivotHigh = ta.pivothigh(high, leftBars, rightBars)
pivotLow  = ta.pivotlow(low, leftBars, rightBars)

// Collect last N pivot highs and lows
// Fit regression line to highs, fit regression line to lows
// Check: same-direction slopes + convergence → wedge
// Check: opposite-direction slopes + convergence → triangle
```

---

## 9. Practical Implementation Plan for HVF Bot

### 9.1 Where Wedge Detection Fits in the Architecture

```
Current:                          With Wedges:
                                  
H1 data → KZ_HUNT detector       H1 data → KZ_HUNT detector (unchanged)
         → (HVF detector, off)             → (HVF detector, off)
                                           → Wedge detector (NEW)
                                  
                                  H4 data → Wedge scanner (higher TF)
                                  D1 data → Wedge scanner (higher TF)
```

### 9.2 New Files Needed

```
hvf_trader/
    detector/
        wedge_detector.py         # NEW — core wedge detection algorithm
        wedge_scorer.py           # NEW — quality scoring (0-100)
        wedge_monitor.py          # NEW — multi-TF wedge tracking
```

### 9.3 Config Additions

```python
# ─── Wedge Detection ─────────────────────────────────────────────────────
WEDGE_SWING_LOOKBACK = 5               # N-bar lookback for swing detection
WEDGE_MIN_TOUCHES = 3                  # Minimum touches per trendline
WEDGE_MIN_BARS_H1 = 20                 # Minimum pattern duration (H1)
WEDGE_MAX_BARS_H1 = 200               # Maximum pattern duration (H1)
WEDGE_MIN_BARS_H4 = 15                # Minimum pattern duration (H4)
WEDGE_MAX_BARS_H4 = 150               # Maximum pattern duration (H4)
WEDGE_MIN_BARS_D1 = 10                # Minimum pattern duration (D1)
WEDGE_MAX_BARS_D1 = 120               # Maximum pattern duration (D1)
WEDGE_MIN_R_SQUARED = 0.75            # Minimum trendline fit quality
WEDGE_CONVERGENCE_MIN = 0.25          # Lines must converge by at least 25%
WEDGE_BREAKOUT_ATR_BUFFER = 0.1       # Close must exceed trendline by 0.1x ATR
WEDGE_VOLUME_DECLINE_THRESHOLD = 0.85 # Volume 2nd half < 85% of 1st half
WEDGE_RETEST_BARS = 5                 # Bars to wait for retest confirmation
WEDGE_SL_ATR_MULT = 0.5              # SL beyond opposite trendline + ATR buffer
WEDGE_TARGET_1_MULT = 0.618          # T1: 61.8% of measured move
WEDGE_TARGET_2_MULT = 1.0            # T2: 100% of measured move (Hunt: from midpoint)
WEDGE_USE_HUNT_TARGETS = True         # True = midpoint-based, False = breakout-based
WEDGE_RSI_DIVERGENCE_BONUS = 15       # Score bonus for RSI divergence
WEDGE_ENABLED_TIMEFRAMES = ['H4', 'D1']  # Detect on these, execute on H1

# Per-pattern additions
SCORE_THRESHOLD_BY_PATTERN["WEDGE"] = 55
MIN_RRR_BY_PATTERN["WEDGE"] = 1.0
RISK_PCT_BY_PATTERN["WEDGE"] = 0.5   # Start conservative
TRAILING_STOP_ATR_MULT_BY_PATTERN["WEDGE"] = 1.5
```

### 9.4 Integration with Existing Pipeline

```
fetch_and_prepare()
  → add H4 and D1 data if not already present
  → compute indicators on all timeframes (ATR, EMA200, RSI, ADX)

wedge_monitor.scan_higher_timeframes()  (every 4h or 24h)
  → detect_wedges() on H4 and D1 data
  → store active wedge formations per symbol

Every scanner cycle (60s):
  → wedge_monitor.check_h1_breakout() for each symbol with active wedge
  → if breakout detected + volume confirmed + score >= threshold:
    → create TradeSignal (same as KZ_HUNT)
    → pass through normal risk gates
    → execute via order_manager
```

### 9.5 Data Fetcher Changes

```python
# Add to data_fetcher.py:

def fetch_daily_data(symbol: str, bars: int = 500) -> pd.DataFrame:
    """Fetch D1 OHLCV + indicators for wedge detection."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, bars)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    add_indicators(df)  # ATR, EMA200, RSI, ADX
    return df

# Add OBV calculation for Hunt-style volume analysis:
def add_obv(df: pd.DataFrame) -> pd.DataFrame:
    """Add On Balance Volume (OBV) column."""
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i-1]:
            obv.append(obv[-1] + df['tick_volume'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i-1]:
            obv.append(obv[-1] - df['tick_volume'].iloc[i])
        else:
            obv.append(obv[-1])
    df['obv'] = obv
    return df
```

---

## 10. Risks and Caveats

### 10.1 Why Wedge Detection Is Hard

1. **Subjectivity:** Two traders looking at the same chart often disagree on whether a wedge exists. Trendline placement is inherently subjective — small changes in which swing points you connect produce different patterns.

2. **Hindsight bias:** Wedges are easy to see after they complete. Real-time detection requires deciding "is this a wedge forming?" with incomplete information.

3. **Timeframe sensitivity:** A pattern visible on D1 may not be visible on H1, and vice versa. The same price action can look like a wedge on one timeframe and a channel on another.

4. **Parameter sensitivity:** Swing lookback period, minimum touches, R-squared threshold, and convergence rate all dramatically affect detection frequency and quality. Overfitting risk is high.

### 10.2 Expected Performance vs Other Patterns

| Metric | KZ_HUNT (current) | Wedge (projected) |
|--------|-------------------|-------------------|
| Frequency (per pair/year) | 60-130 | 5-15 (H4/D1 only) |
| Expected win rate | 49-55% (truthful BT) | 55-65% (with filters) |
| Average trade duration | 4-24 hours | 24-72 hours |
| RRR range | 1.0-2.0 | 1.5-3.0 |
| Detection complexity | Low (rule-based) | High (regression + validation) |
| False positive rate | Medium | High (without filters) |

### 10.3 Honest Assessment

Wedge detection is a meaningful addition to the bot IF:
1. It targets H4/D1 timeframes (where wedges are more reliable)
2. It uses Hunt's midpoint-based targeting (more conservative than standard TA)
3. RSI divergence is used as a required (not optional) filter
4. Volume contraction is validated
5. Position sizing is conservative (0.5% risk initially)

Wedge detection is NOT worth implementing if:
1. It's limited to H1 only (too many false positives)
2. Sample sizes remain small (5-15 trades/year)
3. The bot already has enough trade frequency from KZ_HUNT

### 10.4 Relationship to Existing HVF Detector

The existing HVF detector already captures the BEST wedge-like patterns (symmetrical convergence with strict 3-wave validation). A generic wedge detector would capture ADDITIONAL patterns that fail HVF's strict requirements but still represent valid compression/breakout setups.

Think of it as a relaxation of HVF rules:
- HVF: 6 pivots, strict alternation, dual-sided convergence, 3 waves
- Wedge: 4+ pivot touches, same-direction trendlines, no wave count requirement

The wedge detector would catch patterns the HVF misses — particularly rising and falling wedges (where both trendlines slope the same direction), which HVF explicitly excludes by requiring dual-sided convergence.

---

## 11. Summary and Recommendations

### For Implementation Priority

Given the current state (KZ_HUNT is the active strategy with PF=1.40 truthful WF backtest):

1. **LOW priority for immediate implementation.** The bot needs 50+ trades under the current split-order system before adding new pattern types. Adding wedge detection now would complicate data collection.

2. **MEDIUM priority for research continuation.** The algorithms are well-defined and buildable. When the time comes, the swing-point + trendline fitting approach (Method 1) is the clear winner for this codebase.

3. **HIGH priority for Gold/Silver expansion.** If you add XAUUSD or XAGUSD to the instrument list, wedge detection becomes much more valuable — these instruments form textbook wedges on D1 that Hunt explicitly trades.

### Next Steps (When Ready)

1. Build `wedge_detector.py` using the swing point + trendline fitting algorithm from Section 3.2
2. Add D1 data fetching to `data_fetcher.py`
3. Add OBV indicator
4. Backtest on XAUUSD D1 first (strongest use case for Hunt's wedge approach)
5. If PF > 1.2 on 30+ trades, integrate with the live bot
6. Start with 0.5% risk, conservative targets (61.8% measured move for T1)

### Key Implementation Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Detection timeframe | H4 and D1 (NOT H1) | Wedges are unreliable below H4 |
| Target calculation | Hunt's midpoint method | More conservative, higher hit rate |
| Minimum touches | 3 per trendline (6 total) | 2-touch trendlines are too unreliable |
| RSI divergence | Required (not optional) | Strongest single filter for false breakouts |
| Volume confirmation | Required | Hunt's core principle |
| Initial risk | 0.5% per trade | Unproven pattern type |
| Primary instruments | XAUUSD, XAGUSD | Hunt's specialty; add forex pairs after validation |
