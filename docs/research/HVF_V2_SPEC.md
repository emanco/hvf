# HVF v2 — Pattern Specification (research output, pre-implementation)

**Status:** DRAFT FOR REVIEW. Nothing here is implemented.
**Date:** 2026-08-02
**Supersedes:** the retired HVF detector (`hvf_trader/detector/hvf_detector.py`, retired 2026-06-02).

---

## 0. How to read this document

Every rule is tagged with its evidential status. This tagging is the most important
part of the document — it marks the boundary between what we recovered and what we
invented.

| Tag | Meaning |
|---|---|
| **[V]** | **Validated** — reproduced numerically from Francis Hunt's own charts to stated precision. |
| **[D]** | **Doctrine** — stated by Hunt or a primary source. Not independently verified by us. |
| **[I]** | **Inferred** — our reading of indirect evidence. Plausible, unconfirmed. |
| **[C]** | **Our choice** — genuinely undetermined by any source. We are deciding it. Must be pre-committed and never tuned post hoc. |

Evidence base: 18 screenshots of Hunt's "HVF Drawing Tool" v13/v14 in
`/Users/manu/Dev/hvf/charts/`, transcribed twice independently (once by the primary
analysis, once blind), plus public-source research into Hunt's published method.

**Naming correction:** HVF is **"Hunt Volatility Funnel"** — an eponym, not "High
Volatility Funnel". Every primary source uses "Hunt". The funnel is a *low*-volatility
coil; "volatility" names the compression→expansion cycle, not the coil. **[D]**

---

## 1. The object

An HVF is a **six-pivot contracting structure that follows the exhaustion of a trend**,
resolving in the direction of that trend.

Hunt's own concession, in a paper titled *"Something New and Original or Just a
Symmetrical Triangle?"*: every HVF **is** a symmetrical triangle; not every symmetrical
triangle is an HVF. The HVF is a **subset**. The claimed differentiators are procedural,
not geometric **[D]**:

1. A clear prior trend is mandatory; choppy or flat origins are rejected outright.
2. Pivots must be corroborated by price action, not merely by line touches.
3. Horizontal price levels take priority over diagonal trendlines.
4. Stop and target are knowable **before** the break, which is what makes pending
   orders and pre-trade sizing possible.

Point 4 is the operational heart of the method and the reason the geometry is worth
automating at all.

### 1.1 Pivot naming

Six alternating pivots. The first two define a range; the other four contract inside it.

**Bullish variant** (prior trend up):

```
H1   — the exhaustion high that ends the prior uptrend      -> fib 1.0
RL1  — the low of the countertrend collapse                 -> fib 0.0
RH2, RL2, RH3, RL3 — successive contracting pivots
```

**Bearish variant** (prior trend down), strictly mirrored:

```
L1   — the exhaustion low that ends the prior downtrend     -> fib 0.0
RH1  — the high of the countertrend rally                   -> fib 1.0
RL2, RH2, RL3, RH3
```

The count **does not begin until the prior trend reaches its exhaustion point**; pivots
before H1/L1 are not eligible **[D]**.

### 1.2 The fib scale

All pivots are quoted as a fraction of the first range:

```
a = low anchor  (RL1 for bullish, L1 for bearish)   -> fib 0.0
b = high anchor (H1 for bullish, RH1 for bearish)   -> fib 1.0
fib(P) = (P - a) / (b - a)
```

**The scale is always linear**, including on charts flagged `Projection: Log`. **[V]**

Verified by reconstruction: on US 5Y, `RH3=0.47 -> 4.147` and `RL3=0.27 -> 3.817` implies
anchors of 3.3715 and 5.0215, which are the actual Sep-2024 low and Oct-2023 high of the
US 5-year yield. The inverse-solve lands on real, nameable pivots across every legible
chart.

### 1.3 AMP1

```
AMP1 = b - a     (the full first range, H1 -> RL1)
```

Hunt's paper calls this the "primary target amplitude" and names it AMP1, implying an
AMP2 exists. **The AMP2 construction is not public.** See §9.1. **[D]**

---

## 2. Validated formulas

These four are reproduced from the tool's own output. Precision is stated per rule.

### 2.1 Slung **[V]**

```
slung = (fib(RH3) + fib(RL3)) / 2
```

The vertical centre of the final contraction, in range units.

**13/13 charts agree to within 0.005** — exactly the bound imposed by the panel's
2-decimal display. Maximum residual 0.0050. This is as tight as the evidence physically
permits.

Note `slung` is a *linear* midpoint of the two third-order pivots, in both projection
modes.

### 2.2 Direction **[V] + [D]**

Direction follows the **prior trend into the exhaustion point**, not the shape of the
funnel:

```
prior trend up   -> first pivot is H1 -> LONG,  break upward
prior trend down -> first pivot is L1 -> SHORT, break downward
```

13/13 charts consistent. The tool encodes this in its panel row order: longs print
`RH2/RL2/RH3/RL3` with target above entry above stop; shorts print `RL2/RH2/RL3/RH3`
with target below entry below stop.

> **This is the single rule the old implementation lacked.** In the retired detector the
> LONG and SHORT branches were byte-identical (`hvf_detector.py:193-197` vs `:198-202`),
> so direction was decided purely by whether the 6-pivot window happened to start on a
> high or a low — array-index parity, not directional evidence.

### 2.3 Entry and stop **[V]**

```
LONG :  entry = price(RH3)   stop = price(RL3)
SHORT:  entry = price(RL3)   stop = price(RH3)
```

Entry is a **pending stop order** at the third-order rail — Hunt's term is "tripwire",
and never entering at market is one of the few rules he publishes openly **[D]**.

Confirmed via RRR (§2.4), which reproduces to a median residual of 0.0038 only under
this assignment.

### 2.4 Risk/reward **[V]**

```
RRR = |target - entry| / |entry - stop|
```

13/13 charts. Median residual 0.0038, max 0.0200 (HYG, whose prices carry only 2dp).

### 2.5 Target **[V]**

Let `mid` be the price midpoint of the final contraction:

```
mid = a + slung * (b - a)          # arithmetic, both modes
```

Then apply the AMP1 displacement — **additively in Linear mode, multiplicatively in Log
mode**:

```
Linear:  target = mid + dir * (b - a)
Log:     target = mid * (b/a)      if dir > 0
         target = mid / (b/a)      if dir < 0     [I] — no short-log example in the data
```

Accuracy against the tool's printed targets:

| Mode | n | Mean abs error | Max |
|---|---|---|---|
| Linear | 8 | **0.106%** | 0.584% |
| Log | 5 | **0.347%** | 0.744% |

**Rejected alternatives** (same data):

| Model | Mean abs error |
|---|---|
| Log as a pure fib extension `a·(b/a)^(1+slung)` | 1.90% |
| Linear projection applied to log-flagged charts | 6.44% |
| Classic measured move from the range edge, not the midpoint | R² = **−18.4** |

The last line is the important negative result: **the textbook triangle target is
decisively wrong.** The midpoint anchor is not a refinement, it is the rule.

Independently corroborated three ways: (a) numerically from the pixels; (b) a student
write-up of Hunt's method states the target as *"the distance between the first high and
the first low measured from the midpoint between the third high and the third low"* —
algebraically identical **[D]**; (c) the retired implementation's own
`target_2 = midpoint(h3,l3) + w1` had the formula right.

### 2.6 Linear vs Log selection **[V] for semantics, [C] for the rule**

Restricting to the 7 charts where the two projection spaces differ by more than 0.02 in
outcome, **the tool's flag picks the better-fitting space 7 times out of 7.** The
semantics are settled.

**What triggers the choice** is the chart's **timeframe**, not the size of the range.

> ⚠️ **Correction, 2026-08-03.** This section previously specified `(b/a) > 1.30` and
> claimed it reproduced the observed split. **It does not, and the claim was wrong when
> written.** Solving each chart's anchors gives overlapping classes — Log spans
> `b/a ∈ [1.156, 2.061]`, Linear spans `[1.015, 1.525]` — so **no single `b/a` threshold
> can separate them.** Direct counterexamples: WTI 18h is *Linear* at 1.525, while AU10Y
> 1W is *Log* at 1.333; USDJPY 1W is *Log* at just 1.156. Caught before implementation.

Sorting the same 14 charts by bar period separates them perfectly:

```
Linear:  1h, 1h, 2h, 2h, 4h, 4h, 8h, 18h          (n=8, max 18h)
Log:     3D, 3D, 1W, 1W, 1W, 1M                    (n=6, min 72h)
```

**14/14, with a clean empty gap between 18h and 3D.** This is not confounded with asset
class: FX appears on both sides, and — decisively — the *same instrument* flips with
timeframe. USDJPY is Linear on 4h and Log on 1W; USDKRW is Linear on 2h and Log on 1M.
An instrument cannot change its asset class between two charts, so period is the driver.

**[C] Our rule:** use Log when the bar period is **>= 1 day**, else Linear.

The 1-day boundary sits inside the observed gap `(18h, 72h]`, and nothing in the evidence
pins it more precisely than that interval — 1D is chosen as the conventional
intraday/swing boundary. The *rule* (period, not range) is recovered; only its exact
cut point is our choice. Do not tune it later.

---

## 3. Geometry constraints

### 3.1 Contraction **[V]**

```
fib(RH3) < fib(RH2) < 1.0
fib(RL3) > fib(RL2) > 0.0
```

13/13 after correcting one misread digit. Hunt states it as: each successive high must be
lower and each successive low must be higher **[D]**.

Observed ranges across the sample:

```
RH2 in [0.68, 0.98]    RL2 in [0.01, 0.49]
RH3 in [0.47, 0.85]    RL3 in [0.12, 0.55]
slung in [0.37, 0.68]
```

**[C]** Do **not** encode these ranges as filters. They are 13 observations of what Hunt
chose to screenshot — a selection-biased sample of setups he found worth posting, not a
validity envelope. Treating them as gates would bake his publication bias into the
detector.

### 3.2 The contraction-ratio trap

The retired detector advertised a 1.2× contraction requirement (`hvf_detector.py:225`)
but its `MIN_RRR >= 1.5` gate (`config.py:59`) silently implied, through its own target
and stop definitions:

```
RRR = (w1 - 0.5*w3) / (w3 + 0.5*ATR) >= 1.5   =>   w1 >= 2.0*w3 + 0.75*ATR
```

and since `ZIGZAG_ATR_MULTIPLIER = 2.0` forces every leg to at least ~2×ATR, this
resolved to **w1 >= ~2.4 × w3**. Stated rule and enforced rule differed by a factor of
two, and nothing in the code said so.

**[C] Rule for v2: never let a risk filter imply a geometry filter.** Compute geometry
first, admit the pattern, then apply RRR as a separate, logged, countable rejection with
its own counter. Every filter must be independently observable in the rejection stats.

---

## 4. Detection algorithm

### 4.1 Pivot detection **[I]**

The tool's own embedded backtest box (USDJPY 1W) reads:

```
Box Size 0.5%   winRate 38.89%   Trades 18   Source H/L   avgR 0.23   OpenPos 0
```

`Box Size` as a **percentage** and `Source H/L` together point to a **fixed-percentage
reversal ZigZag computed on highs and lows** (not closes, not a bar-count fractal). The
same charts carry a `Sniper PnF v2` overlay, which is the point-and-figure family the
"box size" vocabulary belongs to.

**[C] Our choice:** percentage-reversal ZigZag on H/L, threshold a free parameter with
0.5% as the starting point. `hvf_trader/detector/zigzag.py` is the right family of
algorithm and is sound — it already enforces H/L alternation — but it is
**ATR-adaptive**, whereas the tool appears to use a **fixed percentage**. Support both;
default to fixed-percentage to match the tool.

Consequence to respect: a percentage ZigZag never emits a pivot for the in-progress final
leg. RL3/RH3 is only confirmed once price has reversed by the box size from it. **The
detector must therefore treat the final pivot as provisional** — which is almost
certainly what the tool's `interim` states are about (§5).

> ✅ **CONFIRMED 2026-08-03 — but the box size is far more sensitive than assumed.**
> This rule was briefly and wrongly recorded here as falsified. The retraction is kept
> because the mistake is instructive about how the acceptance test must be run.
>
> The funnel's legs shrink monotonically by definition, so the usable box sizes are
> bounded on **both** sides, and the band between them can be narrow. On gold
> (2026-06-15..17) the legs run 1.47%, 1.14%, 0.96%, 0.84%, 0.74% of price while the
> largest noise retracement inside the funnel is 0.59%:
>
> * at **box 0.75%** the final leg (0.74%) is *below threshold*, so RH3/RL3 never emit;
> * at **box 0.50%** all six emit but two spurious pivots (fib 0.663, 0.273) land
>   between RL1 and RH2, so the six are not consecutive;
> * at **box 0.62–0.70%** the six emit *consecutively* and correctly.
>
> The working band here is only 0.60–0.74% wide. The first acceptance run swept
> `[..., 0.5, 0.75, ...]` and stepped straight over it, which produced a false negative
> on 7 of 8 charts. **Consequence, now mandatory: the box sweep must be geometric with a
> step no coarser than 1.15×, never a hand-picked list.** A second artefact compounded
> it — a search window truncated shortly after RL3 cannot confirm RL3, since a
> percentage ZigZag needs a `box`-sized reversal *away* from a pivot to emit it. Windows
> must extend past the structure by at least one full leg.

### 4.2 Prior-trend precondition **[D], thresholds [C]**

Mandatory and currently entirely missing from our codebase. Reject any structure whose
origin is choppy or trendless.

**[C]** Candidate implementations, to be chosen before any backtest is run:
- the leg into H1/L1 spans >= K × ATR over the preceding N bars; or
- a directional-movement or linear-regression-slope screen on the pre-H1 window; or
- H1 is the extreme of the last M bars.

Prefer the simplest that can be stated in one line. **Do not** use ADX: the retired
detector's `ADX_MIN_TREND = 15` gate was applied at the *funnel*, where a contracting
range mechanically produces a low ADX — the filter was anti-correlated with the thing it
was meant to select.

### 4.3 Search procedure **[C]**

```
1. Compute the ZigZag pivot series (H/L alternating).
2. For each candidate exhaustion pivot P (a high for longs, a low for shorts):
     a. Verify the prior-trend precondition on the window ending at P.       (4.2)
     b. Take the next 5 alternating pivots -> the 6-pivot candidate.
     c. Set a, b from the first two; compute all fibs.
     d. Test contraction.                                                    (3.1)
     e. Compute slung, entry, stop, target, RRR.                             (2.x)
     f. Emit; log every rejection with its reason.
3. Deduplicate overlapping candidates; prefer the one with the larger AMP1.  ⚠️ FALSIFIED
```

> ⚠️ **Step 3 is falsified — see §8.7.** "Prefer the larger AMP1" drops Hunt's own funnel
> on 2 of the 3 reproducing charts, taking recall from 3/3 to 1/3. Run with
> `detect_hvf(dedupe=False)` until a replacement tie-break is designed and tested.

Directionality falls out of step 2 — a candidate is a long **iff** it starts on a high
that ends an uptrend. There is no dual-sided test, and no window-parity ambiguity.

> ⚠️ **Step 2b is FALSIFIED — retracted 2026-08-03.** All six pivots are *not* adjacent
> in one ZigZag stream, and cannot be. The exhaustion leg and the funnel it precedes are
> **different degrees**, so no single box resolves both. USDJPY 4h, forced to its known
> window, shows this exactly:
>
> | box | stream |
> |---|---|
> | 0.4652% | `RL1 RH2 RL2 RH3 RL3` consecutive and exact — but `H1` is **5 pivots earlier**, the decline subdivided by 160.636 / 161.643 / 160.760 / 161.521 |
> | 0.7076% | `H1 RL1 RH2 RL2` consecutive and exact — but too coarse to ever emit `RH3`/`RL3` |
>
> Gold satisfied adjacency only because its decline happened to be one clean leg. That
> was luck, and I generalised from it twice (§4.1 then here).

**Replacement rule [I], parameter-free.** The four funnel pivots `RH2 RL2 RH3 RL3` must
follow `RL1` consecutively. `H1` is recovered separately as the swing extreme that
started the move into `RL1`: walk backwards from `RL1` keeping a running extreme of
same-kind pivots, and stop at the last one that improved it — the origin of the run of
lower highs (higher lows on the short side). This needs no second box size and **reduces
to the old adjacency rule** wherever the leg is a single clean swing, so gold and HYG are
unaffected (`gap = 1` for both). It is implemented in `hvf_v2_acceptance.anchor`, and is
**not yet ported into `detect_hvf`**, which still requires six consecutive pivots.

The sweep resolution in §4.1 remains part of the algorithm, not a test detail.

### 4.4 Box size is the one genuinely free parameter **[C]**

Everything else in §2 is pinned by the panel arithmetic. The box size is not, and §4.1
shows the admissible band can be as narrow as 0.60–0.74%. Two consequences:

* **It cannot be a global constant.** Gold needs ~0.65% at 2h; HYG matches at 0.75% on
  4h. A per-instrument, per-timeframe value is unavoidable.
* **It is therefore the main overfitting surface in the whole strategy**, and the only
  parameter a calibration/test split needs to protect. Hence §8.4.

---

## 5. Status state machine **[I] + [C]**

Observed strings: `funnelling`, `interim 1`, `interim 2`, `triggered`,
`funnelling / inner triggered`, `funnelling / inner stop loss`.

**Public sources say nothing about any of these.** They are tool strings, not doctrine.
Hunt does confirm the existence of *interim targets* — waypoints short of full amplitude
where a pullback is expected **[D]** — which is the one anchor we have.

**[C] Our state machine**, to be pre-committed:

```
FUNNELLING  6 pivots present, contraction holds, entry not yet touched.
            RH3/RL3 still provisional; levels may move as new pivots form.
ARMED       Pending stop order placed at the rail.
TRIGGERED   Entry filled.
TARGET      AMP1 reached.
STOPPED     Opposite rail taken out.
EXPIRED     Invalidated unfilled (§6).
```

`interim 1` / `interim 2` are **[I]** most likely interim-target waypoints between
TRIGGERED and TARGET. The `inner` prefix is **[I]** most likely a nested HVF forming
inside the outer funnel — consistent with both charts showing `inner` states also showing
the outer state as still `funnelling`, and with Hunt's documented multi-timeframe
practice where lower-timeframe funnels trigger first inside a higher-timeframe one.

**We are not obliged to reproduce these.** The above six states are sufficient to trade
the pattern. Nested-HVF handling is explicitly out of scope for v1.

---

## 6. Invalidation **[C] — entirely our decision**

Research found **no published invalidation rule**: no apex rule, no bar-count expiry, no
close-back-inside rule. This is a genuine hole in the method as published, not a gap in
our search.

It also carries a methodological warning. Practitioners are documented retroactively
disqualifying losing setups as "not really HVFs" on discretionary grounds — "low time and
price symmetry", "highly-slung". That is a No-True-Scotsman structure, and it is exactly
how a pattern with no edge sustains the appearance of one.

**[C] Therefore every invalidation rule must be pre-committed, mechanical, and
evaluated on the losers as well as the winners.** Proposed:

- **Apex expiry.** Cancel unfilled if price reaches the trendline convergence point.
- **Bar expiry.** Cancel unfilled after N bars from RL3/RH3. (The retired detector used
  `PATTERN_EXPIRY_BARS = 100`, which combined with a 2×ATR ZigZag was arithmetically
  near-impossible to satisfy — six pivots rarely fit in 100 bars at that threshold. Set N
  from the observed pivot spacing, not by guess.)
- **Structural invalidation.** Cancel if price closes beyond the *opposite* anchor
  (below `a` for a long) before triggering.

No time-stop on open positions in v1. Hunt's exits are all-or-nothing to target or stop
**[D]**.

---

## 7. What the tool is actually worth

The embedded backtest box is the only performance number in the entire evidence base:

```
Box Size 0.5%   winRate 38.89%   Trades 18   avgR 0.23   OpenPos 0
```

Read it honestly: **18 trades cannot distinguish avgR 0.23 from zero.** This is not
evidence of edge. It is, however, a useful *shape* prior — a low win rate with positive
expectancy, i.e. a convex breakout payoff.

That shape is corroborated by Hunt's own framework. He uses "POUT" (probability of
outcome) and states plainly that *"17+ RRR's should by law of averages have very LOW
probabilities of outcome"* **[D]**. He publishes **no win rate anywhere**, and his site
carries explicit hindsight disclaimers. The only independent figure found was a single
anonymous blogger self-reporting ~60% WR at 1.5 R:R — unaudited, and not reconcilable
with the other two.

**Implication for us: a v2 detector showing a ~40% win rate is behaving as designed, not
failing.** The retired strategy's death certificate said "detector finds ~zero patterns",
which is a detection failure, not a performance verdict. Judge v2 on avgR and on trade
count, never on win rate.

### 7.1 Power requirement

Using the project's standard `N ≈ 7.85 × sd(R)² / avgR²` at the tool's `avgR = 0.23`:

| sd(R) | Closed trades needed |
|---|---|
| 1.5 | 334 |
| 2.0 | **594** |
| 2.5 | 927 |

For a 39%-WR breakout with a ~1:2.5 payoff, `sd(R)` of 1.5–2.5 is realistic. **Budget
roughly 300–900 closed trades before any claim of edge**, and divide by the fill rate to
get the calendar cost. This must be computed *before* committing to a validation plan —
if the achievable sample is 40 trades, the honest answer is that the study cannot be run
on that instrument.

---

## 8. Backtest contract

A new strategy must satisfy the project's documented honesty constraints. The full
checklist lives in `CLAUDE.md`; the ones that bite hardest here:

1. **Copy `simulate()` from `scripts/asb_fill_audit.py:91-255` verbatim.** Do not
   re-derive a fill model. Pin a known-good incumbent row and hard-abort on drift.
2. **Blind-gap fills.** Print the fraction of trades whose first fill-window bar *opens*
   beyond the level. HVF entries are stop orders at a rail that price is accelerating
   through — this is precisely the geometry where gap fills bite. Fill gaps at the bar
   **open**, not the level (`asb_fill_audit.py:193,196`); derive SL/TP/risk from the
   *level*, matching live.
3. **Placeability.** A pending stop already through the market is rejected outright
   (retcode 10015). Model per-leg placeability.
4. **Overnight financing.** HVF on 3D/1W/1M holds for weeks to months. **No existing
   hvf backtest models financing**; `simulate()` charges one round-trip at entry and
   nothing per night. Reuse `swap_fn` from `scripts/donchian_financing_rescore.py:433-483`
   — it reads `swap_mode` per instrument and normalises to an annual rate on notional,
   which is mandatory (a fixed-amount assumption inflated USTEC 5×). **This is
   non-negotiable for high-timeframe HVF and is the single most likely source of a
   fictitious edge.**
