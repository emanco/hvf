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
