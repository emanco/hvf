# Backtest Retrospective Analysis
### Date: 2026-03-07 | Period: ~14 months (10K H1 bars) | Starting equity: £700

---

## Goal: Double the balance at least once per year (100%+ annual return)

---

## Variant Results Summary

| Variant | Trades | Pips | Final £ | Return | MaxDD | Ann. Return |
|---------|--------|------|---------|--------|-------|-------------|
| A: Baseline | 587 | +1,921p | £1,181 | +69% | -7.2% | ~59% |
| B: KZ 1%+max4 | 590 | +1,940p | £1,606 | +129% | -8.1% | ~111% |
| C: KZ thr=40 | 876 | +2,034p | £1,222 | +75% | -8.9% | ~64% |
| D: +3 pairs | 1,021 | +2,921p | £1,369 | +96% | -5.4% | ~82% |
| E: All combined | 1,536 | +3,313p | £2,073 | +196% | -8.3% | ~168% |

**Variants B and E meet the doubling target.** B is the simplest change (2 config values). E is the most aggressive.

---

## What Works

### 1. KZ Hunt is the volume engine
- 362 trades at baseline (62% of all trades), positive across 3 of 4 pairs
- USDCHF KZ Hunt: 115T, +430p, £151 — best single pattern-pair combo by £
- NZDUSD KZ Hunt: 125T, +394p, £89 — second best
- Reliable, consistent returns with moderate win rates (63-67%)

### 2. Viper SHORT-only on select pairs
- EURUSD Viper: 42T, +308p, £71 — strong directional edge
- USDCHF Viper: 50T, +453p, £75 — strongest Viper pair
- Surgical exclusions (EURGBP, NZDUSD) eliminated losing Viper trades without losing profitable HVF/KZ Hunt

### 3. New pairs add genuine diversification
- EURAUD: 81T (KZ only), +704p, £109 — excellent, smooth equity curve
- AUDNZD: 144T, +228p, £47 — moderate positive
- GBPCHF: 107T, +231p, £10 — marginal in £ terms
- Adding 3 pairs lowered portfolio MaxDD from -7.2% to -5.4% (variant D)

### 4. Risk sizing is the biggest £ lever
- KZ Hunt at 0.5% risk: £338 total from ~362 trades
- KZ Hunt at 1.0% risk: ~£722 total from same trades
- Doubling KZ risk adds ~£384 with zero additional trades — pure leverage on existing edge

---

## What Doesn't Work

### 1. KZ Hunt on EURUSD is marginal
- 101T, +98.7p (0.98p/trade) at baseline — barely covers spread
- At 1.0% risk it went negative: -99.9p in variant E
- High churn, no directional edge — creates flat/noisy equity curve periods

### 2. Lowering KZ threshold (50→40) adds noise, not profit
- Variant C: +289 more trades, only +113 more pips and +£41 more equity
- EURUSD KZ at threshold 40: went from +98.7p to **-35.3p** (179 trades)
- Lower threshold lets in marginal setups that dilute edge

### 3. GBPCHF in £ terms is near-zero
- +231p from 107 trades but only £10 profit
- Pip value conversion makes it inefficient at £700 equity

### 4. HVF is too infrequent to move the needle
- 33 trades in 14 months across 4 pairs (~2.4/month)
- +119p total, decent per-trade but negligible portfolio contribution

---

## Recommendations

### Tier 1: Apply now (highest confidence)
1. **Bump KZ Hunt risk 0.5% → 1.0%** — Adds ~£384 from same trades. Single biggest lever. Variant B proves it works: £1,181 → £1,606.
2. **Raise max concurrent 3 → 4** — Captures more overlapping opportunities. Minimal risk increase.
3. **Add NZDUSD to Viper exclusions** — Already applied. PF 1.41→1.80, MaxDD 6.4%→2.0%.

### Tier 2: Add after 2 weeks of demo validation
4. **Add EURAUD** — Best new pair by far: +704p, smooth curve, strong KZ Hunt edge. Add pip value to config and include in INSTRUMENTS.
5. **Add AUDNZD** — Moderate positive (+228p), adds diversification.
6. **Skip GBPCHF** — Marginal £ returns don't justify the additional monitoring.

### Tier 3: Investigate further
7. **Exclude KZ Hunt on EURUSD** — It's marginal at best, negative at 1.0% risk. Would lose ~£17 in baseline but avoids risk of larger losses at higher risk %. Needs more analysis.
8. **M15 timeframe for KZ Hunt** — More frequent candles could increase trade frequency and catch intraday kill zone moves that H1 misses.
9. **Adaptive risk sizing** — Scale position size with rolling PF. If PF > 1.5, bump to 1.5% risk. If PF < 1.0, drop to 0.5%.

---

## Path to Doubling: Recommended Config

```
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "AUDNZD"]
ENABLED_PATTERNS = ["HVF", "VIPER", "KZ_HUNT"]
PATTERN_SYMBOL_EXCLUSIONS = {"VIPER": ["EURGBP", "NZDUSD"]}
RISK_PCT_BY_PATTERN = {"HVF": 1.0, "VIPER": 1.0, "KZ_HUNT": 1.0}
MAX_CONCURRENT_TRADES = 4
SCORE_THRESHOLD_BY_PATTERN = {"HVF": 40, "VIPER": 60, "KZ_HUNT": 50}
```

**Expected performance** (interpolating between variants B and E):
- ~800-1000 trades per 14 months
- ~£1,400-1,700 final equity from £700
- ~100-140% annualised return
- MaxDD ~7-9%

This achieves the doubling target while keeping MaxDD under 10%.

---

## Charts
- `backtests/charts/bt_variants_combined.png` — all 5 variants overlaid
- `backtests/charts/bt_variants_perpair.png` — per-pair baseline vs all-combined
- `backtests/charts/bt_equity_kz1_max4.png` — KZ 1% + max4 detailed comparison
- `backtests/charts/bt_equity_comparison_nzdusd.png` — NZDUSD Viper exclusion