5. **Value per point** from `trade_tick_value / trade_tick_size`, never assumed. Check
   `vol_min × stop_dist × dpp <= equity × risk_pct` before adding an instrument, or the
   strategy is a silent no-op that looks deployed.
6. **Pre-commit a held-out test leg** before looking at any result.
7. **Judge on the floored-spread column**; for long histories use `cost_mode "atrfrac"`.

### 8.1 Data availability

There is no shared loader; the audited scripts read live MT5 on the VPS rather than
`backtests/data/`. Long H1 history exists only where it matters most for this pattern:

| Instrument | H1 coverage |
|---|---|
| XAUUSD | 1998-04-22 → 2026-06-02 (66,241 bars) |
| XAGUSD | 2002-09-15 → 2026-06-02 |
| Indices (DE40/JP225/UK100/US500) | 2012-08 → 2026-06 |
| FX majors | 2018-04-02 → 2026-04-16 |
| BTCUSD | 2017-05-09 → 2026-06-01 |

Four H1 FX files (GBPAUD, GBPCAD, GBPCHF, GBPNZD) have a corrupt `time` column (literally
`1` on every row) and are unusable as-is.

**Note the mismatch with the evidence base:** Hunt's charts are dominated by sovereign
bond *yields*, which we cannot trade and do not have. The tradable overlap is metals, FX,
crypto, energy and index CFDs. Gold H1 back to 1998 is the strongest available substrate
and should be the primary study.

### 8.2 Acceptance-test data — pulled 2026-08-03, `backtests/data/hvf_v2/`

The instruments Hunt charted were pulled fresh from IC via MT5 on the VPS. They live in
their own directory and **nothing in `backtests/data/` was overwritten** — several screens
pin exact PF/N against those files, and the fresh pull is bar-for-bar identical on the
overlap anyway, so swapping them would risk reproducibility for no gain.

| File | Bars | Coverage | Serves |
|---|---|---|---|
| `XAUUSD_H1` | 66,798 | 2000-01-03 → 2026-08-03 | Gold CFD 2h; XAU/XAG 8h |
| `XAGUSD_H1` | 64,529 | 2002-09-15 → 2026-08-03 | XAU/XAG 8h denominator |
| `BTCUSD_H1` | 73,588 | 2011-03-24 → 2026-08-03 | BTCUSD 1h |
| `USDJPY_H1` | 100,000 | 2010-06-25 → 2026-08-03 | USDJPY 4h |
| `USDJPY_W1` | 2,899 | 1971-01-03 → 2026-08-02 | USDJPY 1W |
| `XTIUSD_H1` | 59,584 | 2016-06-30 → 2026-08-03 | WTI 18h **(SHORT)** |
| `XAUEUR_H1` | 63,168 | 2012-09-24 → 2026-08-03 | XAUEUR 1h **(SHORT)** |
| `HYG_NYSE_H1` | 909 | 2026-01-26 → 2026-07-31 | HYG 4h **(SHORT)** — marginal |

D1 companions were pulled for each; `USDJPY_H1` is capped at exactly 100,000 bars by the
terminal, not truncated by error.

**Reachable acceptance sample: 8 of the 13 validated charts** (was 3 before this pull),
including 3 of the 4 shorts and both projection modes. `HYG_NYSE_H1` holds only six months
of history, which may not span its funnel — treat it as a bonus, not a required pass.

**The other 5 are permanently unreachable, and this is a data fact, not a gap to close
later.** Four are sovereign bond yields (AU10Y, US5Y, US20Y, US30Y) and two are USDKRW;
IC lists no yield instrument (`US10`, `TNOTE`, `BUND` all absent) and no KRW pair at all.
Since 4 of the 5 unreachable charts are Log-projection rows, the acceptance test is
**weighted towards Linear** and will exercise the log target formula on only USDJPY 1W.

Two integrity findings from the pull, both worth keeping:
- Continuity against the existing repo files is **exact** — 65,800 of 65,801 overlapping
  XAUUSD H1 bars match to 1e-9, and the single exception is the old file's final,
  partially-formed bar. Same for XAGUSD and BTCUSD. The feed has not been revised.
- IC's BTCUSD feed carries **`low = 0.0`** on 2018-03-17 (H1 *and* D1). Repaired to
  `min(open, close)`. This is not cosmetic: left alone, a zero low is a ~100% spike that a
  percentage-reversal ZigZag would latch onto as the dominant pivot of the decade. **Any
  new instrument must be screened for this before use** — the check belongs in the loader.

---

### 8.3 Acceptance run, 2026-08-03 — three method defects found, all in the test

The first run returned **1 of 8**. That number was an artefact of the test, not a
property of the strategy, and all three defects were in the harness:

**Defect 1 — the box sweep stepped over the answer.** `BOX_SIZES` was a hand-picked list
jumping 0.5 → 0.75, and gold's admissible band is 0.60–0.74. Fixed per §4.1: geometric
sweep, step ≤ 1.15×.

**Defect 2 — search windows were truncated at the structure.** A percentage ZigZag emits
a pivot only after a `box`-sized reversal away from it, so a window ending near RL3
cannot contain RL3. Windows must extend at least one full leg past the structure.

**Defect 3 — the scoring metric, described below.**

The formula pins (`scripts/hvf_v2_formula_pins.py`) pass throughout, so the arithmetic
was never in question.

Two flaws in scoring had to be fixed before the result meant anything, and both had
inflated it:

1. **Error was normalised by price.** Gold's entire funnel spans 1.50% of price, so *any*
   six pivots inside it score under 1.50% automatically — the metric was measuring how
   narrow the structure is, not how well it was found. Gold "matched" at 0.181% even at a
   box size emitting 344 pivots across 330 bars. Corrected to **fib units**, where the
   panel's own 2dp printing sets the natural tolerance (~0.02).
2. **Nothing constrained the candidate's scale.** A 6-pivot window at any amplitude
   scores well once divided by its own range. The found range is now required to be
   within 25% of the reference.

**The decisive anchor: the charts are dated.** The filenames in `charts/` are epoch-
millisecond timestamps, and they run **2026-03-12 to 2026-07-31**. Every setup is
therefore from the last five months. That retrospectively voids most of what the
unrestricted search had been returning — USDJPY 4h "matched" at 2016-02-11, USDJPY 1W at
1998, XAU/XAG at 2020, WTI at 2022, BTCUSD at 2024. Those were the **null distribution**
of the search, and it sits at 0.03–0.05 fib. HYG's 0.0033 is an order of magnitude below
it, which is why HYG is a real detection and the rest were not.

Re-running restricted to 2026 makes the scores **worse** (USDJPY 4h 0.036 → 0.079,
XAU/XAG → 0.205, USDJPY 1W cannot form), confirming the coincidence reading.

**Why HYG was the one that passed:** it is not that our HYG data is better. `HYG_NYSE_H1`
holds 909 bars against 60–100k for the others, so its search space is ~70× smaller and
offers far less opportunity for coincidence. This is a caution about the whole exercise —
a shape search over 26 years of H1 finds funnel-like structures constantly. Containment
counts make the point: for a band of exactly the reference width, BTCUSD has **35**
qualifying windows, XAU/XAG 19, WTI 17, XAUEUR 10. Shape alone is not diagnostic;
date anchoring is what makes the test decisive.

**Gold is present and is almost certainly Hunt's actual setup.** At 2026-06-15..17, box
0.5%, all six pivots appear in correct order with every fib within 0.01 of the panel and
the entry within **0.002%** of the printed 4349.762:

| pivot | panel fib | found fib | price | timestamp |
|---|---|---|---|---|
| H1 | 1.00 | 0.995 | 4369.62 | 06-15 16:00 |
| RL1 | 0.00 | 0.016 | 4305.94 | 06-16 00:00 |
| RH2 | 0.78 | 0.770 | 4354.95 | 06-16 14:00 |
| RL2 | 0.12 | 0.130 | 4313.33 | 06-16 16:00 |
| RH3 | 0.69 | 0.688 | 4349.66 | 06-17 04:00 |
| RL3 | 0.19 | 0.191 | 4317.29 | 06-17 10:00 |

The date is consistent with charts posted 2026-06-17 and 2026-06-23. At box 0.62–0.70,
offset 0, these six are emitted **consecutively**, so the detector reproduces the setup
exactly once the sweep is fine enough to find the band.

### 8.4 Calibration / test split — **pre-committed 2026-08-03, before the re-run**

Box size is the only free parameter (§4.4), so it is the only thing a split needs to
protect. Recorded here *before* the fine-grid acceptance run, and not to be revised
afterwards.

**Held out as test (2):** `BTCUSD 1h`, `XAUEUR 1h`.
**Calibration (6):** `GoldCFD 2h`, `XAU/XAG 8h`, `USDJPY 4h`, `USDJPY 1W`, `WTI 18h`,
`HYG 4h`.

Reasoning, so the choice can be audited rather than trusted:

* **Gold and HYG had to go in calibration — they are already contaminated.** Gold's
  pivots were dumped and inspected in detail while diagnosing the box-band problem, and
  HYG was the single pass used to sanity-check the pipeline. Neither can serve as a
  blind test any more, whatever we would prefer.
* **Both test charts are native 1h**, so neither carries a resampling or session-anchor
  confound. If they fail, the failure is attributable to the detector rather than to our
  reconstruction of a period Hunt's platform builds differently. XAU/XAG (a synthetic
  ratio) and WTI 18h are the opposite case and belong in calibration, where a failure can
  be investigated freely.
* **One long, one short**, so the direction mirror is exercised blind.
* The test set has **no Log-projection chart** — unavoidable, since USDJPY 1W is the only
  reachable one. This costs nothing here: projection mode is pinned data-free by the
  formula pins at 14/14 and is not what this test exercises.

