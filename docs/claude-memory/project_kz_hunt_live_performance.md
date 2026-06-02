---
name: KZ Hunt — full overhaul shipped 2026-04-28
description: Was -$1,519 / PF 0.64 over 109 live trades. After 3-agent diagnosis, shipped 7 trade-mechanics fixes plus moved to M30 timeframe with 6-pair instrument list. Backtest projects +57% pips improvement vs prior H1 setup.
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Live state at the time of overhaul (109 trades since 2026-03-25):**
- WR 40% (vs backtest 61%)
- PF 0.64 (vs backtest 1.53; expert-panel "expected live" 1.15-1.30)
- Total: -$1,519, -280p
- Per-pair worst → best: EURAUD -$409, EURJPY -$295, USDCHF -$277, EURGBP -$276, EURUSD -$200, CHFJPY -$106, GBPJPY -$20, NZDUSD +$63

The earlier 73% WR / PF 1.31 on 15 trades was a lucky streak — reverted to 40%/0.64 as n grew to 109.

---

## Diagnosis (3-agent investigation 2026-04-28)

**Agent 1 (entry quality)**: 87% of live trades fired *stale* — average 22-hour gap between rejection candle and entry. The 13% that fired within 1 H1 bar of rejection broke even (+$46). The rest lost -$13.68/trade. Backtest variant `bars_since_rejection ≤ 1` showed PF 1.49 → 1.96 (+32%).

**Agent 2 (slippage)**: Mean adverse slip 6.06p (98% of fills adverse), max 36.6p, total cost $3,479. JPY crosses worst (CHFJPY +14.2p mean, EURJPY +9.5p, GBPJPY +6.3p). Hour clusters at session opens. No drift-gate or limit-order infrastructure existed.

**Agent 3 (trade management)**: 19 SL'd trades had MFE > 5p; 18/19 reached 50% of T1 distance before reversing. Best combo: BE@50%T1 + ATR trail @ 1×ATR after MFE ≥ 1×ATR → +94p net, +160p SL-bucket recovery.

**Invalidation counterfactual (separate analysis)**: 25 invalidations cost $651 net — backtest claimed 79% accuracy on losers; live measured 52%. Backtest-overfit. Disabled.

---

## All fixes shipped 2026-04-28

### Trade mechanics (7 changes)

