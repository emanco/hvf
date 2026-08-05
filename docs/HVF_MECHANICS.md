# HVF — the mechanics

Hunt Volatility Funnel, as Francis Hunt trades it. This is the **canonical statement of
how the pattern works**: what it is, how it is measured, where the orders go. Read this
first, before touching anything else.

It is deliberately short and deliberately separate from
[`research/HVF_V2_SPEC.md`](research/HVF_V2_SPEC.md), which is a 2,700-line running
research log — every experiment, including the ones that failed and the conclusions that
were later withdrawn. **This file is the mechanics. That file is the evidence.** When
they disagree about how the pattern is *constructed*, this file wins; it is verified
against Hunt's own chart panels to the cent.

Nothing here is a claim that the strategy is profitable. See [Status](#status).

---

## 1. Context — it is a continuation pattern

HVF is not a reversal tool. It is what a trend does when it pauses. Price runs, exhausts,
coils into a contracting range, and the coil resolves **in the direction it was already
going**.

So the direction question is answered *outside* the funnel:

- **The larger timeframe picks the side.** Months to a year of trend. Up for the past
  year → long. Down → short.
- **The funnel picks the entry and the risk.** Nothing more.

A funnel resolving *against* the dominant trend does occur, but it is rare and needs
independent justification — a head and shoulders, a fundamental break — before it is
worth taking. Absent that, skip it. Trading a continuation pattern counter-trend is
taking the one setup the pattern is not describing.

Implementation note: this is §8.19's direction gate. Direction = sign of the move from
the last coarse pivot known at H1, measured at `box = k·AMP1/anchor_price`, k=1. Skip the
candidate when `sign(move) != d`. It is one of only three components that survived
attribution testing.

## 2. Structure — three waves, not six pivots

The six pivots are **three movements of decaying amplitude**, and reading them as six
points rather than three waves is the single easiest way to get this wrong.

| wave | pivots | what it is |
| --- | --- | --- |
| **Wave 1** | H1 → L1 | the widest swing — the old trend exhausting |
| **Wave 2** | H2 → L2 | narrower |
| **Wave 3** | H3 → L3 | the tightest — the tip of the funnel |

Each wave is a full oscillation. Each is smaller than the last. **That contraction is the
funnel** — volatility compressing toward a point.

Naming, bullish case: `H1` (fib 1.0), `RL1` (fib 0.0), then `RH2, RL2, RH3, RL3`.
Bearish is mirrored. `AMP1 = |H1.price − RL1.price|` — wave 1's amplitude, and the
quantity everything else is expressed against.

**Detection.** Each funnel pivot is the extreme of the window its two neighbours define
— the *mutual-extreme* rule (§8.24). It is parameter-free, causal, and finds Hunt's
structure on 8 of 8 catalogued charts. Pivots come from a fixed-percentage ZigZag on
highs/lows at **box = 0.5%**, which is Hunt's own stated setting, not something fitted
(§8.29). `zigzag_pct(frame, box)` takes a percentage.

## 3. The centre is the anchor — everything projects from C

**This is the key mechanic, and the one that was wrong in the code for months.**

> **C = the midpoint of the smallest funnel = (H3 + L3) / 2**

When the compression releases, price does not travel a fixed distance from where you
entered. It replays **each wave's full amplitude, measured from the centre of the coil**.
Each wave comes back with the same force it went in with.

```
TP1 = C + d · |H3 − L3|      (wave 3 — the tip's own reach)
TP2 = C + d · |H2 − L2|      (wave 2)
TP3 = C + d · |H1 − L1|      (wave 1 — the panel's "Target")
```

where `d = +1` long, `−1` short.

Geometrically: draw the line for a wave, then drag it so its base sits at C. Where the
tip lands is that wave's target. The fib levels printed on Hunt's panel are the same
thing expressed as ratios of wave 1.

**Do not anchor at entry.** Projecting from the entry price instead of C puts every
target exactly half an R too far, on every trade, in every direction. That error sat in
the backtests from §8.22 to §8.30 and invalidated the exit ladder those sections tested
(§8.31).

## 4. Entry, stop, risk

| | |
| --- | --- |
| **Entry** | the 5th pivot, `w[4]` — the far side of the tip |
| **Stop** | the 6th pivot, `w[5]` — *just outside* the tiny funnel |
| **Risk** | `|entry − stop|` = wave 3's amplitude = the height of the tip |

The stop is the smallest structure on the chart. That is the entire economic case: you
risk the compression and get paid the expansion.

### TP1 is always exactly +0.5R

Not approximately. Structurally, on every HVF setup that has ever existed:

```
entry = C + d · risk/2          (entry sits at the edge of the tip)
TP1   = C + d · risk            (TP1 projects the FULL wave 3 from C)
∴ entry → TP1 = risk/2          = +0.5R
```

This falls out of the construction, so it needs no measuring — and it is what makes TP1
the natural, non-arbitrary breakeven trigger.

### Reward:risk

`RRR = 1/(fib_H3 − fib_L3) − 0.5` for TP3.

RRR is **not a free parameter to maximise**. You can always manufacture 15:1 by finding a
tighter tip, but the stop then sits inside the range where price still oscillates and it
is simply taken out. Hunt's eight catalogued setups have a **median TP3 of 2.04R**
(range 1.46–4.76) — high, but nowhere near the extreme. Measurement agrees: below ~4R the
structure contributes, above ~6R it is decoration (§8.31, §8.32).

## 5. Management

1. Enter at the 5th pivot. Stop at the 6th.
2. **TP1 (+0.5R) — take a third. Move the stop to breakeven.** The trade can no longer
   lose.
3. **TP2 — take a third.** Let the rest run.
4. **TP3 — take the last third.**

The breakeven move at TP1 is what pays for holding to the far target without bleeding on
whipsaw. It also retires a third of the notional early, which matters for carry (§8.33).

## 6. Two details that bite

**Projection mode.** Hunt's panel prints `Projection: Linear` or `Log`. Intraday the two
agree to ~0.01% and it is irrelevant. On multi-year frames it is decisive: on the USD/KRW
monthly, linear projects 2286.9 where log gives the actual **2740.15**. Read the mode off
the panel; implement log for anything above weekly.

**Non-native timeframes.** Not one of Hunt's intraday charts is a native MT5 period —
2h, 4h, 8h, 18h, all resampled from H1. TradingView anchors non-standard periods to the
instrument's session start, so a different anchor shifts every bar boundary and therefore
every pivot. A near-miss when reproducing his pivots may be an anchoring artifact rather
than a wrong rule.

**Data resolution.** The H1 source files carry *daily* bars in their early years
(~260 rows/yr where the timeframe expects thousands). Genuinely dense history starts:
gold 2016, BTC 2017, XAU/XAG 2016, USDJPY 2011, WTI 2017, XAUEUR 2016. Never backtest
before those dates — see `START` in `scripts/hvf_v2_mef_waves.py`.

## 7. Worked example — USD/KRW 2h

Hunt's own panel, reproduced from the rules above. This is the acceptance test for any
implementation of the geometry.

| | projection | computed | printed on panel |
| --- | --- | --- | --- |
| C | (H3+L3)/2 | 1479.45 | 1479.45 *(drawn as a line)* |
| TP1 | C + wave 3 | 1489.11 | **1489.11** |
| TP2 | C + wave 2 | 1517.07 | 1517.14 |
| TP3 | C + wave 1 | 1530.29 | **1530.30** |
| RRR | | 4.76 | **4.76** |

On the same pair's monthly chart (`Projection: Log`), log-space gives an implied fib span
of 0.238 — the panel displays 0.24 — and RRR 5.64 exactly.

The red line on Hunt's charts is the stop loss.

---

## Status

**The mechanics above are settled. The pattern is real. Every trade built on it that has
been tested loses money. Verdict: NO GO** (§8.38, §8.39 — which RETRACT the §8.36/§8.37
"passed" verdict). Do not trade this live.

What has survived testing: MEF pivot detection (8/8), the direction gate, the 0.5% box
(Hunt's own setting), and this geometry (verified to the cent).

What is null: the §8.20 rank, a reward:risk filter, an ATR floor, a stop buffer, the 14
exit rules of §8.26, and the TP ladder as tested against entry.

**Where it stands (§8.38).** Run frozen against 79 instruments resembling Hunt's own
universe, entire history out-of-sample, honest fills, all costs charged, restricted to
picks whose entry is actually reachable:

| | R |
|---|---|
| mean net | **−0.175** |
| shift-null mean | −0.333 |
| **lift attributable to the funnel** | **+0.158** |
| t on the lift (N_eff 15.5) | **3.48** (bar 1.65) |
| instruments with **lift** > 0 | **65 / 79** |
| instruments with **net** > 0 | **17 / 79** |

Read both rows. The funnel carries real, strongly significant information — the largest
and most significant lift measured in the programme. And the strategy still loses money,
because entering on a breakout 0.5R beyond the anchor with a 1R stop at 61–75× leverage
bleeds more to fills than the pattern earns. **The problem is the expression, not the
detection.**

**Why the earlier verdict was wrong.** `simulate_detail` filled every level *at the
level*. A bar that opens through a level never offered that fill. Worse, **34.1% of picks
had the entry already breached at the arming bar** (`d·e_off ≤ 0` — for a long, the entry
sat *below* the close), so the model was buying below market: an impossible fill granted
free on a third of all trades. That was the edge. Cause is **ZigZag confirmation lag** —
the 6th pivot is not knowable until price has retraced by the box amount, by which time it
has often passed the entry.

**Two remedies were tested and both fail.** Refusing to chase gapped entries is
monotonically *worse* (−0.140 → −0.174 as the threshold tightens), so gapped entries are
not the bad trades. Smaller bars do not help: 4h nets −0.114 with a 30.1% entry-gap rate
against 3D's −0.148 and 41.6%. The entry sits ~0.5R above the anchor close, which is
inside one bar''s opening move at every timeframe tested.

**Do not tune the entry until it turns positive.** The lift is the asset. Any new
expression of it — limit entry at the funnel centre, a stop outside the second funnel, a
longer hold — is a new hypothesis needing its own pre-registered out-of-sample test.
§8.20''s rank, §8.26''s fourteen exit rules and §8.32''s RRR band all died exactly that way.

**Costs are fully modelled (§8.33, §8.37)** and are *not* what killed it. Spread is charged
on volume, not per leg — a round trip crosses it exactly once, so the earlier "pays it four
times" claim was wrong. LEV is 75× mean / 61× median (not the 117–170× from six intraday
charts), so 1bp of round-trip cost is 0.0061R against ~17bp of breakeven headroom.
Financing takes 27% of the three-wave edge.

**Procedural lesson.** Every rule was shift-null-tested; the assumption that a limit price
is obtainable never was. The fill model deserved the same scepticism as the entry rules.

## Verdict (§8.39)

**NO GO.** Every fill-honest measurement is negative: gap-aware run −0.140R, executable
subset −0.175R, and on held-out instruments −0.258R (breakout entry) and −0.400R (limit
entry at C). Net is negative on 73–79 of 79 instruments.

The limit-entry fix was well motivated — it removes the only gap-exposed leg — and it made
things **worse**, because moving the entry from `C + risk/2` to `C` halves the risk
distance, doubling leverage and therefore doubling spread and financing in R. Removing gap
exposure buys less than the leverage penalty costs.

The lift survives (positive in every cell, 57–65 of 79 instruments) but its magnitude moves
with simulator details (+0.158R at t 3.48 in one, +0.121R at t 1.61 in another, 0.75 on the
holdout). Real and small — not something to size positions from.

**The holdout is spent.** Any further hypothesis needs fresh instruments or a fresh period.