**Pass criterion, also pre-committed:** mean |fib error| over the four interior pivots
≤ **0.02** (the panel's own 2dp precision), with found AMP1 within 25% of reference and
the matched window inside the charts' posting range (2026-03-12 .. 2026-07-31).

**Negative control, mandatory before the result is believed:** the null distribution of
this search measured at 0.03–0.05 fib on the *unrestricted* run. It must be re-measured
under the final settings — a sweep this fine may lower the floor, and a pass is only
meaningful if it sits well below whatever the floor turns out to be.

### 8.5 Result of the corrected run — **step 3 does not pass**

| chart | set | box% | fib err | null | verdict |
|---|---|---|---|---|---|
| GoldCFD 2h | calib | 0.615 | **0.0074** | 0.041 | MATCH |
| HYG 4h | calib | 0.708 | **0.0033** | — | MATCH |
| XAU/XAG 8h | calib | 4.354 | 0.0779 | 0.086 | MISS |
| USDJPY 4h | calib | 0.306 | 0.0792 | 0.029 | MISS |
| USDJPY 1W | calib | — | — | 0.124 | no 2026 window |
| WTI 18h | calib | 0.201 | 0.1670 | — | MISS |
| BTCUSD 1h | **TEST** | 1.076 | 0.0281 | 0.046 | near |
| XAUEUR 1h | **TEST** | 0.100 | 0.0490 | 0.047 | near |

**Calibration 2/6. Held-out test 0/2.** Negative control: best pre-2026 score 0.0287,
median 0.0458.

Reading it honestly:

* **Gold and HYG are genuine detections.** Gold at 0.0074 is 4× below the best null and
  ~6× below the median; HYG at 0.0033 likewise. Gold's window (2026-06-15..17) matches
  charts posted 06-17 and 06-23. These are real reproductions of Hunt's setups.
* **Both held-out charts fail, and fail *at the noise floor*.** BTCUSD's 0.0281 sits
  essentially on the best null (0.0287) and XAUEUR's 0.0490 is above the median null
  (0.0458). Neither is distinguishable from coincidence. The pre-committed split did
  exactly its job: the two charts nobody had looked at returned nothing.
* **USDJPY 4h scores 0.0792 live against its own null of 0.029** — the 2026 window is
  *worse* than chance. That pattern points at the structure genuinely not being in our
  USDJPY series (feed or period reconstruction), rather than at a detector failure.
* Stage B adds a separate concern: at gold's matching box the detector emits 8–81
  patterns depending on the prior-trend test, and the true one is emitted under only two
  of six variants. HYG emits exactly 1 under all six. Selectivity is not yet established.

**Conclusion: 2 of 8 charts reproduce, both in calibration, neither in test.** Steps 4–5
(performance, power) remain blocked. The evidence does not currently support the claim
that this detector finds Hunt's funnels in general — it supports the weaker claim that it
finds some of them.

### 8.6 Anchor-rule fix and the blind run — **step 3 still does not pass**

Debugged against USDJPY 4h only (its true window was known from the feed test), then the
held-out pair was run **once**, blind, with no inspection or tuning. Fix is §4.3's
replacement rule.

| chart | set | box% | fib err | AMP1 err | gap | verdict | own null | window |
|---|---|---|---|---|---|---|---|---|
| GoldCFD 2h | calib | 0.6153 | 0.0074 | 2.1% | 1 | **MATCH** | 0.033 | 2026-06-15..06-17 |
| BTCUSD 1h | **TEST** | 1.0761 | 0.0281 | 20.2% | 1 | near | 0.027 | 2026-01-09..01-12 |
| XAU/XAG 8h | calib | 2.8625 | 0.0779 | 20.8% | 7 | MISS | 0.078 | 2026-02-06..02-13 |
| USDJPY 4h | calib | 0.4652 | **0.0058** | 0.3% | 5 | **MATCH** | 0.028 | 2026-07-01..07-14 |
| USDJPY 1W | calib | 3.2919 | 0.3403 | 23.3% | 7 | MISS | 0.082 | 2025-01-05..2026-01-25 |
| WTI 18h | calib | 0.1 | 0.1432 | 8.3% | 11 | MISS | 0.131 | 2026-02-26..03-13 |
| XAUEUR 1h | **TEST** | 0.1 | 0.0490 | 9.1% | 1 | near | 0.047 | 2026-02-05 |
| HYG 4h | calib | 0.7076 | 0.0033 | 1.3% | 1 | **MATCH** | — | 2026-03-27..06-15 |

```
CALIBRATION     3 matched, 0 near, 3 missed  (of 6)
HELD-OUT TEST   0 matched, 2 near, 0 missed  (of 2)
```

**What the fix bought.** USDJPY 4h went 0.0792 → **0.0058** fib and moved from a spurious
2026-04-17 window to its true 2026-07-01..07-14 one, with AMP1 error 16.7% → 0.3%. Gold
and HYG were unchanged. Of the three calibration charts whose prices are verifiably in
our feed, **3 of 3 now reproduce.** The three misses are the three the feed test showed
have no 2026 price chain — they are data problems and no detector work will recover them.

**What it did not buy — and this is the result that matters.** The held-out pair is
unchanged: both still land on the wrong window (their true ones are 2026-03-10..12 and
2026-04-13..27), both at `gap = 1`, so the anchor rule never engaged. Worse, **both live
scores sit at their own noise floors** — BTCUSD 0.0281 against a null of 0.0273, XAUEUR
0.0490 against 0.0472. On the held-out set the search finds nothing distinguishable from
coincidence. XAUEUR also selects the grid floor (0.1%), a boundary artefact.

So the fix is real but did not generalise, and there is still **no blind evidence**. The
split did its job: had USDJPY 4h been debugged and then counted, this would have looked
like progress.

**Also unresolved (Stage B).** USDJPY 4h is emitted by `detect_hvf` under none of the six
prior-trend variants, because the anchor rule is not yet ported into it. Gold is emitted
under 2 of 6, at 8–81 patterns per run. Only HYG emits exactly 1 under all six.
Selectivity is still not established.

### 8.7 Selectivity — measured 2026-08-03, `scripts/hvf_v2_selectivity.py`

Acceptance measures **recall**. Nothing measured **precision**, and precision decides
whether this is a strategy: a detector that finds Hunt's funnel *and eighty others* is a
haystack. Measured on the three reproducing charts, at the box that reproduces Hunt's own
setup (§8.6) — conditions maximally favourable to the detector. Benchmark: Hunt posted
**one setup per instrument/timeframe pair over ~4.6 months ≈ 0.2/month**.

Emissions per month over 2026, and whether Hunt's own funnel is among them:

| prior-trend gate | gold /mo | gold true? | USDJPY /mo | true? | HYG /mo | true? |
|---|---|---|---|---|---|---|
| none (geometry only) | 3.4 | ✅ | 0.4 | ✅ | 0.2 | ✅ |
| **extreme_of_m(50)** | **1.1** | ✅ | **0.4** | ✅ | **0.2** | ✅ |
| extreme_of_m(100) | 0.9 | ❌ | 0.4 | ✅ | 0.2 | ✅ |
| atr_span(4,100) | 2.9 | ✅ | 0.4 | ✅ | 0.2 | ✅ |
| atr_span(3,50) | 3.0 | ✅ | 0.4 | ✅ | 0.2 | ✅ |
| slope(100,0.5) | 0.9 | ❌ | 0.3 | ✅ | 0.2 | ✅ |
| slope(50,0.3) | 1.3 | ❌ | 0.4 | ✅ | 0.2 | ✅ |

**The haystack fear is not confirmed.** At `extreme_of_m(50)` the detector achieves
**3/3 recall at 1.1 / 0.4 / 0.2 emissions per month** — gold ~5× Hunt's rate, the other
two at it. That is a tradeable candidate count, not a haystack. §4.2's open [C] choice is
hereby decided on evidence: **`extreme_of_m(50)`**, the only gate that keeps all three
true funnels while tightening gold over geometry-only.

> ⚠️ **`_dedupe` destroys true positives.** Every figure above is measured with dedupe
> **off**. With it on, gold and USDJPY 4h both lose Hunt's funnel to an overlapping
> larger-AMP1 candidate — 3/3 recall collapses to 1/3. The symptom that exposed it was
> impossible otherwise: *removing* the prior-trend gate made recall go **down**, which no
> filter can do. §4.3 step 3's "prefer the larger AMP1" tie-break is a [C] choice with no
> evidence behind it and must be replaced. `detect_hvf(dedupe=False)` now exists;
> `dedupe=True` remains the default only so the change is made deliberately.

**Two honest caveats.**

* **HYG's perfect selectivity is partly trivial.** A 0.7076% box on a low-volatility bond
  ETF starves the ZigZag — only ~12 candidates exist in total, so "exactly 1 emission" is
  as much a statement about the box as about the geometry.
* **The box was chosen knowing the answer.** Every number here is conditional on the
  reproducing box. The deployment question — can the box be chosen *without* seeing the
  setup — is untested and is now the largest remaining gap.

**Also corrected:** the earlier `min_rrr = 2.0` floor was not a fair filter. Hunt's own
gold setup carries **RRR 1.47**, so a 2.0 floor rejects one of his three. The observed
floor is 1.4.

### 8.7a Dedupe resolved — the span, not the tie-break

The §8.7 warning is discharged. The fault was the **overlap span**, introduced by the
anchor port: `H1` is reached by a backwards walk that can start 5 pivots before the
funnel, so including it in the span made unrelated candidates appear to overlap and
evicted true ones. Judging overlap on the **funnel span `RL1..RL3`** restores 3/3.

| dedupe variant | recall | gold /mo | USDJPY /mo | HYG /mo |
|---|---|---|---|---|
| none | 3/3 | 1.1 | 0.4 | 0.2 |
| full span, larger AMP1 *(old)* | **1/3** | 1.0 | 0.3 | 0.2 |
| **funnel span, larger AMP1** | **3/3** | 1.0 | 0.4 | 0.2 |
| funnel span, earliest | 3/3 | 1.0 | 0.4 | 0.2 |
| funnel span, tightest final | 3/3 | 1.0 | 0.4 | 0.2 |

The last three are **identical** on all three charts, so there is nothing to choose
between the tie-breaks on this evidence and "larger AMP1" is kept unchanged. Choosing
among them on n=3 would have been fitting, not deciding. Confirmed end-to-end: USDJPY 4h
is now emitted by `detect_hvf` under all six prior-trend variants (previously 0 of 6).

### 8.8 Box selection — **clean negative**, `scripts/hvf_v2_boxrule.py`

Everything above is conditional on the box that reproduces Hunt's own funnel, found by
sweeping against a known answer. Live there is no answer to sweep against. The obvious
candidate rule is `box = k × volatility` for one `k`, measured over 100 bars **ending at
H1** so it uses only information available at the time.

| ratio box/vol | median bar range% | mean bar range% | ATR14% | stdev log-ret% |
|---|---|---|---|---|
| GoldCFD 2h | 0.964 | 0.833 | 0.673 | 1.187 |
| USDJPY 4h | 4.393 | 3.348 | 3.437 | 5.043 |
| HYG 4h | 4.196 | 3.285 | 1.737 | 3.593 |
| **spread (max/min)** | **4.56** | **4.02** | **5.11** | **4.25** |

**No `k` exists.** A usable rule needs spread near 1.0; §4.1 measured gold's admissible
band at 0.60–0.74%, roughly ±10%. Applying the tightest rule (`3.285 × mean bar range%`)
reproduces 1 of 3 and puts gold's box **294% off**. USDJPY and HYG cluster tightly at
~3.3× — gold alone is the outlier at 0.83×, i.e. its reproducing box is *smaller than one
bar's mean range*, which is itself suspicious and worth revisiting.

**What it costs to sweep instead.** With no rule, all 28 boxes must run and their
emissions merged (collapsing funnels that overlap in time into one opportunity):

| chart | 1 box /mo | swept /mo | distinct /mo | inflation | true funnel found? |
|---|---|---|---|---|---|
| GoldCFD 2h | 1.0 | 28.3 | **5.0** | 5.0× | ✅ |
| USDJPY 4h | 0.4 | 3.6 | **1.7** | 4.0× | ✅ |
| HYG 4h | 0.2 | 2.0 | **0.5** | 3.0× | ✅ |

**This is the deployable number: 0.5–5.0 distinct setups per instrument per month, at
3/3 recall.** It is 2.5–25× Hunt's posting rate, but it is *not* a haystack — it is a
perfectly tradeable volume for a bot. Sweeping is a viable answer to the box problem;
the price is a 3–5× inflation in candidates, not a collapse.

**Consequence for the precision question.** Against the benchmark "Hunt would have posted
this", precision is ~1/25 to ~1/2.5. But Hunt posts a *curated* subset, so that benchmark
is unsound in the direction that matters, and no amount of chart data will fix it. The
question can only be settled by **whether the emitted funnels make money** — step 4. That
step is now genuinely unblocked, and it is the right next one.

### 8.9 Step 4 pre-commitments — **written 2026-08-03, before any result was seen**

§6 left invalidation entirely to us and §8 item 6 requires a pre-committed test leg. Both
are fixed here, in advance, so they cannot be revised to suit an outcome.

**Lookahead.** `Pivot.confirm` now records the bar at which a pivot became *knowable* —
the bar where price had reversed `box_pct` away from it — as distinct from `index`, where
the extreme printed. **Every simulation arms on `confirm` of the final pivot, never on
`index`.** The gap between them is pure lookahead and is the most likely way this
strategy fabricates an edge: `RH3`/`RL3` simply are not knowable when they print.

| rule | pre-committed choice |
|---|---|
| Arm | at `RL3.confirm`, with entry/stop/target frozen at that bar |
| Placeability | a stop order already through the market is **rejected** (MT5 retcode 10015); counted, never silently filled |
| Pre-fill invalidation | stop rail touched before entry → `EXPIRED` |
| Unfilled expiry | funnel's own duration in bars (`RL1`→`RL3`); scale-free, no new parameter |
| Stop and target in one bar | **stop wins** (conservative) |
| Gap fills | at the bar **open**, not the level; SL/TP/risk derived from the *level* (`asb_fill_audit.py:193,196`) |
| Costs | per-bar `spread` column, floored; judged on the costed column |
| **Held-out leg** | **train ≤ 2019-12-31, test ≥ 2020-01-01** |

**Deviations from the §8 contract, declared up front rather than discovered later:**

* **Item 1 (copy `simulate()` verbatim) cannot be honoured.** That function is built
  around M15 bars, Asian-session windows and daily grouping; HVF holds for weeks on
  arbitrary timeframes. Its *fill semantics* are reused line-for-line instead, and this
  deviation is the reason the result below is provisional rather than final.
* **Item 4 (financing via `swap_fn`) is NOT MODELLED.** `swap_fn` requires
  `MetaTrader5.symbol_info`, and MT5 is Windows-only — unavailable on this machine. The
  spec calls financing "the single most likely source of a fictitious edge" for
  high-timeframe HVF, so **any result on multi-week holds is unsafe until this is run on
  Windows.** Median hold time is reported so the size of the exposure is visible.

### 8.10 Step 4 result — **a small positive expectancy that is not statistically established**

`scripts/hvf_v2_backtest.py`, 5,367 funnels over 6 instruments, 2000-04-10..2026-07-31,
box sweep as §8.8 requires, gate `extreme_of_m(50)`, armed on `Pivot.confirm`.

**Most emitted funnels never become trades:**

| outcome | share | meaning |
|---|---|---|
| `EXPIRED_BROKE` | 32.3% | stop rail taken out before entry |
| `UNPLACEABLE` | **29.0%** | price already through the entry rail when the funnel became knowable |
| `STOP` | 26.4% | |
| `TARGET` | 10.1% | |
| `EXPIRED_UNFILLED` | 2.0% | |

Fill rate **36.5%**. The 29% unplaceable rate is a direct structural cost of the
confirmation lag, and it is not neutral — those are disproportionately the fast breakouts
that would have been winners.

**Performance, 1,960 closed trades, WR 27.6%, sd(R) 2.04:**

| cost (× ATR14) | leg | n | avgR | 95% CI | verdict |
|---|---|---|---|---|---|
| 0.00 | ALL | 1960 | +0.105 | [+0.015, +0.195] | significant, but zero cost is fiction |
| **0.05** | **ALL** | **1960** | **+0.059** | **[−0.031, +0.149]** | **not distinguishable from zero** |
| 0.05 | TEST | 1227 | +0.040 | [−0.074, +0.154] | not distinguishable from zero |
| 0.10 | ALL | 1960 | +0.013 | [−0.077, +0.103] | gone |

Per instrument @0.05: USDJPY 4h +0.143 (TEST **+0.457**), BTCUSD 1h +0.099, GoldCFD 2h
+0.038 (TEST −0.042), XAUEUR 1h −0.012, WTI 18h −0.245 (n=17). HYG produced **no trades
at all** — its single emission never became placeable.

**Verdict.** The sign is right and it survives the pre-committed train/test split without
collapsing, which is more than the retired strategy ever managed. But at a realistic cost
assumption the confidence interval spans zero, and **§7.1 power at the observed
`avgR = 0.059` and `sd = 2.04` demands N ≈ 9,300 closed trades; we have 1,960.** The
entire edge lives between a 5% and a 10% ATR cost. This is not a tradeable result — it is
a "not disproved" result, which is a different and much weaker thing.

**The honest reading:** step 4 does not show HVF works. It shows HVF is not obviously
broken once lookahead is removed, and that settling it needs either ~5× more trades or a
materially better entry. Given the 29% unplaceable rate, the most promising lever is the
entry mechanism, not more instruments.

**Caveats that could move this either way.** Financing is unmodelled (median hold is only
7 bars, so exposure is far smaller than §8 feared for these timeframes — but 3D/1W/1M
funnels, where Hunt also operates, were not tested and are where financing bites). The
cost model is an ATR fraction, not measured spreads: the per-bar `spread` column is
unusable here because ~50% of pre-2020 bars carry `spread = 0`, which would have turned
the train/test split into a pure cost artefact — an error this run made once before it
was caught.

### 8.11 Step 5 result — the entry lever is **falsified**, and the filters were the edge

§8.10 named the entry mechanism as the most promising lever, on the theory that the 62% of
funnels dying before they trade (29% `UNPLACEABLE` + 32% `EXPIRED_BROKE`) were
disproportionately the fast winners. `scripts/hvf_v2_entry_experiment.py` tests that
directly: same 5,367 funnels, same gate, same box sweep, four entry mechanisms, cost
0.05 × ATR14.

**Pre-committed before running: `avgR ≥ 0.13` AND the TEST leg must not collapse.**

| variant | fills | fill% | WR% | avgR | 95% CI | train | TEST | |
|---|---|---|---|---|---|---|---|---|
| A rail-stop (= §8.10) | 1960 | 36.5 | 27.6 | +0.056 | [−0.034, +0.145] | +0.084 | +0.039 | fail |
| B rail-stop, no pre-fill invalidation | 2693 | 50.2 | 24.2 | **−0.083** | [−0.156, −0.010] | −0.053 | −0.101 | fail |
| C market on confirmation | 5336 | 99.4 | 20.1 | **−0.120** | [−0.199, −0.042] | −0.094 | −0.136 | fail |
| D limit at funnel mid | 3542 | 66.1 | 13.5 | +0.060 | [−0.071, +0.191] | +0.156 | **+0.003** | fail |

A reproduces §8.10 to within 0.003 R (the residual is `atr[arm]` here vs `atr[fill_i]`
there) and its outcome mix matches exactly, so the harness is verified against the prior
run rather than being a fresh set of assumptions.

**No variant clears the threshold, and the two that attack the discarded funnels make
things actively worse — significantly so.**

* **C falsifies the §8.10 hypothesis outright.** Taking every `UNPLACEABLE` funnel at
  market is the worst variant on the board (−0.120, CI excludes zero). The funnels where
  price has already run through the rail are not missed breakouts; they are funnels that
  already spent their move. The confirmation lag is not costing us the winners.
* **B shows the pre-fill invalidation is a genuine filter**, not lost opportunity. Letting
  broken structures still trigger adds 733 fills and turns +0.056 into −0.083.
* **D is the multiple-comparison trap.** Nominally the best avgR, but WR collapses to 13.5%,
  sd(R) nearly doubles to 3.98, and train +0.156 → TEST +0.003. It is a worse-priced
  version of the same edge dressed up by four extra losing tails.

**Conclusion.** Both entry filters are *contributing* the edge, not suppressing it — which
means the small positive expectancy in §8.10 is close to the best this geometry produces,
not a floor to be improved on. Testing four variants and reporting the best is upward
biased, and even the biased best (`N` needed **34,382**, have 3,542) is further from
decidable than the baseline was.

**Status: HVF is retired on the evidence.** The pre-committed threshold was set because
§7.1 power says our fixed sample can only settle an edge at `avgR ≥ ~0.13`; nothing
reaches it, the trade supply is ~75/year, and the one lever we had a mechanism-level reason
to expect would help does the opposite. Reopening this needs a *new* hypothesis about where
edge lives, not another parameter of the ones already tested.

> ⚠️ **§8.11's retirement was premature and is withdrawn.** §8.12 supplies exactly the new
> structural hypothesis this paragraph demanded, and it invalidates the population every
> number in §8.10–8.11 was measured on. The entry findings themselves still stand — they
> are correct *about the funnels the current detector emits*.

### 8.12 The detector misses multi-degree funnels — proven on Hunt's USDJPY 1W

Checking the untested high timeframes turned up a defect that outranks everything in
§8.10–8.11. Three facts, in order.

**1. USDJPY 1W is not a data gap.** It was recorded as unreproducible for want of a 2026
price chain. That was wrong. The feed carries `USDJPY_W1` back to **1971**, and the levels
Hunt's panel solves to are all present: he needs `a = 140.147, b = 161.267`, and the feed
makes **161.951 in 2024**, **139.580 later that year**, and **163.987 in 2026** — the
funnel straddles 2024–26 and its target *was* hit.

**2. It is not an anchoring artefact either.** §11.1 warns that a `_W1` source is used
natively, so `native = c["src"].endswith("_W1")` forces `offsets = [None]` and the
week-start is never swept. Rebuilding weekly bars from D1 (7 week-starts) and from H1 (42)
moves the best score from **0.3403 → 0.3356 → 0.3287**. Forty-two anchors, no effect.

**3. Hunt's funnel is present, essentially exactly, and the detector cannot see it.**
At `box = 3.0%` all six pivots print:

| pivot | date | price | got fib | Hunt | err |
|---|---|---|---|---|---|
| H1 | 2024-06-28 | 161.951 | 1.000 | 1.00 | — |
| RL1 | 2024-09-13 | 139.580 | 0.000 | 0.00 | — |
| RH2 | 2025-01-10 | 158.880 | 0.863 | 0.86 | 0.003 |
| RL2 | 2025-04-18 | 139.886 | 0.014 | 0.01 | 0.004 |
| RH3 | 2025-08-01 | 150.917 | 0.507 | 0.51 | 0.003 |
| RL3 | 2025-09-12 | 145.485 | 0.264 | 0.26 | 0.004 |

**Mean |fib error| 0.0034**, against a null floor of 0.0820 and the detector's own best of
0.3287. AMP1 is 5.9% off reference. This is not a near-miss, it is the setup.

**Why it is missed: the pivot gaps are [7, 5, 5, 5, 1].** §4.3 retracted the
six-consecutive-pivots rule *only for the H1→RL1 leg* and replaced it with `_anchor_pivot`,
a backward walk to the exhaustion extreme. That was the right diagnosis applied too
narrowly. On the weekly chart **every leg is multi-degree**: four or five noise pivots sit
between each pair of funnel pivots, and RL2 is *lower* than the four lows around it, so no
monotone-contraction filter recovers it either. Each funnel pivot is the extreme of its own
sub-swing at a coarser degree than the box that must be used to make RH3/RL3 print at all.

**What this invalidates.** The 5,367 funnels behind §8.10–8.11 were all selected as
`anchor + 5 consecutive pivots`. That population is therefore biased toward funnels whose
interiors happen to be degenerate — the ones with no sub-structure — and Hunt's own
weekly setup is not in it. An `avgR` near zero over a population that provably excludes the
reference example is not evidence that HVF has no edge. **The performance question is
reopened, not answered.**

**Honesty about this result.** n = 1, and the six pivots were picked by eye from a printed
pivot list *after* seeing Hunt's fibs. That proves the structure **exists and is
expressible**; it proves nothing about **findability**. The next step is to specify a
parameter-free multi-degree selection rule, then re-run §8.6 blind — it must recover
USDJPY 1W *and* keep the 3/3 that already pass, without inflating emissions past §8.7's
rates. Until that is done this is a defect report, not a working detector.

### 8.13 Target ladder — the AMP2 hypothesis is falsified, but distance helps

`scripts/hvf_v2_target_ladder.py`, same population and entry as §8.10, same stop, seven
rungs at `m × AMP1` (log projection where the period implies it), cost 0.05 × ATR14.

| m × AMP1 | n | WR% | avgR | 95% CI | train | TEST | N needed |
|---|---|---|---|---|---|---|---|
| 0.250 | 1817 | 66.7 | −0.004 | [−0.041, +0.033] | +0.017 | −0.016 | 322,024 |
| 0.375 | 1958 | 56.5 | +0.010 | [−0.037, +0.058] | +0.075 | −0.028 | 84,482 |
| 0.500 | 1963 | 46.5 | +0.013 | [−0.045, +0.070] | +0.045 | −0.007 | 84,950 |
| 0.750 | 1962 | 35.1 | +0.053 | [−0.023, +0.128] | +0.048 | +0.056 | 8,207 |
| **1.000** | 1960 | 27.6 | +0.059 | [−0.031, +0.149] | +0.091 | +0.040 | 9,316 |
| **1.500** | 1959 | 20.3 | **+0.140** | **[+0.022, +0.258]** | +0.226 | +0.088 | **2,863** |
| 2.000 | 1959 | 16.1 | +0.142 | [+0.007, +0.277] | +0.286 | +0.056 | 3,630 |

**§9.1's premise is refuted.** The dashed ray sits *nearer* than the solid one (0.58–0.77
range-units past the midpoint, i.e. `m < 1`), and every nearer rung is **worse** than the
current rule — monotonically, all the way down to `m = 0.25` where the edge is gone
entirely. Whatever the second ray is, taking it as the profit target destroys the edge.

**Distance helps instead, and `m = 1.5` clears the §8.11 pre-commitment** — `avgR 0.140 ≥
0.13`, CI excludes zero, TEST positive. Three reasons to hold that loosely:

* **TEST degrades badly**: train +0.226 → TEST +0.088. Not a collapse, and the sign holds,
  but TEST alone does *not* reach 0.13. This is a marginal pass on the letter of the
  pre-commitment, and should be reported as marginal rather than as a win.
* **The optimum is at the edge of the sweep** and the curve is still rising at 1.5. An
  interior peak would be evidence of a real trade-off; a boundary one usually means the
  swept parameter is proxying for something else.
* **"Further is better" is generic.** On a fat-tailed series, widening the target while
  holding the stop mechanically buys tail exposure. That is a property of prices, not of
  HVF geometry, and it would show up on random entries too — which is the control this run
  does not have.

The curve is smooth and monotone rather than a lone spike, so the seven comparisons are not
the main worry here. The population is: this inherits §8.12's defect in full.

---

### 8.14 Multi-degree rule — the MUTUAL-EXTREME condition, `scripts/hvf_v2_mef.py`

§8.12 demanded a parameter-free multi-degree selection rule that recovers USDJPY 1W,
keeps the existing matches, and does not inflate emissions past §8.7. The first two are
met, comprehensively. The third is not, and that is now the whole remaining problem.

**Two obvious repairs ruled out on paper first, on the weekly chart's own numbers.**

* *A ZigZag whose reversal threshold shrinks with the funnel.* To confirm RH3 = 0.51 the
  threshold must be ≤ 0.26 (the drop into RL3), but an earlier pullback inside the same leg
  is 0.31 (0.40 → 0.09) and confirms 0.40 as the high first. The admissible interval is
  empty. **[V]**
* *Hierarchical degree reduction* (repeatedly delete the smallest leg). The funnel's **last**
  leg is 0.26 while the noise legs inside it run to 0.41, so any reduction coarse enough to
  clear the noise deletes RH3 → RL3 first. **[V]**

Both fail the same way: they are **global** rules over leg amplitude, and a funnel's degree
is not globally monotone.

**The rule. [C], and it is the generalisation §8.12 diagnosed.** Each funnel pivot is the
extreme of the window its two neighbours define:

    RL1 = min low  between H1  and RH2        RL2 = min low  between RH2 and RH3
    RH2 = max high between RL1 and RL2        RH3 = max high between RL2 and RL3

plus the nesting already required (RH2 < H1, RL2 > RL1, RH3 < RH2, RL3 > RL2); mirrored for
shorts. This is `_anchor_pivot` — §4.3's accepted fix for the H1 → RL1 leg — applied to
**every** leg instead of one. No threshold, no degree index, no lookback. It is causal by
construction: every interior condition references pivots already in the past at arming
time, and the one live edge, RL3, is the running extreme since RH3, so a lower low simply
re-arms a later funnel.

Enumeration is bounded by "previous / next more-extreme same-kind pivot". Those walls and
the record runs between them are precomputed with monotonic stacks, so the search costs
O(candidates), not O(n) per step — the first version scanned and did not finish in 10 min.

**Two changes to the test, both forced by the rule, not chosen to suit it.**

1. *Liveness is counted in bars.* §8.3 defect 3 anchored matches in time with "ends in
   2026". That is a bar-count statement disguised as a date. Hunt posted these 2026-03 to
   2026-07 and USDJPY 1W's RL3 is 2025-09-12 — 25 **weeks** earlier, but only 25 **bars**,
   which on a 1h chart is a day. Bound is now `2026-01-01 − 30 × bar period`. For every
   chart of 18h or less this moves the line by at most a fortnight; only the weekly moves
   materially.