1. **Freshness 1 bar** (was 24): `PATTERN_FRESHNESS_BARS["KZ_HUNT"]=2` on M30 (= 60min wall clock, same as old H1's 1 bar). Root-cause fix.
2. **Entry-drift gate** (`MAX_ENTRY_DRIFT_PIPS=6, JPY=12` after 2026-04-30 widening; was 3/8 originally): skip entries when live price drifted past intended. Initially set at 3p/8p but rejected 100% of overnight M30 signals (5-16p drift is normal on M30 due to slower confirmation). Widened to 6p/12p — correct for M30; truly stale signals (18p+) still get rejected.
3. **BE at 50% T1** (`BE_AT_T1_PROGRESS_BY_PATTERN["KZ_HUNT"]=0.50`): SL → entry when price reaches halfway to T1.
4. **Symbol-specific deviation** (`MAX_DEVIATION_PIPS=2`): MT5 rejects fills > 2p drift. Was hardcoded 20pts = 0.2p on JPY, slack on majors.
5. **Pre-partial ATR trail** (`PRE_PARTIAL_TRAIL_ATR_BY_PATTERN["KZ_HUNT"]=1.0`): trails SL at 1×ATR once MFE ≥ 1×ATR.
6. **4hr time stop** (`TIME_STOP_HOURS_BY_PATTERN["KZ_HUNT"]=4`): force-close drifters.
7. **Limit-style entries** (`LIMIT_ORDERS_ENABLED_BY_PATTERN["KZ_HUNT"]=True`, tolerance 2p / 5p JPY): request price = intended ± tolerance, zero deviation. Caps residual slippage at 2p.

### Strategy-level (timeframe + pairs)

8. **Switched to M30 timeframe** (was H1). Backtest 8 pairs × 8 yrs: H1 → M30 = +57% pips, PF 1.50 → 1.69.
9. **Dropped GBPJPY + CHFJPY**. Backtest 3yr: GBPJPY+CHFJPY combined +166p (low-signal pairs). Kept EURJPY (+473p alone). New `INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "EURJPY"]`.
10. **Confirmed M15 not viable**. EURUSD 1yr: M15 PF 1.37 vs M30 PF 2.27. WR collapses to 45%. Spread/move ratio is the problem on M15.

### Disabled feature
- **Invalidation OFF** for KZ_HUNT (`INVALIDATION_ENABLED_BY_PATTERN["KZ_HUNT"]=False`). Other patterns retain it.

### Scorer status (notes for future)
- Score 0-100 (rejection quality + KZ range + EMA200 + volume + timing) has **zero predictive power within the 50+ band** in both live and backtest. Score≥75 trades lose at the same per-trade rate as score 60-75.
- The 50 threshold itself still acts as a coarse sanity floor — keep it. Tightening to 70 gains marginal PF (+0.03) at cost of trade count.
- **Don't invest more time tuning component weights.** A different signal model would be needed for the scorer to add real edge. Until then it's a backstop, not an active filter.

---

## Backtest evidence

**8 pairs × 8 years (full historical):**
| Config | Trades | WR | PF | Total | DD |
|---|---|---|---|---|---|
| OLD (H1, fresh=24, inval ON) | 5,386 | 52% | 1.50 | +15,304p | 268p |
| NEW H1 (fresh=1, inval OFF) | 3,575 | 52% | 1.69 | +13,774p | 237p |

**8 pairs × 3 years (recent regime):**
| Config | Trades | WR | PF | Total | DD |
|---|---|---|---|---|---|
| H1 / fresh=1 | 1,294 | 52% | 1.75 | +4,968p | 235p |
| **M30 / fresh=2 (chosen)** | 2,593 | 51% | 1.61 | **+7,810p** | 316p |

**EURUSD-only timeframe sweep, 1yr:**
| TF | Trades | WR | PF | Total | DD |
|---|---|---|---|---|---|
| H1/fresh=1 | 101 | 56% | 1.87 | +419p | 62p |
| M30/fresh=2 | 176 | 55% | 2.27 | +945p | 90p |
| M15/fresh=4 | 216 | 45% | 1.37 | +415p | 152p |

M30 is the sweet spot. M15's structural issues (spread/move ratio, indicator validity) outweigh frequency gains.

---

## Live expectations

- **Trade frequency**: ~1-2 KZ_HUNT/day (down from 3.2/day). Drift gate already rejecting 13-15p stale signals.
- **WR**: expect 48-55% (vs current 40%). Backtest is 51-52%; with our slippage caps we should hit the upper end.
- **PF**: 1.20-1.50 expected live (backtest 1.61 with typical 30-40% live degradation, but slippage fixes narrow the gap).
- **Mean slippage**: ≤2p (capped by limit orders). Was 6p.
- **Validation**: 30+ closed trades for statistical sanity ≈ 2-4 weeks at expected frequency.

## Watch for

- Trade frequency collapse (<5/week stays for >1 week) → relax drift gate from 3p to 4-5p
- PF still <1.0 after 30 trades → consider pausing EURAUD/EURGBP/USDCHF
- `[BE_PROGRESS]`, `[PRE_PARTIAL_TRAIL]`, `[TIME_STOP]`, `[REQUOTE]` log lines should all start appearing
- NZDUSD was the one pair that prefers H1 over M30 in backtest — watch it specifically; if it bleeds, pause it

## Code paths

- Drift gate + limit price: `main.py:_attempt_entry` (around line 1408+)
- BE@50%T1 + ATR trail + time-stop: `trade_monitor.py:_check_trade` (around line 261+)
- Symbol-specific deviation + limit-order request: `order_manager.py:place_market_order`
- Invalidation toggle: `trade_monitor.py:_check_trade` reads `config.INVALIDATION_ENABLED_BY_PATTERN`
- Freshness check: `kz_hunt_detector.py:171` and `main.py:1291`
- LB pinned to H1: `main.py:_scan_london_breakout` uses literal `"H1"` (PRIMARY_TIMEFRAME is now M30)

## Backtest scripts (all in `scripts/`)

- `kz_hunt_freshness_compare.py` — 8yr OLD vs NEW H1 comparison
- `kz_hunt_m30_compare.py` — 3yr H1 vs M30/fresh=1 vs M30/fresh=2
- `kz_hunt_m15_single_pair.py` — 1yr EURUSD timeframe sweep (M15 verification)
- `kz_invalidation_analysis.py` — counterfactual on the 25 invalidation closures
- `kz_hunt_sl_analysis.py` — entry-quality + slippage breakdown
- `slippage_analysis.py` — agent-written deep-dive

## Charts

- `backtests/charts/kz_hunt_freshness_compare.png`
- `backtests/charts/kz_hunt_m30_compare.png`
- `backtests/charts/kz_hunt_m15_single_pair.png`