2. *The pass criterion is a rank, not a floor.* The old "best live beats best pre-2026"
   comparison breaks here. The rule emits ~200 live candidates against ~88,000 null ones on
   gold, and the minimum of 88,000 draws sits far below the minimum of 200 for arithmetic
   reasons alone — so a bare floor comparison penalises the live side by a per-chart factor.
   Reported instead: `k` = null candidates scoring at least as well as the best live one,
   and `E = ((k+1)/(N+1)) × n_live` = the expected number of coincidences that good.
   **Pre-committed at E < 0.05** before running anything past gold and BTC. Candidates are
   deduplicated by their six timestamps first: the MEF condition is scale-invariant, so the
   same funnel reappears at every box fine enough to print it (USDJPY 1W's at 26 of 28), and
   counting it 26 times would corrupt both sides of the rank.

**Result — 8 of 8, both held-out charts included.**

| chart | set | box% | anch | fib err | AMP1 | shape | live | null | k | E |
|---|---|---|---|---|---|---|---|---|---|---|
| GoldCFD 2h | calib | 0.1 | 0 | 0.0061 | 2.1% | MATCH | 210 | 88,437 | 0 | 0.002 |
| BTCUSD 1h | **TEST** | 0.1 | — | 0.0052 | 1.7% | MATCH | 3,981 | 135,188 | 0 | 0.029 |
| XAU/XAG 8h | calib | 0.1 | 3 | 0.0027 | 0.3% | MATCH | 4,415 | 213,383 | 0 | 0.021 |
| USDJPY 4h | calib | 0.1 | 0 | 0.0058 | 0.3% | MATCH | 1,123 | 72,414 | 0 | 0.016 |
| USDJPY 1W | calib | 0.1 | 0 | **0.0034** | 5.9% | MATCH | 476 | 17,564 | 0 | 0.027 |
| WTI 18h | calib | 1.08 | 15 | 0.0177 | 5.7% | MATCH | 3,364 | 103,218 | 0 | 0.033 |
| XAUEUR 1h | **TEST** | 0.1 | — | 0.0057 | 1.8% | MATCH | 1,420 | 135,716 | 0 | 0.010 |
| HYG 4h | calib | 0.1 | 0 | 0.0033 | 1.3% | MATCH | 388 | **0** | — | n/a |

Every fib coordinate agrees with the panel to 2dp, worst case 0.03 (WTI's RL3). **k = 0
everywhere**: across ~765,000 pre-window candidates, not one scored as well as the live
match on its own chart. §8.6's 3/3 becomes 8/8, and the two pre-committed held-out charts
(§8.4) passed blind.

HYG is not a failure — its feed starts 2026-01-26 (909 bars), entirely inside the live
window, so there is no null population to rank against. Undefined, and a feed limitation
of the kind already catalogued in §8.2.

**The box stops mattering — §8.8's negative is softened. [V]** Each chart matches over a
*plateau* of box sizes and then falls off a cliff, exactly as scale-invariance predicts.
Coarsest box still scoring MATCH: gold 0.71, BTC 1.88, XAU/XAG 3.29, USDJPY 4h 0.47,
USDJPY 1W 3.29, WTI 1.08, XAUEUR 0.94\*, HYG 0.94\* (\* sweep ran out of live candidates
rather than hitting a cliff). The reported "box 0.1%" for 7 of 8 is a tie-break artefact —
ties break to the first box swept — not a fit. §8.8 said no rule picks a box; the answer is
that under MEF the box mostly does not need picking, over a band often 30× wide. The one
conflict is WTI, which matches **only** at 1.08 while USDJPY 4h dies above 0.47, so a
single global box still does not cover all eight.

**The bad news — selectivity is worse, not better.** The acceptance search prunes on
`AMP_TOL`, i.e. on a range read off the chart being searched for. A live system has no such
number. Ungated distinct funnels per month, against §8.7's detector rates:

| box% | GoldCFD 2h | vs 1.1 | USDJPY 4h | vs 0.4 | HYG 4h | vs 0.2 |
|---|---|---|---|---|---|---|
| 0.1 | 44.7 | 41× | 50.3 | 126× | 6.5 | 33× |
| 0.5 | 14.9 | 14× | 9.4 | 24× | 0.3 | 2× |
| 1.0 | 5.3 | 5× | 1.6 | 4× | 0.2 | 1× |
| 2.0 | 1.2 | 1× | 0.3 | 1× | 0.0 | — |

Rates reach §8.7 only at box ≈ 2%, and USDJPY 4h's funnel is gone above 0.47%. At the
coarsest box that keeps all the intraday matches, the rule emits **10–25×** the old count.

⚠️ **Corrected 2026-08-04 — that table is not like for like, and it understated the
problem.** §8.7's benchmark rates were measured with the `extreme_of_m(50)` prior-trend
gate, **over 2026 only**, at the box that reproduces Hunt's setup. The row above is
ungated, over the whole feed, at boxes of our choosing — three differences at once, and
averaging 2000–2026 dilutes the emission-dense 2026 window badly. Re-measured under §8.7's
exact protocol (`scripts/hvf_v2_mef_gated.py`), gold emits **896.7/month** on geometry
alone against the detector's 1.1. The real gap was ~800×, not 10–25×. See §8.15.

**What this means. [V]** MEF is a **necessary** condition on Hunt's funnels and a very
strong one — it recovers all eight from a search that had previously found three. It is not
**sufficient**: it finds Hunt's setup among several thousand structural twins. Detection is
solved; **selection is not, and is now the binding constraint.** Nothing here yet licenses
re-running §8.10 — a population of 4,000 candidates per chart per year is not a strategy,
and running expectancy over it would repeat §8.12's error in the opposite direction.

**Lead for selection, with its blind check already run. [I]** Hunt's fib coordinates
cluster hard. Bands from the six calibration charts, tested against the two held-out ones:

| coord | calibration band (n=6) | BTCUSD 1h | XAUEUR 1h | holds? |
|---|---|---|---|---|
| RH2 | 0.77 – 0.94 | 0.84 | 0.82 | ✅ |
| RL2 | 0.01 – 0.34 | 0.08 | 0.09 | ✅ |
| RH3 | 0.47 – 0.85 | 0.65 | 0.63 | ✅ |
| RL3 | 0.19 – 0.47 | 0.14 | 0.12 | ❌ both below |

Three of four survived a genuine out-of-sample test; RL3's lower bound did not, and widens
to 0.12. `RH2 ≥ 0.77` in all eight is the sharpest of them. This is a *ranking* prior, not
a detection rule, and with n = 8 it is a lead rather than a result — but it is the obvious
next lever, and it must be measured on emission rate and on expectancy separately.

### 8.15 Selection — the missing constraint is **scale**, and ATR supplies it

§8.14 left selection as the binding problem. The diagnosis is now specific: **the MEF rule
is scale-free.** Funnels nest inside funnels, from three-bar wiggles to multi-year
structures, and every level satisfies the mutual-extreme condition *simultaneously*. That
is not a flaw in the condition — it is what a self-similar geometric rule does. It means
the rule can never select on its own, and no refinement of the geometry will fix it.

**First, referencing the funnel to the confirmed prior trend. [V]** §4.2's gate asks only
that H1 top a 50-bar window. Under §8.7's exact protocol (reproducing box, 2026 only),
`scripts/hvf_v2_mef_gated.py`:

| prior-trend gate | gold /mo | true? | USDJPY 4h /mo | true? | HYG 4h /mo | true? |
|---|---|---|---|---|---|---|
| none (geometry only) | 896.7 | ✅ | 16.2 | ✅ | 0.2 | ✅ |
| extreme_of_m(100) | 88.6 | ❌ | 6.3 | ✅ | 0.2 | ✅ |
| **extreme_of_m(50)** | **116.4** | ✅ | **6.8** | ✅ | **0.2** | ✅ |
| atr_span(k=4,n=100) | 692.3 | ✅ | 15.6 | ✅ | 0.2 | ✅ |
| slope(n=100,r²=0.5) | 388.3 | ❌ | 12.1 | ✅ | 0.2 | ✅ |
| *v8.7 detector* | *1.1* | ✅ | *0.4* | ✅ | *0.2* | ✅ |

`extreme_of_m(50)` remains the right choice (§8.7's decision survives) and it cuts gold ~8×.
It is nowhere near sufficient: 116 against 1.1. **A binary "is H1 a local extreme" test
cannot select, because it says nothing about how BIG the funnel should be.**

**Second, the shape ratios. [V] — three of four are unusable.** Measured on all eight
matched funnels (`scripts/hvf_v2_mef_trendref.py`), with the impulse into H1 defined
parameter-free and in the rule's own idiom (trend origin = extreme opposite pivot between
H1 and the previous pivot exceeding H1):

| chart | AMP1/trend | AMP1/ATR14 | funnel bars / trend bars |
|---|---|---|---|
| GoldCFD 2h | 0.184 | 1.9 | 0.61 |
| BTCUSD 1h *(TEST)* | 0.459 | 3.5 | 1.15 |
| XAU/XAG 8h | 0.579 | 4.3 | 8.08 |
| USDJPY 4h | 0.027 | 10.2 | 0.00 |
| USDJPY 1W | 0.259 | 8.5 | 0.10 |
| WTI 18h | 3.221 | 5.1 | 72.00 |
| XAUEUR 1h *(TEST)* | 0.531 | 4.1 | 1.52 |
| HYG 4h | 0.826 | 6.8 | 1.29 |

The calibration bands for `AMP1/trend` (120× wide) and the time ratio (29,000× wide) do
technically contain both held-out values, and that is worth **nothing** — a band that wide
contains anything, so "it holds out-of-sample" is a tautology, not a validation. Both are
wrecked by the same two rows: USDJPY 4h's trend spans 22,802 bars and WTI's spans 1, i.e.
**the parameter-free trend definition fails outright on 2 of 8 charts.** Trend-*referenced*
shape cannot be judged until that definition is repaired; it has not been ruled out, it has
not been tested.

**`AMP1/ATR14` at H1 is the exception, and it is the whole result.** Spread 1.9–10.2, only
**5.4×**, and it needs no trend definition at all. Applied as a band taken from the **six
calibration charts only** (`scripts/hvf_v2_mef_atrband.py`):

| chart | geometry | + extreme_of_m(50) | + ATR band 1.9–10.2 | Hunt kept? | total cut |
|---|---|---|---|---|---|
| GoldCFD 2h | 896.7 | 116.4 | **5.3** | ✅ | 169× |
| BTCUSD 1h *(TEST)* | 328.2 | 84.6 | **1.8** | ✅ | 182× |
| XAUEUR 1h *(TEST)* | 3269.7 | 1643.6 | **9.4** | ✅ | 348× |
| HYG 4h | 0.2 | 0.2 | **0.2** | ✅ | 1× |
| USDJPY 4h | 16.2 | 6.8 | **0.3** | ❌ | 54× |

Emissions fall by a further **20–170×** beyond the trend gate, landing within an order of
magnitude of §8.7's rates instead of two to three. Recall survives on 4 of 5 **including
both pre-committed held-out charts**, whose ratios (3.5 and 4.1) sit mid-band and did not
set it — that is a genuine blind check on recall.

**The one failure is the informative one.** USDJPY 4h loses its funnel, and its ratio is
10.2 — exactly the top edge of a band set by six observations. A band whose edge is defined
by a single chart will lose anything sitting on that edge, and here it did. Two things
follow: the band is a *scale prior*, not a hard filter, and it belongs in a ranking score
rather than a gate; and n = 6 is not enough to set its edges. (The ratio is also
box-dependent in practice — this run uses §8.6's reproducing box and anchor, not the box
§8.14's acceptance selected — so part of the USDJPY miss may be that, and it is untested.)

⚠️ **Every rate in this section is one direction only** — the searches pass Hunt's known `dir`. Both directions give gold **33.0/month**, not 5.3. See §8.16.

**Where this leaves the strategy. [V]** Detection is solved (§8.14, 8/8). Selection has
gone from *unsolved* to *tractable*: the binding constraint was scale, scale is measurable
without reference to Hunt, and two filters that are doctrine rather than fitting — prior
trend, and funnel height in volatility units — recover ~99.5% of the reduction needed.
The remaining gap is roughly 5× on gold. That is a candidate count a person could look at.

**Still not licensed:** re-running §8.10. The population is now plausible but the ATR band's
edges rest on n = 6, and the USDJPY 4h miss shows what that costs. Fix the trend definition,
turn the band into a rank rather than a gate, and only then re-measure expectancy.

### 8.16 Direction is not determined — and every §8.14–8.15 count is one-sided

**What the doctrine says.** §2.2 **[V]+[D]**, 13/13 charts: direction follows the *prior
trend into the exhaustion point*, never the shape of the funnel. That section calls it
"the single rule the old implementation lacked".

**What the code does.** `detect_hvf` line 378:

```python
# Direction is set by the prior trend into the exhaustion pivot, so it
# is decided here and never by window parity (spec 2.2 [V]+[D]).
direction: Direction = 1 if run[0].kind == "L" else -1
```

The comment asserts the opposite of what the line does: direction *is* set by window
parity. The prior-trend test is applied afterwards, at line 386, as a veto. So the real
design is **parity proposes, prior trend disposes** — strictly better than the retired
detector, which had no directional evidence anywhere, but it is not §2.2.

**What was never tested.** Every measurement in §8.14 and §8.15 passes `c["dir"]` — Hunt's
known answer — into `mef_candidates`. Direction determination has therefore never been
exercised at all. Measured now, both directions, 2026, reproducing box
(`scripts/hvf_v2_mef_direction.py`):

| chart | Hunt | stage | longs | shorts | both /mo | wrong-way |
|---|---|---|---|---|---|---|
| GoldCFD 2h | long | geometry | 6,304 | 108,037 | 16,264 | **94.5%** |
| | | + extreme_of_m(50) | 818 | 16,327 | 2,439 | **95.2%** |
| | | + ATR band | 37 | 195 | **33.0** | **84.1%** |
| USDJPY 4h | long | geometry | 114 | 5,658 | 821 | 98.0% |
| | | + ATR band | 2 | 6 | **1.1** | 75.0% |
| BTCUSD 1h | long | geometry | 2,307 | 47,736 | 7,118 | 95.4% |
| | | + ATR band | 13 | 38 | **7.3** | 74.5% |
| HYG 4h | short | + ATR band | 0 | 1 | **0.2** | 0.0% |

**Three consequences, in order of severity.**

1. **`extreme_of_m(50)` does not decide direction.** On gold it admits 818 longs *and*
   16,327 shorts over the same 2026 window. A test that passes both directions on the same
   data is a local-extreme test, not directional evidence. §8.7 chose it on emission count
   with direction held fixed, so that choice never bore on this question — it is not
   wrong, it is simply silent here.
2. **§8.15's rates are one-sided and roughly 6× optimistic.** Gold's headline `5.3/month`
   is longs only; both directions give **33.0/month** against §8.7's 1.1. The ATR band's
   20–170× cut is real and unaffected — it is measured within each direction — but the
   distance still to travel was understated.
3. **The geometry is grossly direction-asymmetric**, ~17:1 toward shorts on gold and
   ~21:1 on BTC, both in rising markets, before any gate. Whether that is real structure
   or a defect in the short-side mirror of `mef_candidates` is **unresolved**, and it must
   be settled before the wrong-way counts are interpreted: the four contraction conditions
   were checked by hand and read correctly, but no test exercises the mirror.

**This outranks the scale problem.** §8.15 concluded selection was "tractable, ~5× to go on
gold". With direction restored that is ~30×, and the dominant failure mode is no longer
*too many funnels* but *funnels pointing the wrong way*. The next work is to make §2.2
literal — derive direction from the prior trend and enumerate one direction per anchor
rather than both — and only then re-measure. §8.10 remains blocked.

### 8.17 Is HVF a with-main-trend pattern? **Not in Hunt's own sample** — clean negative

**The hypothesis, from the trader.** HVF is overwhelmingly a *continuation* pattern; it
rarely marks a trend change. Direction should therefore be read off the **larger
timescale** — if the chart has risen for the past year it is a long, if it has fallen it is
a short — adapting the window to months or weeks. A funnel against the main trend also
fights the fundamentals, and legitimising one needs a *second* pattern (head-and-shoulders
and the like) to price the risk, which we do not have implemented.

This is a strong, cheap, falsifiable claim, and it would solve §8.16 outright: unlike
`extreme_of_m(50)`, a signed net move is **exclusive** — its sign picks one side and
refuses the other by construction.

**Test 1 — the funnel's own timeframe** (`hvf_v2_mef_maintrend.py`), six exclusive rules
over 100–200 bars. Best recall **6/8** (close vs SMA100). Mis-specified, and rejected on
those grounds rather than on the score: 100 bars of 2h is eight days, which is not a main
trend.

**Test 2 — the daily series, calendar windows** (`hvf_v2_mef_maintrend_htf.py`). This is
the hypothesis as stated. Recall against the way Hunt actually traded each chart:

| rule | close vs SMA50 | vs SMA200 | net 3m | net 6m | **net 1y** | zigzag 5% | zigzag 10% |
|---|---|---|---|---|---|---|---|
| recall | 4/8 | 2/8 | 2/8 | 3/8 | **3/8** | 1/8 | 3/8 |

Prices verified individually rather than trusted in aggregate:

| chart | Hunt | H1/L1 date | price | −3m | −1y | 1y move | with 1y trend? |
|---|---|---|---|---|---|---|---|
| GoldCFD 2h | long | 2026-06-15 | 4309.03 | 4965.74 | 2677.37 | **+60.9%** | ✅ |
| BTCUSD 1h *(TEST)* | long | 2026-03-10 | 70224.08 | 92357.00 | 79386.21 | −11.5% | ❌ |
| XAU/XAG 8h | long | 2026-02-05 | 67.464 | 82.762 | 87.334 | −22.8% | ❌ |
| USDJPY 4h | long | 2026-07-01 | 162.598 | 156.362 | 154.770 | +5.1% | ✅ |
| USDJPY 1W | long | 2024-06-27 | 160.770 | 150.535 | 130.102 | +23.6% | ✅ |
| WTI 18h | short | 2026-03-10 | 86.550 | 61.110 | 74.330 | +16.4% | ❌ |
| XAUEUR 1h *(TEST)* | short | 2026-04-21 | 4018.85 | 3645.25 | 2464.10 | +63.1% | ❌ |
| HYG 4h | short | 2026-03-27 | 78.670 | — | — | — | no history |

**3 of 7 with the yearly trend, 4 against** — and the two against include *both*
pre-committed held-out charts. Shorter windows are no better: on the 3-month view it is
2 of 7. **On this evidence the hypothesis is falsified for Hunt's charted sample.** A
with-trend gate on any of these windows would reject the majority of the setups he posted.

**Gold is the one clean instance of the model, and it is instructive.** +60.9% on the year,
−13.2% over the quarter, Hunt long — buy the dip inside the main uptrend. That is the
pattern the hypothesis describes, and it appears once.

**Three honest limits on this negative.**

* **n = 7.** Hunt's posted charts are also plausibly a *biased* sample: a trader publishes
  the setups worth talking about, and a contrarian entry is more worth talking about than
  the fourth pullback in an obvious uptrend. This may say more about what gets posted than
  about what gets traded.
* **WTI's anchor is unreliable.** It was already the weakest match (fib 0.0177, at the pass
  boundary) and the chart where §8.15's trend definition degenerated to a 1-bar leg. Its
  L1 sits after a +41% three-month rally, which is not a downtrend terminus. Treat that
  row as unresolved, not as evidence.
* **This does not contradict §2.2.** §2.2's "prior trend into the exhaustion point" is the
  *local* leg one degree above the funnel, which is up-into-H1 for every long by
  construction. That is why it is true of all eight and also why it cannot select (§8.16).
  The main-trend hypothesis is a different, stronger claim, and it is the stronger one that
  fails.

**What to do with it instead. [C]** Do not gate on it — that discards Hunt's own examples.
The trader's own formulation already points at the right shape: a counter-trend funnel is
not *forbidden*, it is *expensive*, and needs corroboration we cannot yet supply. So carry
`with_main_trend` as a **feature, not a filter**, and settle it empirically: when §8.10 is
unblocked, report expectancy split by it. If with-trend funnels pay and counter-trend ones
do not, the gate earns its place on our data rather than on doctrine — and if they pay
equally, we learn that HVF genuinely is direction-agnostic once the geometry is right.

### 8.18 The short skew is **real, trend-driven and mechanical** — direction must be imposed

§8.16 reported 17:1 and 21:1 short-to-long emission ratios on gold and BTCUSD, two markets
that have risen for years. That is a smell, not a finding, and it was chased to ground.

**It is not a code defect. [V]** `scripts/hvf_v2_mef_mirror.py` reflects the price series
and asks whether symmetric code swaps the two counts. Three levels, increasingly strict:

| chart | level | longs | shorts | S:L | symmetric? |
|---|---|---|---|---|---|
| GoldCFD 2h | as traded | 6,304 | 108,037 | 17.1 | — |
| | **A** mirror the pivot list (`price → −price`, H↔L) | 108,037 | 6,304 | 0.06 | **exact** |
| | B `p → C²/p` (% moves preserved) | 110,741 | 6,095 | 0.06 | ~2.5% off |
| | C `p → K − p` (% moves **not** preserved) | 11,800 | 2,633 | 0.22 | no |
| BTCUSD 1h | as traded | 2,307 | 47,736 | 20.7 | — |
| | **A** | 47,736 | 2,307 | 0.05 | **exact** |
| | B | 49,643 | 2,378 | 0.05 | ~4% off |
| USDJPY 4h | as traded | 114 | 5,658 | 49.6 | — |
| | **A** | 5,658 | 114 | 0.02 | **exact** |
| | B | 5,693 | 114 | 0.02 | ~0.6% off |
| HYG 4h | every level | 1 | 1 | 1.0 | exact |

Level A swaps the counts **to the digit on all four charts**: `mef_candidates`'s bearish
branch is a true mirror of its bullish one. Level B's residual is ZigZag numerics, not
structure. Level C is *expected* to break — an arithmetic reflection does not preserve
percentage moves, so a %-box ZigZag prints different pivots; it is the control that shows
levels A and B are testing something.

The load-bearing consequence is in level B: **reflect gold into a synthetic multi-year
downtrend and the skew flips to ~18:1 longs.** The skew tracks the direction of the series.

**The mechanism, decomposed exactly. [V]** The first hypothesis — that the enumeration
window (the wall span `next_beyond − prev_beyond`) is wider for lows than for highs in an
uptrend — is *true but far too weak*: median span is 12 for both kinds on all three liquid
charts, and even the mean only reaches 1.27× (gold), 1.97× (BTC), 1.05× (USDJPY 4h). It
cannot produce 17–50×. `scripts/hvf_v2_mef_bias.py` records this; it is a dead end kept so
it is not re-tried.

Grouping live candidates by their **anchor pivot** does produce it, and to three digits:

| chart | dir | distinct anchors | funnels | per anchor | top-10 anchors' share |
|---|---|---|---|---|---|
| GoldCFD 2h | long | 148 | 6,304 | 42.6 | 32.2% |
| | short | **598** | 108,037 | **180.7** | 2.2% |
| BTCUSD 1h | long | 87 | 2,307 | 26.5 | 31.6% |
| | short | **424** | 47,736 | **112.6** | 2.6% |
| USDJPY 4h | long | 15 | 114 | 7.6 | 95.6% |
| | short | **190** | 5,658 | **29.8** | 6.2% |

The skew is the product of two independent factors, and they multiply out exactly:

    gold     598/148 = 4.04  ×  180.7/42.6 = 4.24  →  17.1  ✓
    BTCUSD   424/ 87 = 4.87  ×  112.6/26.5 = 4.25  →  20.7  ✓
    USDJPY   190/ 15 = 12.67 ×   29.8/ 7.6 = 3.92  →  49.6  ✓

A long funnel anchors on a high, a short funnel on a low. In an uptrend highs are exceeded
continuously and lows are seldom undercut, so **4–13× more lows survive as valid anchors**,
and each survivor gets **~4× more room** to host a funnel. The long side is not merely
rarer, it is *degenerate*: on USDJPY 4h ten anchors carry 96% of all long candidates, on
gold 32%, whereas the short side is diffuse (2–6%). Ungated, the enumerator is trading the
trend's own asymmetry, not the pattern.

**So the user's objection was right, and for a stronger reason than a bug would have been.**
An unfiltered HVF bot on gold or BTCUSD would be a short-selling machine in a secular bull
market. Direction cannot be left to the geometry; it has to be imposed.

**Does the multi-year window rescue §8.17? Partly — exactly where it was claimed to. [V]**
§8.17 tested at most one year and got 3/7. `scripts/hvf_v2_mef_trendhorizon.py` extends it:

| chart | Hunt | 1y | 2y | 3y | 5y |
|---|---|---|---|---|---|
| GoldCFD 2h | long | +60.9% ✅ | +126.6% ✅ | +123.7% ✅ | +237.2% ✅ |
| BTCUSD 1h *(TEST)* | long | −11.5% ❌ | +1.1% ✅ | **+242.5% ✅** | +23.4% ✅ |
| XAU/XAG 8h | long | −22.8% ❌ | −15.8% ❌ | −9.6% ❌ | −17.8% ❌ |
| USDJPY 4h | long | +5.1% ✅ | +10.1% ✅ | +29.7% ✅ | +49.8% ✅ |
| USDJPY 1W | long | +23.6% ✅ | +46.4% ✅ | +48.2% ✅ | +46.1% ✅ |
| WTI 18h | short | +16.4% ❌ | +21.2% ❌ | +22.2% ❌ | +65.3% ❌ |
| XAUEUR 1h *(TEST)* | short | +63.1% ❌ | +128.5% ❌ | +147.1% ❌ | +246.1% ❌ |
| HYG 4h | short | — | — | — | — |
| **recall** | | **3/7** | **4/7** | **4/7** | **4/7** |

The claim under test was specifically *gold and BTCUSD are up over several years*. **It is
correct, and BTCUSD is the chart the longer window recovers**: −11.5% on the year is a
drawdown inside a +242% three-year advance, so the 1-year window mislabelled it and 2y/3y/5y
all agree with Hunt's long. Gold agrees on every horizon.

What the longer window does **not** do is make with-main-trend a rule. Recall stops at 4/7
and the three failures are horizon-independent: XAU/XAG falls on all four, while WTI and
XAUEUR rise on all four and Hunt shorted both. XAUEUR is gold quoted in euros, up **+246%
over five years, shorted**. Hunt genuinely takes counter-trend setups; §8.17's negative
stands, it is simply narrower than it looked.

**Decision. [C] — direction becomes a hard filter anyway, and the reason is §8.18, not §8.17.**
§8.17 left `with_main_trend` as a feature to be settled on expectancy. That is now superseded:
the filter's job is not to imitate Hunt, it is to **correct a measured mechanical bias in the
enumerator**. A population that is 17:1 short because lows do not get undercut is not a
population whose expectancy means anything. Concretely, on gold the trend gate takes
114,341 → 6,304 candidates (−94.5%) before any other filter, and it removes precisely the
side the bias inflates.

Two things this costs, both stated up front: it forgoes ~3/7 of Hunt's own published setups,
and the trend definition itself is still the weak link — no rule tested in §8.17 or here beats
4/8, and the parameter-free definition remains broken on USDJPY 4h and WTI (§8.15). The
multi-year net-move rule at 2y–5y is adopted as the direction gate because it is the only one
that both scores 4/7 and has a stated rationale, not because it is well established.

**§8.10 is still blocked**, but the blocking list is now shorter: direction is settled
(this section), scale is a prior not a gate (§8.15), and what remains is repairing the trend
definition and turning the ATR band into a rank.

### 8.19 The prior-trend definition, repaired — **degree was the missing term**

§8.15 left the parameter-free trend definition broken on 2 of 8 charts, and §8.10 has been
blocked on it since. It is now fixed, and the fix turns out to settle direction as well.

**The diagnosis. [V]** `trend_of` walked back to `prev_beyond[H1]` — the last pivot exceeding
H1 — and took the extreme opposite pivot in between. That wall is a *single pivot* and the
distance to it is unbounded in both directions:

* **USDJPY 4h** — H1 is the highest pivot in the feed, so `prev_beyond = −1`, the wall
  collapses to bar 0, and the "trend" is the entire **22,802-bar** history back to the
  all-time low.
* **WTI 18h** — the pivot immediately before H1 already exceeds it, so the "trend" is
  **1 bar** and `AMP1/trend = 3.22`: the funnel comes out three times *larger* than the
  impulse that supposedly produced it, which is not a trend measurement at all.

Both are one defect. The definition has **no notion of degree** — and an impulse is only an
impulse relative to a scale. The funnel already carries one: `AMP1`.

**The repair. [C], and it is the same move §8.14 made.** Re-run the ZigZag at a box scaled
to the funnel, and take the last pivot it confirms:

    box = k · AMP1 / anchor_price        trend origin = last coarse pivot known at H1

with `k = 1` pre-committed before the run. Everything inside the funnel is noise at that box
by construction, so the surviving leg is exactly one degree up. It is bounded above (any
`k·AMP1` retracement terminates the leg) and below (a shorter leg is never confirmed), it is
causal, and it introduces no constant that is not derived from the funnel itself.
`scripts/hvf_v2_mef_trendfix.py`.

**Result 1 — the shape ratio becomes usable, and holds out-of-sample. [V]**

| chart | AMP1 | trend | AMP1/trend | f.bars | t.bars | time ratio |
|---|---|---|---|---|---|---|
| GoldCFD 2h | 65.02 | 199.60 | 0.326 | 19 | 7 | 2.71 |
| BTCUSD 1h *(TEST)* | 2801.96 | 6190.44 | **0.453** | 47 | 23 | 2.04 |
| XAU/XAG 8h | 16.93 | 29.38 | 0.576 | 202 | 22 | 9.18 |
| USDJPY 4h | 2.32 | 7.79 | 0.298 | 56 | 239 | 0.23 |
| USDJPY 1W | 21.12 | 34.04 | 0.620 | 63 | 76 | 0.83 |
| WTI 18h | 40.37 | 54.16 | 0.745 | 72 | 1587 | 0.05 |
| XAUEUR 1h *(TEST)* | 81.36 | 151.15 | **0.538** | 76 | 27 | 2.81 |
| HYG 4h | 2.16 | 2.63 | 0.823 | 108 | 85 | 1.27 |

| metric | calib band (n=6) | spread | was (§8.15) | BTCUSD 1h | XAUEUR 1h | holds? |
|---|---|---|---|---|---|---|
| **AMP1/trend** | 0.298 – 0.823 | **2.8×** | 120× | 0.453 | 0.538 | ✅ |
| time ratio | 0.045 – 9.182 | 202× | 29,000× | 2.043 | 2.815 | ✅ |

`AMP1/trend` goes from a 120× band that contained anything to a **2.8× band**, it is now
bounded in (0, 1) by construction — the funnel can no longer come out bigger than its own
impulse — and **both held-out charts land mid-band** at 0.45 and 0.54, having played no part
in setting it. That is a genuine blind check, and unlike §8.15's it is not a tautology.

The time ratio improves by 140× and still fails to be a filter: a 202× band is nearly
vacuous, so "both held-out values sit inside it" proves little. WTI is again the outlier
(1,587 bars ≈ 3 years of 18h). **Carry `AMP1/trend`; do not carry the time ratio.**

**Result 2 — the same definition answers direction, at 7/8. [V]** This had never been tested.
§8.17 tried thirteen rules and every one of them was a *calendar* window — SMA50/200, net
move over 3m/6m/1y, ZigZag legs — on the daily series; §8.18 added 2y/3y/5y. The best of
them scored 4/8. None asked doctrine's actual question (§2.2): what was the trend at the
funnel's **own** degree? Taking the sign of the repaired impulse, direction-free:

| chart | Hunt | k=0.5 | **k=1** | k=2 | k=3 |
|---|---|---|---|---|---|
| GoldCFD 2h | long | +83.8 ✅ | **+115.3 / 7b ✅** | +261.8 ✅ | +261.8 ✅ |
| BTCUSD 1h *(TEST)* | long | +3326 ✅ | **+3326 / 23b ✅** | −5196 ❌ | +6509 ✅ |
| XAU/XAG 8h | long | +2.94 ✅ | **+12.53 / 22b ✅** | −72.83 ❌ | +12.24 ✅ |
| USDJPY 4h | long | +7.65 ✅ | **+7.65 / 239b ✅** | +7.65 ✅ | +10.59 ✅ |
| USDJPY 1W | long | +21.45 ✅ | **+34.48 / 76b ✅** | +86.13 ✅ | +86.13 ✅ |
| WTI 18h | short | −30.8 ✅ | **+24.87 / 1130b ❌** | +85.28 ❌ | +85.28 ❌ |
| XAUEUR 1h *(TEST)* | short | +54.0 ❌ | **−42.63 / 27b ✅** | −66.7 ✅ | +535.1 ❌ |
| HYG 4h | short | −2.35 ✅ | **−2.35 / 85b ✅** | — | — |
| **recall** | | **7/8** | **7/8** | 4/7 | 5/7 |

**7 of 8 against a previous best of 4 of 8**, and the two pre-committed held-out charts both
pass at `k = 1`. The sensitivity is the finding, not a nuisance: recall collapses to 4–5/7 by
`k = 2`. **HVF resolves in the direction of the impulse at its own degree, not the macro
trend** — which is exactly why §8.17's calendar windows failed, since a 1-year window is an
enormous `k`. It also explains the counter-trend setups §8.18 could not account for: XAUEUR
is up +246% over five years and Hunt shorted it, and at `k = 1` the local impulse into that
funnel is **down**, so the rule agrees with him where every calendar window disagreed.

Honest caveat on `k`: 0.5 and 1 both score 7/8 but fail on *different* charts (WTI vs
XAUEUR), so the tiebreak between them is that `k = 1` gets both held-out charts right — which
does spend part of the held-out set's value. WTI fails at every `k ≥ 1`; it is the same chart
§8.15 flagged for an unreliable anchor and §8.17 and §8.18 both failed on. n = 8, one
persistent outlier.

**Result 3 — as a gate it destroys the §8.18 bias but does *not* select. [V]**
The rule is per-candidate, so it is EXCLUSIVE in §8.16's sense: each candidate is admitted in
exactly one direction, its own. `scripts/hvf_v2_mef_trendgate.py`, live window, distinct
funnels:

| chart | long | short | S:L | gated long | gated short | **S:L gated** | total cut |
|---|---|---|---|---|---|---|---|
| GoldCFD 2h | 6,304 | 108,037 | 17.1 | 5,907 | 783 | **0.13** | 17× |
| BTCUSD 1h | 2,307 | 47,736 | 20.7 | 1,371 | 3,802 | **2.8** | 9.7× |
| USDJPY 4h | 114 | 5,658 | 49.6 | 110 | 225 | **2.0** | 17× |
| HYG 4h | 1 | 1 | 1.0 | 0 | 1 | — | 2× |

The counter-trend bias measured in §8.18 is gone: **gold flips from 17:1 short to 7.5:1
long**, USDJPY from 49.6:1 to 2.0:1. Recall through this exact code path is **7/8** — the same
seven, WTI the same miss — so the cut is not bought by discarding Hunt's setups.

**What it does not do is select**, and this must not be overstated. Gold still emits
**950/month** after the gate (was 16,242), BTCUSD 735, USDJPY 4h 47.6, against §8.7's detector
rates of 1.1, 0.4 and 0.2. Direction is a *bias* correction, roughly one order of magnitude;
the remaining three orders are §8.15's job — the prior-trend gate and the scale prior, the
latter of which `AMP1/trend` can now finally join.

**A lookahead bug found and fixed on the way, worth recording. [V]** The first version of
`coarse_table` ran one ZigZag over the whole series and then selected the last pivot with
`index ≤ anchor`. A pivot's `index` is where its extreme *printed*; it is not KNOWN until
price reverses a box away, which is what `Pivot.confirm` is for and what §4.1 warns about in
so many words. Keyed by `index` the gate reported a **783× cut on gold (114,341 → 146)** and
recall of 6/8; keyed by `confirm` the true numbers are a 17× cut and 7/8. The lookahead
version looked **46× better**. Any future filter measured this way must select on `confirm`.

**Decision. [C] — this supersedes §8.18's direction gate.** The multi-year net-move rule was
adopted in §8.18 for want of anything better (4/7, chart-level, PERMISSIVE). It is replaced
by the funnel-degree impulse: 7/8, per-candidate, exclusive, causal, parameter-free given the
funnel, and it removes the enumerator bias §8.18 existed to correct. §8.18's *reasoning*
stands unchanged — direction must be imposed because the geometry is biased — only its
instrument changes. The user's original objection is also now satisfied on its own terms:
under this gate gold emits **7.5 longs for every short**.

**§8.10 status.** Both of §8.15's blockers are cleared: the trend definition is repaired
(this section) and direction is settled. What remains before expectancy is meaningful is
turning the ATR band into a rank rather than a gate, and adding `AMP1/trend` to it — the
emission rate is still ~3 orders of magnitude above §8.7's, and expectancy over a
950/month population would repeat §8.12's error a third time.

### 8.20 The scale band becomes a rank — and the band is retired by it

§8.15 applied `AMP1/ATR14` as a hard band `[1.882, 10.196]` whose edges came from six charts,
and it deleted USDJPY 4h, which sat *on* the upper edge. That is the generic failure of a band
fitted at n=6. §8.15 itself concluded the quantity is a **scale prior** and belongs in a
ranking score; §8.19 cleared the last blocker by making `AMP1/trend` measurable. This builds
the score. `scripts/hvf_v2_mef_rank.py`.

**The score. [C]** A diagonal Mahalanobis distance in log space over two features,

    u = log(AMP1 / ATR14 at H1)      §8.15, the only shape metric that ever survived
    v = log(AMP1 / prior trend)      §8.19, usable only since the degree repair

fitted to the six calibration funnels, evaluated on all eight. Log space because both are
ratios; diagonal because n=6 cannot support a covariance. **Nothing is discarded.** What is
reported is where Hunt's own funnel sits in the ordering, and how many candidates per month
outrank it — the honest form of §8.7's emission-rate question and the number §8.10 needs.

| feature | mean | sd | = ratio | 1sd band |
|---|---|---|---|---|
| `log AMP1/ATR14` | 1.688 | 0.605 | 5.41 | 2.95 – 9.90 |
| `log AMP1/trend` | −0.442 | 0.760 | 0.64 | 0.30 – 1.38 |

**Result 1 — the rank finds Hunt's funnel near the top of a five-figure population. [V]**
One box per chart, both directions, live window, `confirm`-keyed throughout. Rank is Hunt's
position; `ahead/mo` is how many candidates a human would have to read before reaching his.

| chart | N | ATR only | trend only | **both** | ahead/mo (both) |
|---|---|---|---|---|---|
| GoldCFD 2h | 76,797 | 2,070 | 18,279 | 2,106 (2.7%) | 299.4 |
| BTCUSD 1h *(TEST)* | 49,673 | 95 | 1,906 | **25 (0.1%)** | 3.4 |
| XAU/XAG 8h | 1,280 | 52 | 10 | 13 (1.0%) | 1.7 |
| USDJPY 4h | 3,742 | 54 | 2,504 | 85 (2.3%) | 11.9 |
| USDJPY 1W | 49 | 9 | 1 | 8 (16.3%) | 1.0 |
| WTI 18h | 3,528 | 54 | 2,475 | 786 (22.3%) | 111.7 |
| XAUEUR 1h *(TEST)* | 18,633 | 206 | 1,178 | **114 (0.6%)** | 16.1 |
| HYG 4h | 1 | 1 | 1 | 1 | 0.0 |
| **median rank** | | 54 | 1,542 | 55 | |

Adding §8.19's direction gate first:

| chart | N gated | ATR only | trend only | **both** | ahead/mo (both) |
|---|---|---|---|---|---|
| GoldCFD 2h | 4,891 | 1,159 | 1,765 | 1,169 (23.9%) | 166.1 |
| BTCUSD 1h *(TEST)* | 5,175 | 72 | 1,214 | **22 (0.4%)** | 3.0 |
| XAU/XAG 8h | 1,198 | 13 | 6 | 13 (1.1%) | 1.7 |
| USDJPY 4h | 309 | 35 | 301 | 45 (14.6%) | 6.3 |
| USDJPY 1W | 9 | 2 | 1 | 2 (22.2%) | 0.1 |
| WTI 18h | 1,682 | — | — | gate drops it | — |
| XAUEUR 1h *(TEST)* | 2,306 | 171 | 98 | 102 (4.4%) | 14.4 |
| HYG 4h | 1 | 1 | 1 | 1 | 0.0 |
| **median rank** | | 35 | 98 | **22** | |

**BTCUSD, held out, ranks 25th of 49,673 ungated and 22nd of 5,175 gated** — 3.0 candidates a
month ahead of it — having played no part in fitting the prior. XAUEUR, also held out, is
0.6% / 4.4%. Six of eight charts are now at **≤ 16 ahead/month**, five at ≤ 6.3, against
§8.19's gated emission of 950/mo on gold and 735 on BTCUSD. That is the two-to-three orders
of magnitude §8.15 said were missing, on seven charts.

**Percentile is not the headline and is reported only for completeness.** The direction gate
removes candidates that were *already worse* than Hunt's, so it can worsen the percentile
while improving the absolute rank — gold goes 2.7% → 23.9% while its rank improves 2,106 →
1,169. `ahead/mo` is the quantity §8.7 and §8.10 care about: how long a list a human reads.

**Result 2 — a tight band across Hunt's charts is NOT the same thing as a discriminative
feature. [V]** This is the methodological finding of the section and it reverses a judgement
made in §8.15. `AMP1/trend` has the *tighter* band of the two after §8.19 (2.8×, bounded in
(0,1)) and §8.15 would have ranked it the better feature on that basis. As a ranking feature
alone it is **useless** — median rank 1,542, and it puts Hunt at the 67th and 70th percentile
on USDJPY 4h and WTI. `AMP1/ATR14`, whose band is looser, gives a median rank of 54.

The reason is that §8.15 judged features by the **spread of Hunt's own values** and the right
criterion is **separation from the candidate distribution**. A feature on which every
candidate looks like Hunt is tight and worthless. Any future feature must be scored this way.

`v` is still worth carrying jointly, on a narrower claim: it improves **both** held-out charts
(BTCUSD 95 → 25, XAUEUR 206 → 114 ungated) and it is what takes the gated median from 35 to
22. It costs on WTI (54 → 786), which is the same persistent outlier as §8.15, §8.17, §8.18
and §8.19. Two-of-two out-of-sample improvement at n=2 is weak evidence; carry it, and revisit
if a third test chart disagrees.

**Result 3 — the band is subsumed, not merely superseded. [V]** A rank does not automatically
retire a band, and on gold the band looked like the stronger shortlist: it keeps 1,268
candidates where the rank leaves 2,106 ahead of Hunt. Composing them (gate → band → rank)
settles it:

| chart | gated | + band | Hunt survives | rank | ahead/mo | gain vs rank alone |
|---|---|---|---|---|---|---|
| GoldCFD 2h | 4,891 | 752 | yes | 751 | 106.7 | **1.6×** |
| BTCUSD 1h *(TEST)* | 5,175 | 107 | yes | 22 | 3.0 | 1.0× |
| XAU/XAG 8h | 1,198 | 33 | yes | 13 | 1.7 | 1.0× |
| USDJPY 4h | 309 | 35 | yes | 30 | 4.1 | 1.5× |
| USDJPY 1W | 9 | 3 | yes | 2 | 0.1 | 1.0× |
| XAUEUR 1h *(TEST)* | 2,306 | 536 | yes | 102 | 14.4 | 1.0× |

**The band adds at most 1.6× and usually nothing at all**, because almost everything it
deletes was already ranked behind Hunt. It carries the deletion risk for no shortlist gain.
**Retire it.** [C]

A detail that sharpens the original objection: measured on the *detected* funnel rather than
the chart annotation, the band does **not** drop USDJPY 4h here — it keeps Hunt on all eight.
§8.15's deletion came from the annotated AMP1/ATR of 10.196 against an edge of 10.196. Whether
a chart survives turns on which of two near-identical measurements is used. That is the
argument for a rank stated more strongly than §8.15 stated it, not more weakly.

**Result 4 — what is still broken. [V]** **Gold.** 1,169th of 4,891, 166 candidates a month
ahead of Hunt's, against §8.7's 1.1/mo. It is the one chart where neither the gate nor the
rank bites, and it is also the largest population (76,797 at one box). WTI is worse in kind —
§8.19's gate discards it outright. So the shortlist is usable on six of eight charts and not
on two, and the two are the ones every previous section also failed on.

**§8.10 status. [C]** The band-to-rank conversion was the last of §8.15's three blockers and
it is done. Expectancy can now be run **per chart over a ranked shortlist**, not over the raw
population — which is exactly the error §8.12 made twice. The honest framing for §8.10 is a
top-N sweep: at N=25 the shortlist contains Hunt's funnel on BTCUSD, XAU/XAG, USDJPY 1W and
HYG, and does not on gold, USDJPY 4h, WTI or XAUEUR. Gold must be diagnosed before any
aggregate expectancy number is quoted, or it will dominate the population and the result will
mean nothing.

### 8.21 What a funnel is worth — the premise, tested for the first time

Every section from §8.14 to §8.20 measures **agreement with Hunt's annotations**. None measures
money, and agreement is not a proxy for profit: the object being reproduced has unknown
expectancy, so a perfect classifier for a break-even pattern is a live possibility. §8.10 has
been deferred five sections running. This is the cheapest thing that could falsify the whole
premise — the R-multiple of Hunt's own eight setups. `scripts/hvf_v2_mef_rmultiple.py`.

**Method. [C]** The simulation runs on the **detected** funnel, never the annotation, and arms
at `RL3.confirm` — the bar the sixth pivot becomes knowable. A live system has nothing earlier.
Entry is a stop order at the 5th pivot, stop-loss at the 6th, target is a measured move of
`AMP1` from entry. Intrabar ties resolve to the **stop**, the conservative side of an ambiguity
OHLC cannot settle. Entry must trigger within the funnel's own span in bars or the setup is
abandoned.

**Result 1 — the geometry pays, and it is exact rather than anecdotal. [V]** Risk is
`(rh3 − rl3) · AMP1` by construction, so reward:risk is `1/(rh3 − rl3)` and depends on nothing
but the funnel's shape:

| chart | dir | AMP1 | risk | AMP1/risk | breakeven win% |
|---|---|---|---|---|---|
| GoldCFD 2h | long | 63.68 | 32.37 | 1.97 | 33.7% |
| BTCUSD 1h *(TEST)* | long | 2849.06 | 1489.50 | 1.91 | 34.3% |
| XAU/XAG 8h | long | 16.97 | 3.22 | **5.27** | 15.9% |
| USDJPY 4h | long | 2.331 | 0.860 | 2.71 | 27.0% |
| USDJPY 1W | long | 22.371 | 5.432 | 4.12 | 19.5% |
| WTI 18h | short | 38.07 | 17.11 | 2.23 | 31.0% |
| XAUEUR 1h *(TEST)* | short | 79.93 | 41.51 | 1.93 | 34.2% |
| HYG 4h | short | 2.19 | 0.80 | 2.74 | 26.8% |
| **median** | | | | **2.47** | **28.8%** |

The tight-stop-against-a-measured-move structure HVF claims is real: a **28.8% win rate breaks
even** at the median. That is the sole structural reason this pattern could carry an edge, and
it survives contact with the annotations.

**Result 2 — the move is usually there; capturing it is the open question. [V]**

| chart | state | bars→fill | held | MFE (R) | MAE (R) | R @ target |
|---|---|---|---|---|---|---|
| GoldCFD 2h | stopped | 1 | 1 | 1.01 | 2.46 | **−1.00** |
| BTCUSD 1h *(TEST)* | stopped | 1 | 156 | 3.48 | 1.16 | **+1.91** |
| XAU/XAG 8h | open | 73 | 122 | 2.72 | 0.85 | open |
| USDJPY 4h | stopped | 7 | 60 | 1.75 | 5.25 | **−1.00** |
| USDJPY 1W | open | 1 | 42 | 2.41 | 0.28 | open |
| WTI 18h | open | 14 | 71 | 1.30 | 0.54 | open |
| XAUEUR 1h *(TEST)* | stopped | 1 | 176 | 3.36 | 1.20 | **+1.93** |
| HYG 4h | open | 1 | 12 | 0.26 | 0.23 | open |

All eight filled. **7 of 8 reach ≥1R** of favourable excursion and 4 of 8 reach ≥2R, median MFE
**2.08R**. Four have resolved at a measured-move target: **mean +0.46R, 2 wins from 4**.

**n=4 resolved is worth nothing statistically and no weight is placed on it.** What §8.21
establishes is narrower and sufficient: the premise is **not falsified**, so a real backtest is
justified. Note also the gap between MFE and realised — the excursion exists on 7 of 8 but only
2 of 4 resolved trades banked it, which makes the **exit rule**, untouched so far, a first-class
open question rather than a detail.

**Result 3 — fills are knife-edge, and this is mechanical. [V]** Entries fill a **median of one
bar** after `RL3.confirm`. That is not luck. Gold's risk is 0.74% of price and its detection box
is 0.71%: the move that *confirms* the sixth pivot is the same size as the move to the entry, so
confirmation and trigger are near-simultaneous by construction. Any backtest that fills at the
trigger price is therefore maximally exposed to slippage and latency, and the assumption must be
stated every time rather than buried. This is a property of the detector's box, so it can be
traded off against detection quality — but not ignored.

**Verdict. [C]** Proceed to expectancy over a ranked shortlist (§8.22). The two things §8.21
says must be carried into it: trades come off the shortlist and never the raw population — the
error §8.12 made twice — and a **random-selection control** is mandatory, because a positive
result over 2023–2026 could be the pattern, the direction gate, or simply a bull market, and
without a control it cannot be attributed to the rank.

### 8.22 The first backtest — the pattern pays, the rank is not what pays

§8.21 cleared the premise. This runs expectancy properly for the first time: enumerate funnels,
impose §8.19's direction, rank by §8.20's prior, trade the top few each month.
`scripts/hvf_v2_mef_backtest.py`, `scripts/hvf_v2_mef_significance.py`.

**Design. [C]** 2023-01-01 → 2026-08-03, one box per chart, gated population 57,976 candidates.
Entry is a stop order at the 5th pivot armed from `RL3.confirm`, stop at the 6th, target a
measured move of `AMP1`; intrabar ties go to the stop; one open position per chart. Trades come
off a **shortlist, never the raw population** — the error §8.12 made twice. Fills at the trigger
price, **no costs, no slippage, no financing**, which §8.21 showed is the most exposed
assumption in the study.

Disclosed leak: §8.20's prior is fitted on six funnels dated 2026, inside the test window. Six
points setting four constants is small but not zero.

**Result 1 — the system makes money at every shortlist depth. [V]** Pooled across charts:

| top N/month | trades | win% | mean R | total R | PF | | control win% | control mean R |
|---|---|---|---|---|---|---|---|---|
| 1 | 156 | 22.4% | +0.40 | +61.9 | 1.51 | | 13.0% | −0.13 |
| 2 | 186 | 24.2% | +0.47 | +87.4 | 1.62 | | 12.1% | +0.18 |
| **3** | **212** | **26.4%** | **+0.76** | **+161.2** | **2.03** | | 12.6% | +0.14 |
| 5 | 249 | 24.9% | +0.54 | +133.9 | 1.72 | | 13.1% | +0.39 |
| 10 | 266 | 19.9% | +0.26 | +68.7 | 1.32 | | 10.9% | −0.04 |

Bootstrapping the 212 trades at N=3: mean **+0.76R, 95% CI [+0.32, +1.24]**, P(mean>0) = 100%.
Note the trade count barely moves with N (156 → 266 as the shortlist goes 1 → 10) because the
one-position-per-chart rule binds long before the shortlist does.

Note also that the **win rate is below the 28.8% breakeven of §8.21 at every depth**. The
expectancy is carried entirely by dispersion in `AMP1/risk` — the winners are the high-reward
funnels. That is a real mechanism, not an artefact, but it is a fragile one: it means results
depend on a minority of trades and the mean is not robust to a few exits going differently.

**Result 2 — and here the honest part. The rank cannot be shown to be what earns it. [V]**
The first run compared against a single random draw, which at ~30 trades a chart is far too
noisy. Redrawing the control over **200 seeds** gives a null distribution to place the ranked
result against:

| chart | rank mean R | null mean | null sd | percentile | rank win% | null win% |
|---|---|---|---|---|---|---|
| GoldCFD 2h | +1.72 | +0.16 | 0.35 | **100.0%** | 37.5% | 18.2% |
| BTCUSD 1h *(TEST)* | +0.85 | +1.22 | 1.63 | 54.0% | 26.5% | 6.0% |
| XAU/XAG 8h | −0.74 | −0.81 | 0.51 | 85.5% | 9.1% | 1.9% |
| USDJPY 4h | +0.55 | +0.32 | 1.03 | 72.0% | 25.6% | 12.5% |
| USDJPY 1W | +1.62 | +3.38 | 2.09 | 6.0% | 50.0% | 73.8% |
| WTI 18h | −0.07 | −0.43 | 0.55 | 80.0% | 13.2% | 6.5% |
| XAUEUR 1h *(TEST)* | +1.22 | +0.46 | 0.37 | **97.5%** | 34.5% | 20.3% |
| **POOLED** | **+0.73** | **+0.61** | 0.38 | **61.0%** | | |

**Pooled, the rank sits at the 61st percentile of random selection from the same gated pool.**
That is not an edge. It is clear on gold (100th) and on held-out XAUEUR (97.5th), absent
everywhere else, and n=2 makes USDJPY 1W's 6th percentile meaningless.

The rank *does* do one thing consistently and strongly: it roughly **doubles the win rate** on
every chart (37.5 vs 18.2, 26.5 vs 6.0, 34.5 vs 20.3, 25.6 vs 12.5). That does not convert into
mean R because random selection occasionally draws a very high `AMP1/risk` funnel and those
lottery tickets carry the null's mean — BTCUSD's null has mean +1.22 with sd 1.63.

**The conclusion this forces. [V]** The **random control is itself profitable** (+0.61R pooled).
So the edge measured in Result 1 lives in the parts *upstream* of the rank — the funnel geometry
of §8.21 and the direction gate of §8.19 — and **not** in §8.20's selection. Five sections were
spent on selection; the money is in direction and shape.

**Result 3 — two charts are outright negative and it is the same two as ever. [V]** XAU/XAG
−0.74R with a bootstrap CI of [−1.00, −0.23] entirely below zero, and WTI −0.07R. These are the
charts that failed §8.15, §8.17, §8.18, §8.19 and §8.20. The failure is now measured in money
and it is consistent across every method tried.

**What this backtest does NOT establish, and the next test must. [C]** The direction gate makes
every trade a trend-following breakout, and the window 2023–2026 contains enormous trends in
gold and BTCUSD. A trend-following breakout system will look good over it whether or not the
funnel means anything. **The control used here randomises *which funnel* is traded but never
asks whether a funnel is needed at all.** The decisive test is a control that keeps the entry
timing, direction and `AMP1/risk` geometry but takes the structure away — random entries, same
stop and target distances, same regime. Until that runs, the correct statement is:

> A trend-aligned breakout with a ~2.5:1 measured-move target made money on six of eight
> instruments over 2023–2026, before costs. Whether the *funnel* contributes anything beyond
> the trend alignment is untested.

Everything else remains subject to zero costs, zero slippage on a fill §8.21 showed is
knife-edge, overlapping non-independent trades, and 43 months of one regime.

### 8.23 Ablation — the structure is real, the direction gate is real, the rank still is not

§8.22 could not attribute its own result: the control shuffled *which* funnel was traded and so
kept direction, timing and the 2.5:1 geometry present in the null. The honest reading was left
as "a trend-aligned breakout in a trending window, funnel possibly decoration".
**That reading is now falsified.** `scripts/hvf_v2_mef_ablation.py`.

**Method. [C]** The funnel does three separable jobs — it supplies a **scale** (`AMP1`, which
§8.19's gate needs), a **timing** (the breakout at the 5th pivot, armed from `RL3.confirm`), and
a **risk unit with its payoff**. Three ablations remove exactly one each:

* **B/C structure** — same instrument, direction, risk distance, reward:risk *and the same
  distance from price to the trigger*, but armed `k` bars away from the funnel. Levels are
  expressed as offsets from the anchor's close, so everything is preserved exactly and only the
  coincidence that this level bounds a funnel is removed. **`k=0` reproduces the baseline bar for
  bar (0.76R, 212 trades)**, which is the sanity check that the ablation is well-formed.
* **D direction** — every trade mirrored about its anchor.
* **E gate** — same rank and geometry, selected from the **ungated** pool (503,219 candidates,
  57,976 gated).

**Result 1 — removing the structure destroys the edge. [V]** 200 random shifts of ±50–1500 bars:

| chart | real meanR | null mean | null sd | null p95 | **percentile** | real win% | null win% |
|---|---|---|---|---|---|---|---|
| GoldCFD 2h | +1.72 | +0.69 | 0.40 | 1.34 | **98.0%** | 37.5% | 27.5% |
| BTCUSD 1h *(TEST)* | +0.85 | +0.06 | 0.25 | 0.50 | **99.5%** | 26.5% | 19.8% |
| XAU/XAG 8h | −0.74 | −0.80 | 0.46 | 0.28 | 79.5% | 9.1% | 4.1% |
| USDJPY 4h | +0.55 | +0.15 | 0.44 | 0.99 | 85.0% | 25.6% | 17.3% |
| USDJPY 1W | +1.62 | −0.44 | 0.73 | 1.13 | 99.5% | 50.0% | 11.2% |
| WTI 18h | −0.07 | +0.24 | 0.55 | 1.24 | 29.5% | 13.2% | 13.3% |
| XAUEUR 1h *(TEST)* | +1.22 | +0.88 | 0.44 | 1.70 | 77.5% | 34.5% | 29.6% |
| **POOLED** | **+0.73** | **+0.11** | **0.17** | **0.40** | **100.0%** | | 17.5% |

**Pooled, the real result beats all 200 random-shift nulls**, and it does so by a wide margin —
+0.73R against a null of +0.11 ± 0.17. Held-out **BTCUSD is at the 99.5th percentile**. The
fixed-shift sweep says the same thing without any randomisation:

| k (bars) | 0 | 25 | 50 | 100 | 250 | 500 |
|---|---|---|---|---|---|---|
| mean R | **+0.76** | +0.36 | +0.24 | +0.35 | +0.43 | +0.10 |

Moving the trade off the breakout costs half the edge or more at every distance tried. **The
six-pivot structure is doing work that direction and geometry alone do not do.** This is the
first result in the entire study that shows the pattern predicting *price* rather than
predicting *Hunt*, and it is much stronger evidence than any recall number in §8.14–§8.20.

**Result 2 — the direction gate is worth roughly half the edge, and flipping it erases it. [V]**

| variant | trades | win% | mean R | total R |
|---|---|---|---|---|
| **A baseline** | 212 | 26.4% | **+0.76** | +161.2 |
| D direction flipped | 239 | 17.6% | **0.00** | +0.5 |
| E gate removed (ungated pool) | 246 | 25.6% | **+0.38** | +94.1 |

Mirroring every trade takes +0.76R to **exactly zero** — the edge is entirely directional.
Selecting from the ungated pool halves it, 0.76 → 0.38, which is what §8.19 is worth **in money**
rather than in recall. Note flipping yields ~0 rather than a symmetric loss, so the edge is not a
sign error on a symmetric effect; it is a real asymmetry that direction alignment unlocks.

**Result 3 — the rank remains unvalidated. [V]** §8.22 put it at the 61st percentile of random
*selection*; nothing here changes that. The three-way attribution is now:

| component | evidence | verdict |
|---|---|---|
| funnel structure (§8.14 MEF) | 100th pct vs 200 shift-nulls | **real** |
| direction at own degree (§8.19) | 0.76 → 0.38 removed, → 0.00 flipped | **real** |
| scale-prior rank (§8.20) | 61st pct vs 200 selection-nulls | **not established** |

**Result 4 — WTI now fails a test it cannot be argued out of. [V]** At the 29.5th percentile its
real result is *worse* than randomly shifting it, and XAU/XAG is negative in absolute terms
(−0.74R) even while beating its own null. These are the same two charts that failed §8.15,
§8.17, §8.18, §8.19, §8.20 and §8.22. Six independent methods now agree they are outliers; they
should be excluded from further calibration rather than diagnosed again.

**Standing caveats, unchanged. [D]** Zero costs and zero slippage on a fill §8.21 showed lands a
median of one bar after `RL3.confirm`; 43 months of a single regime; trades that overlap in time
and across nested funnels and are therefore not independent draws. The shift null also relocates
trades into different volatility regimes, which is a partial confound in its favour, not against.

**Decision. [C]** Build it. The two components that survive ablation — MEF detection and the
degree-scaled direction gate — are the strategy. §8.20's rank should be carried only as a
tie-break for shortlist length, not credited with edge. The next work is costs and slippage
against the knife-edge fill, then the exit rule, which §8.21 flagged and nothing has yet touched.

### 8.24 The payoff asymmetry — real, and it has a ceiling

§8.23 settled attribution but never examined the **engine**. At 26.4% wins and +0.76R the average
winner is **+5.67R**, far above §8.21's 2.47R median geometry, so expectancy is carried by the
tight funnels whose risk is small and whose measured move is many multiples of it. The obvious
inference is to select on reward:risk. `scripts/hvf_v2_mef_payoff.py`.

The inference is only sound if the **hit rate holds as the target recedes**. Under a random walk
it cannot: the chance of travelling `T` risk-units before travelling one falls as roughly
`1/(1+T)`, mean R is flat, and sorting on `T` buys nothing. So the question is never "is the
payoff asymmetric" — it is by construction — but "is the hit rate better than the asymmetry
demands".

**Result 1 — it is, by a wide margin, at every size. [V]** The 212 baseline trades bucketed by
`AMP1/risk`, each bucket against the breakeven *it* needs:

| AMP1/risk | n | median T | breakeven | realised win% | **edge** | mean R |
|---|---|---|---|---|---|---|
| 1.42 – 3.91 | 53 | 2.92 | 25.5% | 35.8% | **+10.3%** | +0.40 |
| 3.93 – 5.73 | 53 | 4.72 | 17.5% | 28.3% | **+10.8%** | +0.56 |
| 5.74 – 9.56 | 53 | 7.06 | 12.4% | 32.1% | **+19.7%** | **+1.65** |
| 9.70 – 32.19 | 53 | 12.86 | 7.2% | 9.4% | +2.2% | +0.42 |
| **ALL** | 212 | 5.73 | 14.9% | **26.4%** | **+11.6%** | +0.76 |

**Every bucket beats its own breakeven.** The headline "26.4% wins is below §8.21's 28.8%
breakeven" was the wrong comparison — 28.8% is the breakeven for a 2.47R target, and these trades
carry a median target of **5.73R**, needing only 14.9%. The system clears its bar by **+11.6
points**, and the effect strengthens up to `T ≈ 7`, where a 32.1% hit rate against a 12.4%
requirement returns **+1.65R a trade**. §8.22's framing of the win rate as "below breakeven and
therefore fragile" was wrong and is corrected here.

**Result 2 — but it breaks down past `T ≈ 10`, and the reason is mechanical. [V]** The top bucket
collapses to a +2.2% edge and +0.42R. `corr(AMP1/risk, win) = −0.206`, and the **losers carry the
higher reward:risk** — mean 8.19 against the winners' 5.67. `AMP1/risk` is `1/(rh3 − rl3)`, so an
extreme value means the last two pivots are almost coincident: the stop sits a hair from the entry,
inside single-bar noise, and gets taken out before the structure can resolve. The asymmetry is
real up to the point where the stop stops being a stop.

**Result 3 — so selecting on reward:risk actively destroys the edge. [V]** Reselecting the
shortlist by highest `AMP1/risk` instead of §8.20's z-score, against §8.23's shift-null:

| chart | by z (§8.20) | by AMP1/risk | null mean | percentile | n | win% |
|---|---|---|---|---|---|---|
| GoldCFD 2h | +1.72 | +0.82 | +0.72 | 65.0% | 36 | 16.7% |
| BTCUSD 1h *(TEST)* | +0.85 | +2.84 | −0.15 | 100.0% | 22 | 4.5% |
| XAU/XAG 8h | −0.74 | −1.00 | −0.93 | 0.0% | 10 | 0.0% |
| USDJPY 4h | +0.55 | +0.81 | +1.17 | 46.0% | 15 | 6.7% |
| USDJPY 1W | +1.62 | −1.00 | −0.87 | 0.0% | 2 | 0.0% |
| WTI 18h | −0.07 | −1.00 | +0.55 | 0.0% | 34 | 0.0% |
| XAUEUR 1h *(TEST)* | +1.22 | +1.46 | +1.08 | 78.0% | 23 | 26.1% |
| **POOLED** | **+0.73** | **+0.42** | | | | |

Pooled it is **worse than §8.20's rank** (0.42 vs 0.73) and worse than the shift-null on four
charts, with win rates of 0.0% on three of them. Maximising reward:risk selects precisely the
degenerate funnels of Result 2. **Do not select on reward:risk. [C]**

**What this points at next. [I]** The failure mode is a stop too tight to survive noise, which is
a statement about `risk` relative to **volatility**, not relative to `AMP1`. The principled filter
is therefore a **minimum stop distance in ATR units** — reject a funnel when `risk / ATR14` at the
anchor is below some threshold — rather than a fitted band on `T`. That is one measurement away
and it is the most promising selection idea the study has produced, because unlike §8.20's prior
it has a mechanism behind it. Note honestly that it was suggested *by* this data and so must be
validated out-of-sample before being credited.

**Caveats unchanged. [D]** Zero costs, zero slippage on a knife-edge fill, one regime, overlapping
non-independent trades. Bucket boundaries are quartiles of the observed sample, so the `T ≈ 7`
optimum is in-sample and is not a tuned parameter recommendation.

### 8.25 A minimum stop in ATR units — rejected out-of-sample

§8.24 diagnosed the collapse past `AMP1/risk ≈ 10` as a stop sitting inside single-bar noise, and
proposed the principled filter that follows from it: `risk / ATR14 ≥ threshold` at the arming bar.
It was suggested by §8.24's own data, so it was validated the only way that means anything —
threshold chosen on the **six calibration charts**, then applied unchanged to the two
pre-committed held-out ones. `scripts/hvf_v2_mef_stopfilter.py`.

**Result 1 — the mechanism is visible, and weak. [V]** Baseline picks bucketed by `risk/ATR14`:

| risk/ATR | n | median T | breakeven | realised win% | edge | mean R |
|---|---|---|---|---|---|---|
| 0.49 – 1.41 | 166 | 7.46 | 11.8% | 15.1% | +3.2% | +0.17 |
| 1.42 – 2.35 | 165 | 5.09 | 16.4% | 19.4% | +3.0% | +0.16 |
| 2.35 – 4.03 | 165 | 5.27 | 15.9% | 21.2% | +5.3% | +0.25 |
| 4.06 – 20.88 | 165 | 6.05 | 14.2% | 23.0% | +8.8% | **+0.55** |

Monotone in the predicted direction — a stop further from the noise does better, 0.17R → 0.55R —
but `corr(risk/ATR, win) = +0.043`, which is nothing. *(Disclosure: these 661 picks are run
individually rather than through the one-position-per-chart sequencing, so this is a larger
population than the 212 sequenced baseline trades; it measures the relationship cleanly but is
not the same sample as the sections below.)*

**Result 2 — and the threshold does not transfer. This is the finding. [V]**

| threshold | 6 calibration charts | 2 held-out charts | all 8 |
|---|---|---|---|
| **0.00 (none)** | n=134, +0.63R | n=78, **+0.98R** | n=212, **+0.76R** |
| 0.50 | 135, +0.62 | 78, +0.98 | 213, +0.75 |
| 1.00 | 120, +0.56 | 79, +0.96 | 199, +0.72 |
| **1.50 (best on calib)** | 100, **+0.69** | 79, **+0.81** | 179, +0.74 |
| 2.00 | 83, +0.52 | 78, +0.61 | 161, +0.57 |
| 3.00 | 55, +0.09 | 62, +0.53 | 117, +0.33 |

The best calibration threshold, `risk/ATR ≥ 1.50`, improves calibration from +0.63R to +0.69R and
**degrades the held-out two from +0.98R to +0.81R**. Across all eight it moves +0.76R to +0.74R —
it discards 33 trades to achieve nothing. **Reject the filter. [C]**

This is the same lesson as §8.20 arriving by a different route: a plausible mechanism plus an
in-sample improvement is not evidence. The mechanism in Result 1 is *real* and still fails to
produce a usable rule, because the effect is too weak relative to the variance to survive a
threshold being placed on it.

**Result 3 — the structure keeps carrying the result regardless. [V]** At `risk/ATR ≥ 1.50`
against §8.23's shift-null: pooled **+0.88R vs a null of +0.02 ± 0.16, the 100th percentile**;
BTCUSD (held out) 99.0%, gold 91.5%, USDJPY 4h 90.5%. That is §8.23 reconfirmed on a different
subsample, not a new finding, and it is not the filter's doing.

**Where selection now stands. [C]** Three selection ideas have been tested against a null and all
three have failed: §8.20's scale-prior rank (61st percentile of selection nulls), §8.24's
reward:risk (+0.42R against +0.73R), and this one (no out-of-sample transfer). What survives every
test is **detection (§8.14) and direction (§8.19)**. The working conclusion is that funnel
*selection* may simply not be where the edge lives — take every gated funnel the detector emits,
cap exposure by position limits rather than by ranking, and stop spending sections trying to
choose between them. Costs, slippage and the exit rule are untouched and are now the only
material unknowns left before a live decision.

### 8.26 The exit rule — the measured move survives, everything else loses money

`scripts/hvf_v2_mef_exit.py`

Every backtest from 8.22 onward used one exit and never questioned it: a measured
move of `AMP1` from entry, a hard stop at the 6th pivot, ties to the stop, no trail
and no time limit. 8.21 gave a direct reason to suspect it was leaving money behind
— **7 of Hunt's 8 setups reach ≥1R of favourable excursion, but only 2 of the 4
resolved trades banked it** — and I told the user the exit was likely worth more
than any selector I had tried. That guess was wrong, and usefully so.

Fourteen rules in four families, on the same top-3/month shortlist as 8.22–8.25.
Chosen on the six calibration charts, reported blind on `BTCUSD 1h` and `XAUEUR 1h`.
**Position sequencing is re-run per rule** — changing the exit changes when capital
frees up and therefore which later setups are takeable at all, so a fixed trade list
would have compared rules on different opportunity sets without saying so.

| rule | calib mean R | held-out mean R | all 8 | n | win% |
|---|---|---|---|---|---|
| **AMP1 target (baseline)** | **+0.63** | **+0.98** | **+0.76** | 212 | 26.4% |
| fixed 1R | +0.14 | +0.34 | +0.22 | 329 | 60.8% |
| fixed 2R | +0.19 | +0.33 | +0.24 | 297 | 41.4% |
| fixed 3R | +0.40 | +0.55 | +0.45 | 264 | 36.4% |
| fixed 4R | +0.51 | +0.68 | +0.58 | 244 | 31.6% |
| fixed 5R | +0.54 | +0.82 | +0.64 | 216 | 27.3% |
| AMP1 + BE at 1R | +0.14 | +0.79 | +0.38 | 263 | 15.6% |
| AMP1 + BE at 2R | +0.46 | +0.81 | +0.59 | 235 | 20.9% |
| AMP1 + trail 2 ATR | +0.25 | +0.07 | +0.18 | 352 | 45.5% |
| AMP1 + trail 3 ATR | +0.24 | +0.26 | +0.25 | 331 | 40.2% |
| AMP1 + trail 5 ATR | +0.22 | +0.49 | +0.33 | 298 | 39.3% |
| half 2R, rest AMP1+BE | +0.33 | +0.58 | +0.43 | 235 | 42.1% |
| half 3R, rest AMP1+BE | +0.57 | +0.72 | +0.63 | 226 | 37.6% |
| AMP1, time stop 3 spans | +0.65 | +1.01 | +0.78 | 217 | 29.0% |
| AMP1, time stop 10 spans | +0.61 | +0.98 | +0.75 | 212 | 26.4% |

**Not one alternative beats the measured move.** The best on calibration is the
3-span time stop at +0.65R against +0.63R — a two-hundredth of an R, inside noise
several times over, and I am not adopting it. It also transfers as noise would
(+1.01 vs +0.98) and gains nothing anywhere except WTI, which has failed seven
sections and is already a candidate for exclusion.

The `win%` column is not comparable across families. A breakeven exit scores exactly
0.00R, which counts as neither a win nor a loss, so `BE at 1R` shows 15.6% wins while
being *more* likely than baseline to avoid a full stop. Mean R is the only figure
that means the same thing in every row.

**Why the excursion in 8.21 is a trap.** The rule that banks it — `fixed 1R` — has by
far the best hit rate in the table, **60.8%**, and by far the worst return, +0.22R.
The whole distribution is one-sided: the top decile carries the result and every rule
that clips it (a fixed target, a trail, a breakeven stop, a partial) converts real
tail into a higher win rate and less money. The trailing stops are the sharpest
demonstration, a 2-ATR trail lifts hit rate to 45.5% and cuts return to +0.18R. This
is the same asymmetry the user identified in 8.24, arriving from the opposite side:
there it said don't fear a low hit rate, here it says don't buy one.

**The other direction.** Every rule above shortens the trade, so "AMP1 wins" could
have meant only "AMP1 beats cutting it short". Sweeping the target distance itself,
with 10,000-resample bootstraps of the difference:

| target | n | mean R | total R | Δ mean | 95% CI of difference | P(better) |
|---|---|---|---|---|---|---|
| 0.50 × AMP1 | 248 | +0.49 | 121.2 | −0.27 | [−0.82, +0.25] | 16.2% |
| 0.75 × AMP1 | 233 | +0.56 | 129.9 | −0.20 | [−0.79, +0.37] | 25.3% |
| **1.00 × AMP1** | **212** | **+0.76** | **161.2** | — | — | — |
| 1.25 × AMP1 | 191 | +0.95 | 182.1 | +0.19 | [−0.55, +0.92] | 69.3% |
| 1.50 × AMP1 | 178 | +0.86 | 153.3 | +0.10 | [−0.68, +0.94] | 59.9% |
| 2.00 × AMP1 | 162 | +0.81 | 131.4 | +0.05 | [−0.83, +1.02] | 53.2% |
| 3.00 × AMP1 | 129 | +1.10 | 142.5 | +0.34 | [−0.89, +1.78] | 68.4% |

**Every interval straddles zero.** Shorter than the measured move is consistently
worse and longer is flat-to-noisy — 1.5 and 2.0 dip below 1.25 and 3.0 rises again,
which is the shape of sampling noise, not of a payoff curve. Mean R also flatters
the long targets: 3× AMP1 earns the most per trade and less in total (142.5 vs 161.2)
because far fewer trades ever resolve. **The measured move cannot be beaten in either
direction on this data**, which is the strongest evidence yet that `AMP1` is a real
feature of the pattern rather than an arbitrary convention inherited from Hunt — the
only quantity in the whole study that came from doctrine [D] and then survived being
optimised against.

The 8.23 shift-null was re-run under the best calibration rule and is unchanged:
+0.75R against +0.09 ± 0.17, **100th percentile pooled**. The edge is still coming
from where the funnel sits, not from how the trade is managed.

**Verdict: keep the exit exactly as it is.** Three selection ideas (8.20's rank,
8.24's reward:risk, 8.25's ATR floor) and now fourteen exit rules have all failed to
add anything to detection plus the direction gate. That is four independent attempts
to improve the system from the outside, all null. The remaining unknown before any
live decision is costs and slippage against a fill that lands a median of 1 bar after
`RL3.confirm` — and given how little slack the exit turned out to have, that is now
the question most likely to decide whether this is tradeable.

### 8.27 Costs — the spread is irrelevant, the financing is not

`scripts/hvf_v2_mef_costs.py`, `scripts/hvf_v2_mef_carry.py`

Everything from 8.22 to 8.26 assumed a fill at the trigger price with zero spread,
zero commission and zero slippage. 8.26 made that assumption more dangerous rather
than less: the exit turned out to have no slack in it at all, so there is nothing in
the trade management to absorb a bad fill. Broker is IC Markets [C].

Rather than plug one spread number in and get one answer, the question is inverted:
**how much round-trip cost does each instrument absorb before mean R reaches zero?**
That is a number checkable against a spec sheet instead of guessed at.

| chart | n | median price | median risk | risk % of price | breakeven round trip | published cost | cost as % of risk |
|---|---|---|---|---|---|---|---|
| GoldCFD 2h | 40 | 2,628 | 23.94 | 0.83% | **39.89** | ~0.70 | 2.9% |
| BTCUSD 1h `T` | 49 | 61,779 | 1,335.30 | 2.24% | **893.77** | ~6.46 | 0.5% |
| XAUEUR 1h `T` | 29 | 2,999 | 35.92 | 1.12% | **40.52** | ~3.27 | 9.1% |
| USDJPY 4h | 43 | 148.19 | 0.922 | 0.62% | **0.5045** | ~0.002 | 0.2% |

Costs are charged as `net_R = gross_R − C / risk`. Published cost is IC Markets'
blended average spread plus $7 round-turn commission per standard lot [I — their
own spec sheets, not measured in our terminal].

**The round trip is a rounding error.** Gold absorbs $39.89 an ounce before the edge
is gone and costs about $0.70; that is a 57× margin. The reason is structural rather
than lucky: an HVF stop sits outside the whole sixth pivot, which on this data is
0.6%–2.2% of price, and no retail spread is a meaningful fraction of a move that
size. This is the first cost result in the study that the pattern's own geometry
guarantees rather than the sample happening to allow.

| chart | 0% | 1% | 2% | 5% | 10% | 20% | 30% |
|---|---|---|---|---|---|---|---|
| GoldCFD 2h | 1.72 | 1.71 | 1.70 | 1.67 | 1.62 | 1.52 | 1.42 |
| BTCUSD 1h `T` | 0.85 | 0.84 | 0.83 | 0.80 | 0.75 | 0.65 | 0.55 |
| XAUEUR 1h `T` | 1.22 | 1.21 | 1.20 | 1.17 | 1.12 | 1.02 | 0.92 |
| USDJPY 4h | 0.55 | 0.54 | 0.53 | 0.50 | 0.45 | 0.35 | 0.25 |

**Fill quality.** Replacing the trigger fill with the next bar's OPEN — the
pessimistic case for a resting order at a level price is actively moving through —
costs 0.07R on gold, 0.12R on BTC and *gains* 0.02R on XAUEUR. It also drops 2–7
trades per chart that gapped clean through the stop before they could be entered.
Real but small, and not directional enough to redesign the entry around.

**Financing is the actual cost, and it was nearly missed.** A round trip is charged
once; financing is charged every night, on notional, and notional here is 45×–120×
the trade's own risk. That leverage inverts the intuition — a rate that looks small
per year is large per R per day.

| chart | notional / risk | median hold | mean hold | R lost / day | mean drag | gross → net |
|---|---|---|---|---|---|---|
| GoldCFD 2h | 120.5 | 6.2 d | 12.3 d | 0.023 | 0.27R | 1.72 → **1.45** |
| BTCUSD 1h `T` | 44.7 | 2.5 d | 9.8 d | 0.024 | 0.24R | 0.85 → **0.61** |
| XAUEUR 1h `T` | 89.1 | 3.9 d | 23.5 d | 0.017 | 0.31R | 1.22 → **0.91** |

Crypto financing is published at −20%/yr on notional, tripled Fridays [I]. Gold is
not published, so it is swept across the 4%–10%/yr implied by broker swap tables at
current prices: gold nets 1.57R / 1.45R / 1.34R at 4% / 7% / 10%, BTC nets
0.67R / 0.61R / 0.55R at 15% / 20% / 25%. **The conclusion is rate-insensitive** —
no plausible financing rate takes either instrument near zero.

**But note where the drag lands.** Median hold is 2.5–6.2 days and mean hold is
9.8–23.5, so the distribution is long-tailed, and financing scales with time held.
It therefore taxes precisely the long winners that 8.26 showed carry the entire
result. Financing costs BTC 28% of its gross edge while costing the median trade
only 0.05R. This is the one cost that is *not* a rounding error and the one that
argues, weakly, for preferring the faster instrument at equal edge.

**Verdict: costs do not kill this.** The unknown flagged at the end of 8.26 is now
closed — gold nets ~1.45R and BTC ~0.61R after realistic spread, commission,
pessimistic fills and financing. Two figures remain estimates from published sheets
rather than measurements: the live spread during the hours we actually trade, and
the current gold swap line. Both should be read out of the terminal before sizing,
and neither is close enough to a threshold to change the decision.

### 8.28 Two details from doctrine — the stop buffer and the TP ladder

`scripts/hvf_v2_mef_doctrine.py`

The user described the pattern as three waves compressing into a funnel, then a
move back with the same force and length for "TP1, TP2, etc.", with the stop "just
outside the tiny funnel". Two things there are not what 8.26 tested, and both are
Hunt's own description rather than my invention — which makes them the strongest
remaining candidates for something the implementation got wrong.

**A. The stop sits *at* the sixth pivot, not outside it.** There is no buffer
anywhere in the implementation. 8.25 rejected a minimum stop distance in ATR units,
but that is a different object — it filters setups whose stop is too tight, it does
not move the stop. 8.27 gave a fresh reason to look: 2–7 trades per chart gapped
clean through the stop.

| stop | calib mean R | held-out mean R | all 8 | n | win% |
|---|---|---|---|---|---|
| **at 6th pivot (baseline)** | **+0.63** | **+0.98** | **+0.76** | 212 | 26.4% |
| +5% of risk beyond | +0.58 | +0.90 | +0.70 | 208 | 26.4% |
| +10% of risk beyond | +0.57 | +0.85 | +0.68 | 205 | 27.3% |
| +20% of risk beyond | +0.45 | +0.76 | +0.57 | 195 | 27.7% |
| +33% of risk beyond | +0.52 | +0.72 | +0.59 | 187 | 30.5% |
| +50% of risk beyond | +0.59 | +0.76 | +0.65 | 176 | 34.7% |
| +0.25 ATR14 beyond | +0.53 | +0.88 | +0.67 | 200 | 27.5% |
| +0.50 ATR14 beyond | +0.52 | +0.68 | +0.58 | 194 | 28.9% |
| +1.00 ATR14 beyond | +0.54 | +0.71 | +0.61 | 170 | 32.9% |

**The baseline wins outright — every buffer is worse on calibration and worse
held-out.** No selection step was even needed. And the shape is 8.26's trap again,
arriving from a third direction: widening the stop lifts win rate monotonically from
26.4% to 34.7% while mean R falls, because a buffer costs R on *every* winner to
rescue *some* losers. The gapped-through stops 8.27 found are real but they are not
worth what it costs to avoid them.

This is now the third independent confirmation that the sixth pivot is a real level
rather than a convention: 8.25 said don't filter on it, 8.26 said don't move it
after entry, 8.28 says don't pad it before entry.

**B. Partials, isolated from the breakeven move.** 8.26 concluded partials lose, but
every partial it tested *also* moved the stop to breakeven — and the breakeven move
is independently the thing 8.26 blamed for clipping the tail. So a ladder with the
stop left alone had never actually been measured. That is what "TP1, TP2" describes.

| ladder | calib mean R | held-out mean R | all 8 | n | win% |
|---|---|---|---|---|---|
| **all at 1× AMP1 (baseline)** | **+0.63** | **+0.98** | **+0.76** | 212 | 26.4% |
| half 1×, half 1.5× | +0.77 | +0.74 | +0.76 | 178 | 25.3% |
| half 1×, half 2× | +0.61 | +0.67 | +0.63 | 162 | 22.8% |
| half 1×, half 3× | +0.67 | +1.13 | +0.83 | 129 | 23.3% |
| thirds 1× / 2× / 3× | +0.72 | +1.08 | +0.84 | 129 | 23.3% |
| thirds 1× / 1.5× / 2× | +0.60 | +0.66 | +0.62 | 162 | 22.8% |
| quarter 1×, ¾ at 2× | +0.75 | +0.67 | +0.72 | 162 | 21.6% |
| ¾ at 1×, quarter 2× | +0.48 | +0.66 | +0.54 | 162 | 22.8% |

**Rejected by the pre-committed protocol.** The calibration winner is `half 1×, half
1.5×` at +0.77R, and it does not transfer: +0.74R held-out against the baseline's
+0.98R. Choose honestly and you choose wrong.

The ladder family is nonetheless *not* harmful the way the buffer is, and two rows
beat the baseline pooled — `thirds 1×/2×/3×` at +0.84R and `half 1×, half 3×` at
+0.83R. Both are declined, for reasons that were already on the record before this
section ran: they are not what calibration selected, so taking them is hindsight; n
falls to 129; and 8.26's target sweep already put a wide zero-straddling CI on
everything at 3× AMP1. The consistent signal across both tables is that the long leg
carries the result — which is 8.26's finding again, not a new one.

**Verdict: keep the exit exactly as it is, for the sixth time.** Detection plus the
direction gate plus entry/stop/target at the funnel's own levels. Six independent
attempts to improve on it from outside — 8.20's rank, 8.24's reward:risk, 8.25's ATR
floor, 8.26's fourteen exit rules, and now a stop buffer and a TP ladder — have all
returned null. **The rule set is frozen.**

### 8.29 The box — the last hindsight, and what removing it costs

`scripts/hvf_v2_mef_universalbox.py`, `scripts/hvf_v2_mef_universalnull.py`

The box size was the only input still chosen by knowing the answer. 8.14 picked it
per chart as "the coarsest box that still reproduces Hunt's funnel" — eight numbers
fitted to eight charts, 0.4652% to 3.2919% — and it sits upstream of everything else
in the study.

The USDJPY 1W chart displays the setting directly: **`Box Size 0.5 %`, `Source H/L`**
[D]. A single universal constant, from the source. My value on that same chart is
3.2919%, 6.6× coarser.

**Detection at a universal 0.5% matches 7 of 8** — fib errors 0.003–0.007 against a
`PASS_FIB` of 0.02, a 3–7× margin. The sole failure is WTI at 0.032, which has now
failed eight consecutive sections. One constant reproduces almost every funnel Hunt
drew.

**The backtest does not survive it intact.**

| variant | calib | held-out (blind) | all 8 | n |
|---|---|---|---|---|
| hindsight per-chart | +0.63 | **+0.98** | **+0.76** | 212 |
| **universal 0.50%** | **+0.65** | +0.28 | +0.51 | 309 |
| universal 0.4652% | +0.42 | +0.72 | +0.53 | 314 |
| universal 1.00% | +0.23 | +0.31 | +0.26 | 228 |

Calibration is unchanged (+0.63 → +0.65); the held-out figure collapses. That
asymmetry is diagnostic. The per-chart box was fitted to Hunt's drawing **on each
chart, including the two pre-committed held-out ones** — so BTCUSD and XAUEUR were
never fully blind, and the +0.98R quoted since 8.22 was partly buying its own
answer. **8.4's held-out protocol was violated upstream of the point where it was
enforced.** Every held-out figure in 8.22–8.28 inherits this and should be read as
optimistic.

**Dispersion tells the same story from the other side.**

| chart | hindsight | universal 0.50% | delta | cands |
|---|---|---|---|---|
| GoldCFD 2h | +1.72 | **+1.57** | −0.15 | 2.0× |
| BTCUSD 1h `T` | +0.85 | +0.37 | −0.47 | 11.7× |
| XAU/XAG 8h | −0.74 | +0.32 | **+1.06** | 20.4× |
| USDJPY 4h | +0.55 | +0.38 | −0.17 | 0.8× |
| USDJPY 1W | +1.62 (n=2) | +0.11 (n=7) | −1.50 | 14.4× |
| WTI 18h | −0.07 | +0.33 | **+0.41** | 1.1× |
| XAUEUR 1h `T` | +1.22 | +0.18 | −1.04 | 5.7× |
| HYG 4h | no trades | −1.00 (n=1) | — | 6.0× |

Under the universal box every chart with meaningful n is positive, including the two
that had failed everything. The fitted box gave a −0.74 to +1.72 spread; the honest
one gives a narrow, unspectacular, uniformly positive band. Extreme dispersion
across instruments that should behave alike is what fitting looks like; uniformity
is what a real, modest edge looks like.

**The shift-null, re-run under the universal box:**

| chart | n | real | null mean | null sd | pctile |
|---|---|---|---|---|---|
| **GoldCFD 2h** | 50 | **+1.57** | +0.42 | 0.41 | **99.0%** |
| USDJPY 1W | 7 | +0.11 | +0.12 | 1.21 | 84.0% |
| BTCUSD 1h `T` | 66 | +0.37 | +0.10 | 0.29 | 83.5% |
| XAU/XAG 8h | 52 | +0.32 | +0.05 | 0.39 | 77.5% |
| USDJPY 4h | 43 | +0.38 | +0.09 | 0.50 | 75.0% |
| WTI 18h | 35 | +0.33 | +0.06 | 0.77 | 75.0% |
| XAUEUR 1h `T` | 55 | +0.18 | +0.48 | 0.37 | **22.0%** |
| HYG 4h | 1 | −1.00 | −0.01 | 0.26 | 0.0% |
| **POOLED** | **309** | **+0.51** | **+0.20** | **0.17** | **95.0%** |

Pooled survives at the **95th** percentile rather than 8.23's 100th — positive but
no longer overwhelming. Two things deserve stating plainly. The null mean is **+0.20,
not zero**, so of the +0.51R only about +0.31R is attributable to *where* the funnel
sits; the remainder comes from the direction gate and risk geometry, which 8.22
established is real edge but is a different claim. And **XAUEUR now fails outright at
the 22nd percentile** — worse than shifting it — having scored 77.5th under its
fitted box.

**What holds up is gold.** +1.57R against a null of +0.42 ± 0.41 at the **99th
percentile**, with the smallest box change of any chart (2.0× the candidates, versus
11.7× for BTC and 20.4× for XAU/XAG) — gold's fitted box was already close to
Hunt's stated 0.5%, so gold is the one instrument whose result never depended on the
leak. It is nearly unchanged (1.72 → 1.57) precisely because there was little to
remove.

**Verdict: adopt the universal 0.5% box [D] and drop the per-chart table.** It is
parameter-free, sourced from Hunt's own tool, reproduces 7 of 8 funnels, and removes
the last hindsight in the system. The cost is a third of the headline return and the
credibility of every held-out figure prior to this section — both of which were not
ours to keep. The honest pooled number is **+0.51R at the 95th percentile**, and the
honest single-instrument number is **gold at +1.57R and the 99th**.

### 8.30 Out-of-sample in time — the strategy does not survive [V]

`scripts/hvf_v2_mef_oos.py`. Everything from §8.22–§8.29 was measured on
2023-01-01 onward. This section runs the frozen rule set — universal 0.50% box
(§8.29), 8.19 direction gate, top-3/month, AMP1 measured move, hard stop at the
6th pivot — on the years *before* that cut. No parameter was refitted. `FIT`
(§8.20) is hardcoded from Hunt's own eight funnels, not from returns, so it
carries across unchanged.

**Data-quality correction first.** A naive run reported gold from 2000 and BTC
from 2011 with a pooled +0.37R, and that was wrong. These H1 source files carry
**daily** bars in their early years — gold has ~260 rows/year before 2016 where
a 2h frame expects ~4,380; BTC ~260/year before 2017. Sixteen of gold's
twenty-three "years" were junk resolution. The table below is restricted to the
genuinely dense era per chart, which is the only honest blind window available:

| chart | span | n | win% | mean R | total R | PF | null mean | pctile | /yr |
|---|---|---|---|---|---|---|---|---|---|
| GoldCFD 2h | 2016-01..2022-12 | 116 | 26.7% | **+0.31** | 35.9 | 1.42 | 0.17 | **74.0%** | 16.6 |
| BTCUSD 1h | 2017-01..2022-12 | 106 | 14.2% | **0.00** | 0.0 | 1.00 | 0.16 | **26.5%** | 17.7 |
| XAU/XAG 8h | 2016-01..2022-12 | 92 | 18.5% | +0.06 | 5.7 | 1.08 | 0.25 | 37.0% | 13.2 |
| USDJPY 4h | 2011-01..2022-12 | 116 | 17.2% | −0.10 | −11.9 | 0.88 | 0.06 | 34.0% | 9.7 |
| WTI 18h | 2017-01..2022-12 | 32 | 18.8% | +1.13 | 36.2 | 2.39 | 0.33 | 87.0% | 5.3 |
| XAUEUR 1h | 2016-01..2022-12 | 94 | 26.6% | +0.54 | 51.0 | 1.74 | 0.22 | 90.0% | 13.5 |
| **POOLED** | | **556** | | **+0.21** | | | 0.18 | **57.5%** | |

`pctile` is the real result's position in that chart's own 200-seed shift-null
(§8.23). The bar is the 95th; nothing clears it.

**Read against the pre-committed in-sample benchmarks (§8.29b):**

- Gold was the whole case for building: **+1.57R at the 99th percentile**
  in-sample. Out-of-sample it is **+0.31R at the 74th** — inside its own null.
  Seven years and 116 trades say the 2023–2026 figure was regime, not rule.
- BTC returns **exactly 0.00R**, below its null mean, at the 26.5th percentile.
- Pooled falls from +0.51R at the 95th to **+0.21R at the 57.5th** — i.e. the
  full rule set on 556 blind trades is indistinguishable from randomly relocating
  the same trades in time.

**The decisive detail is the sign of the cross-period correlation.** Ranking the
six charts by in-sample percentile against out-of-sample percentile gives
Spearman **ρ = −0.52** (mean R: ρ = −0.43). The two charts that look best in the
blind window — WTI (87th) and XAUEUR (90th) — are precisely the two that failed
in-sample (WTI negative under the hindsight box for eight sections; XAUEUR at
the 22nd percentile under the universal box). Per-instrument performance does not
merely fail to persist, it *anti-persists*. That is the signature of noise being
re-sorted, not of an edge with varying strength. It also removes any option to
salvage the result by trading "the good instruments": there is no stable set.

**Conclusion — no deployable edge. [V]**

Attribution across the whole programme now reads: MEF detection is real and
parameter-free (§8.11, 8/8); the direction gate is real (§8.19); the 0.5% box is
Hunt's own stated setting and correct (§8.29). Everything downstream of that —
§8.20 rank, reward:risk, ATR floor, fourteen exit rules (§8.26), stop buffer and
TP ladder (§8.28) — was null. §8.29 then showed the per-chart box had leaked
hindsight into every prior held-out figure, and §8.30 shows what remains does not
survive contact with unseen years.

The pattern Hunt draws is detectable and his geometry is reproducible. What is
not established is that trading it makes money. The honest position is that
eight sections of null results, one leak, and an anti-correlated out-of-sample
add up to a strategy that should not be built as specified.

**What would change this verdict**, in order of cost:
1. Genuine tick or minute data pre-2016 for gold, so the blind window is longer
   than six years and the 116-trade sample stops being the binding constraint.
2. A selection rule that is *causal and defensible* rather than fitted — the
   consistent failure mode has been that every selector works in-sample and
   transfers at zero. Detection is not the bottleneck; picking which funnel to
   trade is, and nothing tried has beaten "all of them".
3. Forward paper-trading gold 2h on the frozen rules. ~17 setups/year means a
   year buys ~17 trades — too slow to resolve +0.31 vs 0.00.

None of these is a reason to place live capital now.

### 8.31 The target geometry was wrong — three waves, not one [V]

`scripts/hvf_v2_mef_waves.py`. Two new USD/KRW panels (2h and 1M) print Entry,
Stop, Target and RRR together, which is enough to solve the projection exactly.
Every target in §8.22–§8.30 was placed incorrectly.

**The correct construction.** The six pivots are better understood as **three
waves** — H1→L1, H2→L2, H3→L3 — of contracting amplitude. Each wave is projected
from **C, the centre of the smallest funnel**, not from the entry:

```
C   = (H3 + L3) / 2              # midpoint of the tip; entry and stop straddle it
TP1 = C + d * |H3 - L3|          # = C + risk
TP2 = C + d * |H2 - L2|
TP3 = C + d * |H1 - L1|          # = C + AMP1; this is the panel's "Target"
```

Verified on USD/KRW 2h (fibs 0.86/0.12/0.57/0.38, entry 1484.28, stop 1474.62):

| level | computed | printed on chart | in R |
|---|---|---|---|
| TP1 | 1489.11 | **1489.11** | +0.50 |
| TP2 | 1517.07 | 1517.14 | +3.39 |
| TP3 | 1530.29 | **1530.30** | +4.76 |

C itself (1479.45) is drawn as its own line on the later panel — the tool plots
the projection anchor. RRR reproduces exactly: (1530.29−1484.28)/9.66 = 4.76. [V]

**TP1 is always exactly +0.5R.** Entry sits at the top of the tip, C + wave3/2,
while TP1 projects the *full* tip from C. So TP1 − entry = risk/2 identically,
on every HVF setup. That is the structural breakeven trigger. [V]

**Projection is linear or log**, per the tool's own `Projection:` field. The
USD/KRW 1M panel uses Log: solving in log space gives an implied fib span of
0.238 against a displayed 0.24, and reproduces RRR 5.64 exactly. Linear would
have given 2286.9 against an actual 2740.15. At intraday scale the two agree to
~0.01%, so this matters only on multi-year frames. [V]

**What §8.22–§8.30 got wrong:** target anchored at entry rather than C, making
it half a tip-width — **exactly 0.5R** — too far on every trade, 9.5%–25.5% of
the target distance. And no TP1, no TP2, no breakeven move. §8.26's fourteen
exit rules and §8.28's ladders were all specified as multiples of AMP1 from
entry, so **the actual HVF ladder was never among the variants tested**.

**Re-run of §8.29/§8.30 with the corrected exits.** Same frozen detection,
direction gate, universal 0.50% box and top-3/month; only the exit changes.

| exit model | IS pooled | blind pooled | blind pctile | ρ(IS, blind) |
|---|---|---|---|---|
| legacy — entry+AMP1, hard stop | +0.51 | +0.23 | 65.5% | **−0.66** |
| TP3 only — C+AMP1, hard stop | +0.51 | +0.19 | — | **−0.66** |
| TP3 + breakeven at +0.5R | +0.35 | **+0.23** | — | **+0.61** |
| thirds TP1/TP2/TP3 + breakeven | +0.22 | +0.11 | **87.0%** | **+0.49** |

**The corrected exit does not raise returns.** Trading it Hunt's way — thirds at
each target, stop to breakeven once TP1 trades — gives a **67.2%** blind win rate
and the **worst** mean R (+0.11 vs +0.23). This is §8.26's finding for the third
time: banking early converts winners to scratches faster than it saves losers.
Gold falls from +0.31R (74th pctile) to +0.04R (34th).

**Two things do improve, and they pull in the opposite direction:**

1. The **shift-null collapses** under the ladder, 0.18 → 0.06 pooled. The legacy
   result was substantially "a small-stop trade in a trending instrument makes
   money wherever you put it"; the breakeven stop removes most of that free ride.
   So the ladder's +0.11R is *more* attributable to funnel location than the
   legacy +0.23R is — 87.0th percentile vs 65.5th, though still short of 95.
2. The **sign of cross-period persistence flips**. Both models carrying a
   breakeven stop persist positively (ρ +0.61, +0.49); both without persist
   negatively (ρ −0.66). This is the §8.30 verdict's central evidence reversing.

**But (2) is not established. [I]** Six charts, p = 0.16–0.33. A 6-point Spearman
cannot separate −0.66 from +0.61 at any usable confidence, and with four models
falling into two groups the grouping itself could be chance. It is a reason to
extend the chart set, not a result.

**Standing verdict.** §8.30's "no deployable edge" was reached on a materially
wrong exit model and should not be cited as-is. The corrected picture is *not*
better in returns — it is worse — but it is better in attribution, and the one
piece of evidence that made §8.30 decisive (anti-persistence) is exit-dependent
and therefore not decisive. The honest position is now **unresolved rather than
negative**, and the binding constraint is the six-chart sample, not the rules.

**Next test that would actually settle it:** more instruments. The persistence
question needs ~20 charts, not 6. Everything else — costs, financing, detection,
the box — is already closed.

### 8.32 The RRR band as a selector — improves the null margin, still short of significance [V]

Script: `scripts/hvf_v2_mef_rrrband.py`. Blind years only (pre-2023, per-chart `START` from
§8.30), legacy exit, MEF detection, direction gate, box 0.5%. `NSEED = 200` shift-null seeds
per chart per band. Band is applied to the candidate pool *before* `top()` selection, so it
is a genuine pre-entry filter, not a post-hoc slice of the trade list.

RRR here is TP3 in R: `1/(fib_H3 - fib_L3) - 0.5` (§8.31 geometry).

```
band     chart            n    win%   meanR    null   pctile
none     GoldCFD 2h     116   26.7%    0.31    0.17    74.0%
none     BTCUSD 1h      106   14.2%    0.00    0.16    26.5%
none     XAU/XAG 8h      92   18.5%    0.06    0.25    37.0%
none     USDJPY 4h      116   17.2%   -0.10    0.06    34.0%
none     WTI 18h         32   18.8%    1.13    0.33    87.0%
none     XAUEUR 1h       94   26.6%    0.54    0.22    90.0%
none     POOLED         556            0.21    0.18    57.5%

<=4R     GoldCFD 2h      82   30.5%    0.28    0.15    72.5%
<=4R     BTCUSD 1h       90   24.4%    0.17    0.00    82.0%
<=4R     XAU/XAG 8h      52   32.7%    0.48    0.06    91.0%
<=4R     USDJPY 4h       69   21.7%   -0.11    0.07    27.5%
<=4R     WTI 18h         31   19.4%   -0.13    0.28    13.5%
<=4R     XAUEUR 1h       77   31.2%    0.35    0.13    82.0%
<=4R     POOLED         401            0.19    0.10    83.0%
```

**What the band actually does.** Pooled mean R does *not* improve: 0.21 → 0.19. What improves
is the shift-null, 0.18 → 0.10, and with it the percentile, 57.5 → 83.0. The band is not
finding better trades; it is discarding trades whose payoff a randomly-relocated funnel of the
same shape collects just as well. That is still a real finding — it means the ≤4R region is
where structure contributes and the >4R region is where the funnel is decoration — but it is
an argument about attribution, not about expectancy.

Win rate rises on every chart (pooled ~20% → ~27%), exactly as §8.31's bucketing predicted:
the tight tips that manufacture 10:1 put the stop inside the oscillation.

**Why it is still not a green light.**

1. **83rd percentile, not 95th.** The pre-registered bar (§8.23) is unchanged and unmet. One
   in six shuffles of the pure-noise null still beats the live rule.
2. **It is not uniform.** Two charts improve sharply (BTC 26.5 → 82.0, XAU/XAG 37.0 → 91.0),
   two are flat (Gold 74.0 → 72.5, XAUEUR 90.0 → 82.0), one is unchanged and negative
   (USDJPY), and **WTI collapses 87.0 → 13.5** — the band removes only 1 of its 32 trades but
   that one carried its entire +1.13R. A filter whose pooled result depends on which single
   trade it happens to delete is not a filter, it is a coin.
3. **The lever is small.** ≤4R keeps 401 of 556 picks. On Gold it removed 34 of 116. This is a
   mild trim, and the pooled percentile it buys is inside the range that resampling six charts
   would produce anyway.
4. **Six charts.** As in §8.30 and §8.31, n=6 instruments is the binding constraint on every
   pooled statement in this document.

**Relation to the earlier bucketing.** §8.31's bucket table reported +0.295R over 143 trades
for a narrower 1.5–4R window against a 351-trade baseline; that ran over a different pick
pool. The figures above supersede it — same script, same pool, both bands, null included.

**Attribution ledger, updated.**

| component | verdict |
| --- | --- |
| MEF pivot detection | real (§8.24, 8/8) |
| Direction gate | real (§8.19) |
| 0.5% box | Hunt's own stated setting, not fitted (§8.29) |
| Three-wave exit + breakeven | lowers mean R, flips persistence positive (§8.31), unresolved |
| **RRR ≤ 4R band** | **improves null margin 57.5 → 83.0 pctile; does not reach 95th; WTI-fragile** |
| §8.20 rank, reward:risk, ATR floor, stop buffer, 14 exit rules, TP ladder | null |

**Status.** §8.30's "no deployable edge" remains withdrawn (§8.31), and this section does not
restore it in either direction. Two independent post-§8.30 findings — the corrected exit
geometry and the RRR band — both move the evidence the same way without either one clearing
the bar. The honest position is *unresolved on six charts*, and the next thing that can change
it is more instruments, not more rules. See §11.

### 8.33 Financing against the blind gross — it does not kill it, it halves it [V]

Script: `scripts/hvf_v2_mef_carry_blind.py`. Blind years (pre-2023), MEF detection,
direction gate, 0.5% box, `top()` selection — identical pick set to §8.30/§8.32, and the
gross column reproduces them to the cent (legacy +0.21R, waves +0.11R pooled), which is the
check that the harness is the same one.

**Why §8.27 had to be re-asked.** §8.27 concluded "costs do not kill this" by setting a drag
of 0.24–0.31R against a gross of 1.72R (gold) and 0.85R (BTC). Both of those gross figures
came from the 2023–2026 in-sample window under the legacy exit, and §8.30 then showed the
blind gross is 0.19–0.31R while §8.31 showed the exit geometry was wrong. **Financing drag is
an absolute number of R, not a fraction of one.** 0.27R against 1.72R is 16%; the same 0.27R
against a blind +0.31R is the entire edge. The verdict was arithmetically correct and
substantively obsolete.

Two things modelled here that §8.27 could not model:

1. **Carry integrated over a decaying position.** Taking a third off at TP1 retires a third
   of the notional early, so the three-wave exit carries less. §8.27 charged a flat position.
2. **Per-trade integration** rather than mean-hold × rate. The hold distribution is long-tailed,
   and drag scales with time, so the mean of the product is not the product of the means.

Financing is charged on calendar days elapsed, `lev = |entry| / risk` marked at entry. Rates
are the §8.27 sweep: gold-like 4/7/10%/yr, BTC 15/20/25%, USDJPY 0/2/4%.

```
LEGACY exit                                    WAVES exit (thirds + breakeven)
chart        n  lev  medd  meand gross  drag   net  |   n  lev  medd  meand gross  drag   net
GoldCFD 2h 116  161   1.3    3.2  0.31  0.09  0.22  | 142  160   0.5    1.2  0.04  0.02  0.02
BTCUSD 1h  106  119   0.2    0.8  0.00  0.04 -0.04  | 115  117   0.1    0.4 -0.04  0.01 -0.05
USDJPY 4h  116  160   4.2   13.1 -0.10  0.10 -0.20  | 139  157   2.2    7.6  0.17  0.03  0.14
XAUEUR 1h   94  170   2.0    6.4  0.54  0.20  0.34  | 127  170   0.7    1.6  0.00  0.03 -0.03
XAU/XAG 8h  92  132   2.8    5.3  0.06  0.14 -0.07  | 112  132   1.3    2.7  0.22  0.04  0.18
WTI 18h     32   37   3.0   30.4  1.13  0.12  1.01  |  47   37   2.2   16.6  0.50  0.03  0.46
POOLED     556                    0.21  0.11  0.10  | 682                    0.11  0.03  0.08
```
(drag/net shown at the central rate; `medd`/`meand` are days held)

**Headline.** Financing takes **52% of the legacy edge** (0.21 → 0.10) and **27% of the
three-wave edge** (0.11 → 0.08). It does not produce a negative number pooled, so §8.27's
direction of travel survives — but "costs are a rounding error" does not. At a blind gross of
0.2R, carry is the second-largest term in the model.

**The three-wave exit is much cheaper to carry, and that is a real point in its favour.**
Median hold drops from 1.3 → 0.5 days on gold and 4.2 → 2.2 on USDJPY; pooled drag falls
0.11 → 0.03. Banking a third at TP1 and pulling the stop to breakeven gets most of the
position off the books quickly. So the two exits land in nearly the same place net
(+0.10 vs +0.08) from very different directions: legacy earns more and pays more, waves earns
less and pays almost nothing. **Waves is the more robust of the two** — its net is nearly
insensitive to the financing rate (0.03R spread across the whole 4–10% sweep, versus 0.08R
for legacy), and the rate is the input we are least sure of.

**Holds are far shorter than §8.27 reported** — gold median 1.3d here versus 6.2d there. The
two measure different windows (blind vs in-sample) and different pick sets (`top()` vs
top-3-by-rank), so this is not a contradiction, but it does mean §8.27's hold distribution
should not be quoted for the blind period.

**The instrument ranking does not survive the exit change, and this is the most important
line in the section.** Gold goes 0.31 → 0.04 gross; USDJPY goes −0.10 → +0.17; XAU/XAG goes
0.06 → 0.22; XAUEUR goes 0.54 → 0.00. Changing *only* the exit rule — leaving detection,
gate, box and pick set identical — completely reshuffles which instruments make money. That
is what a six-chart sample of noise looks like, and it is direct evidence against
`hvf-instrument-pick`'s "GoldCFD 2h ONLY" conclusion, which was reached under the legacy
exit and does not hold under the corrected one.

**Not modelled, and it matters at this gross.** Spread and commission are charged per leg, and
the waves exit has three legs plus an entry. §8.27's round-trip costs as a fraction of risk
were gold 2.9%, XAUEUR 9.1%, BTC 0.5%, USDJPY 0.2%. Against a waves gross of +0.04R on gold,
a ~0.03–0.06R three-leg spread bill is the whole number. So the gold waves cell above should
be read as *indistinguishable from zero after dealing costs*, not as +0.02R. The charts where
the waves exit still clears are USDJPY, XAU/XAG and WTI — none of which is the instrument
§8.29–§8.32 nominated.

**Verdict.** Financing is not a kill shot; it is a halving. The blind edge after carry is
+0.08 to +0.10R pooled, before per-leg dealing costs, at the 83rd percentile of the
shift-null (§8.32) where the bar is the 95th. That is not a deployable number — not because
any single test failed, but because a thin positive that halves under carry, reshuffles under
a change of exit rule, and never cleared its significance bar has no margin left to survive
the things still unmodelled. **Do not size this. The next step remains §11: more instruments
against the frozen spec, not more rules.**

### 8.34 How big a backtest would settle this — and why live trading never will [V]

Script: `scripts/hvf_v2_mef_power.py`. Trade-level dispersion of the **net** (post-financing,
§8.33) blind returns, inverted through the standard one-sided power formula at α=0.05,
power=0.90.

```
                       LEGACY                       WAVES
chart           n   net R      sd      n   net R      sd
GoldCFD 2h    116    0.22    2.28    142    0.02    0.89
BTCUSD 1h     106   -0.04    2.73    115   -0.05    0.92
USDJPY 4h     116   -0.20    2.08    139    0.14    1.40
XAUEUR 1h      94    0.34    3.09    127   -0.03    0.84
XAU/XAG 8h     92   -0.07    2.31    112    0.18    1.15
WTI 18h        32    1.01    5.84     47    0.46    1.97

                          LEGACY     WAVES
pooled net edge            0.101     0.079  R
trade-level sd             2.802     1.153  R
observed t (naive)          0.85      1.79   (need ~1.65)
design effect               2.29      3.13
trades needed (corrected)  15,129     5,706
=> INSTRUMENTS needed         163        50   (have 6)
```

**Neither is significant.** The waves exit's naive t=1.79 does clear 1.65, but HVF trades
overlap and cluster in regime, so they are not independent draws. Deflating by the design
effect gives an effective t of 1.79/√3.13 ≈ **1.01**. This is the same conclusion the
shift-null reached from a completely different direction (§8.32: 83rd percentile, bar is
95th), which is at least reassuring about the diagnosis.

**The three-wave exit cuts dispersion by 2.4×, and that is its real advantage.** sd falls
2.802 → 1.153 for a nearly unchanged net edge, so edge-per-unit-risk almost doubles
(0.036 → 0.069 per trade). §8.31 read the waves exit as *worse* because it looked only at
mean R. On a risk-adjusted basis it is much better, it costs a third as much to carry
(§8.33), and it needs **a third as many instruments to prove**. Every axis except raw mean R
prefers it. Trade it Hunt's way.

**Correction to §11 and to the running recommendation.** The figure quoted repeatedly as
"~20 instruments" was a guess and it was too low by 2.5×. At the observed net effect size,
settling this needs **~50 instruments** on the three-wave exit — 163 on the legacy one,
which is a further reason to drop legacy. The requirement scales as 1/effect², so it is very
sensitive: a true edge of 0.15R would need ~14 instruments, one of 0.05R would need ~125.
The point estimate is the planning number, not a promise.

**Live trading cannot settle this, and that is decisive for how to proceed.** The blind data
yields ~16 trades per instrument-year. Six instruments traded live produce ~96 trades/year,
against a 5,706-trade requirement — **roughly 60 years**. Even 50 instruments running live
would take ~7 years. A paper-trading or small-size "let's just see" phase is therefore not a
cheap experiment that resolves the question slowly; it resolves nothing on any horizon that
matters. **Backtesting is not the inferior substitute for live evidence here. It is the only
instrument that can answer the question at all.**

**Caveat on the design effect.** It is estimated from between- versus within-chart variance
on six charts, so it is itself a noisy statistic, and it is pulled upward by WTI (net +0.46R
on n=47). Treat 2–3× as the plausible range rather than 3.13 as a measurement.

**So: is another backtest worth running?** Not on these six charts — that adds no
information and is precisely the path that produced the old implementation's `MIN_RRR`
tuned on eighteen trades. The only backtest worth building is a **wider** one: expand the
instrument universe toward ~50 with genuine intraday history, run the spec frozen exactly as
it stands, and change nothing else. If that data cannot be assembled, the honest conclusion
is that the question is not answerable with the resources available and the strategy should
not be traded — not that it should be traded on six charts' worth of hope.

## 9. Open questions

### 9.1 AMP2 / the target ladder

Hunt's "AMP1" naming implies a ladder, and he confirms interim targets exist **[D]**.
Every chart carries a **second, dashed ray** below the solid target ray.

Weak evidence: the XTI Crude chart — quarantined because its entry and stop are occluded
by TradingView alert boxes — computes to `m = 1.977`, suspiciously close to exactly
**2 × AMP1**. Three legible dashed-ray readings give 0.77, 0.76 and 0.58 range-units past
the midpoint, which is not yet a rule.

**Resolution needs:** a chart where both the dashed ray and a clean entry/stop are
legible. Cheap to obtain if more screenshots exist.

### 9.2 Residual disagreements in the evidence

- **USDJPY 1W stop** — the two transcriptions disagree (143.483 vs 145.483; both appear
  as axis tags). The `m = 1` rule favours 145.483 (m = 1.017 vs 0.786) and so does the
  printed RRR (3.760 vs 2.748 against a printed 3.87), but **neither reproduces 3.87
  exactly**. Unresolved; excluded from the validation set.
- **Norway 3Y** — internally inconsistent under every model tested; RH3/RL3 are occluded
  by candles. Excluded.
- **US 10Y 3D** — the info panel is not rendered in the screenshot at all. No data.

### 9.3 Undetermined by any source

Restated for the record, because these are where we are designing rather than recovering:
the status state machine (§5), invalidation (§6), the Linear/Log threshold (§2.6), the
prior-trend test (§4.2), "slung" acceptance thresholds, and the pivot-detection
parameterisation (§4.1).

---

## 10. Why the previous attempt failed

Recorded so the same failure is not repeated. None of these are evidence against the
pattern.

1. **No prior-trend precondition.** The mandatory doctrinal filter was absent entirely,
   so the detector searched for triangles in chop — which Hunt's own paper disqualifies.
2. **Direction by array parity.** LONG and SHORT branches byte-identical; the same price
   region yielded "LONG" at offset `i` and an identical "SHORT" at offset `i+1`.
3. **A hidden 2.4× contraction requirement** smuggled in through the RRR gate (§3.2).
4. **Compound selectivity ~0.06** once the dual-sided convergence test, the 100-bar
   expiry, the ADX floor and the RRR gate were stacked — hence "~zero patterns".
5. **Threshold overfitting on a shrinking sample.** The git arc runs: relax filters twice
   to chase trade count, then tighten `MIN_RRR` 1.0 → 1.5 on the strength of an
   **18-trade** backtest (`fd78255`). Sample went 268 → 33 → 18.

**Reusable:** `zigzag.py`. **Bin:** the entire `_validate_pattern` rule stack.

*(Unrelated, spotted in passing: `WEDGE_MIN_TOUCHES = 2` makes `WEDGE_MIN_R_SQUARED = 0.65`
vacuous, since a 2-point regression always returns R² = 1.0 —
`wedge_detector.py:289-293`. Different strategy, worth its own ticket.)*

---

## 11. Proposed order of work

1. ~~Extend data coverage to the charted instruments.~~ **DONE 2026-08-03** — see §8.2.
   Acceptance sample went from 3 charts to 8.
2. Reimplement pivot detection (fixed-percentage ZigZag on H/L) and the 6-pivot search.
   **Not started — awaiting go-ahead.**
3. Validate the detector **against the charts themselves** — feed it the same
   instruments and periods and confirm it finds Hunt's structures with his fib values.
   This is the acceptance test the old implementation never had.
4. Only then measure performance, using the §8 contract, on Gold H1 first.
5. Compute the achievable sample size before interpreting any result (§7.1).

### 11.1 Two things step 3 must settle before it can be trusted

**Non-native timeframes.** Not one of Hunt's intraday charts is a native MT5 period —
they are 2h, 4h, 8h and 18h, all of which we must resample from H1. TradingView anchors
non-standard periods to the instrument's session start, so a different anchor shifts every
bar boundary and therefore every pivot. A near-miss on the acceptance test may be an
anchoring artifact rather than a wrong rule, so **sweep the anchor offset and report which
one reproduces Hunt's pivots** instead of assuming ours matches.

**Calibration is not validation.** The prior-trend precondition (§4.2) is the one rule we
could not recover from the panel, and the 8 reachable charts are labelled positives, so
they can be used to *fit* its threshold. That is legitimate — and it spends them. Once
used that way they cannot also serve as evidence the rule works, so step 4 must measure on
instruments and periods outside the calibration set, or we have only fitted the
screenshots. Decide which of the two jobs these 8 charts do **before** looking at a result.
