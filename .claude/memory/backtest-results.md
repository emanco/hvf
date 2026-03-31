# Backtest Results

## Run 10: 10-Year Backtest V4 — Current Live Config (2026-03-12)

Config: 70K H1 bars (Dec 2014 — Mar 2026, 11.2 years), £700, HVF + KZ Hunt only (Viper removed)
Changes vs V3: Viper disabled, PARTIAL_CLOSE_PCT 0.50→0.60, backtest engine fixed to use config value
Compounding position sizing (lot size scales with equity at 2% KZ / 1% HVF risk)

### Portfolio Summary
- **£700 → £741,338** (+105,805%), CAGR 86.0%
- **6,107 trades**, +25,973 pips, PF=1.79, WR=65%
- **Max Drawdown: 10.9%**
- **544 trades/year** (~45/month)

### V3 → V4 Comparison
| Metric | V3 | V4 | Change |
|--------|----|----|--------|
| Final Equity | £282,911 | £741,338 | +162% |
| Total Pips | +20,701 | +25,973 | +25% |
| Profit Factor | 1.53 | 1.79 | +17% |
| Max Drawdown | 19.5% | 10.9% | -44% |
| CAGR | 70.7% | 86.0% | +22% |
| Win Rate | 63% | 65% | +2% |

### Per-Pair Results
| Pair | Trades | Pips | PF | WR |
|------|--------|------|----|----|
| EURAUD | 1,261 | +9,124 | 1.75 | 66% |
| USDCHF | 1,138 | +4,739 | 2.34 | 67% |
| NZDUSD | 1,227 | +4,699 | 1.82 | 66% |
| EURUSD | 1,149 | +4,256 | 1.79 | 63% |
| EURGBP | 1,332 | +3,154 | 2.06 | 65% |

### Per-Pattern Per-Pair Breakdown
| Pair | Pattern | Trades | WR | PF | Pips | AvgW | AvgL |
|------|---------|--------|----|----|------|------|------|
| EURUSD | HVF | 36 | 78% | 1.32 | +139 | 20.5 | 54.4 |
| EURUSD | KZ_HUNT | 1,113 | 63% | 1.68 | +4,117 | 14.5 | 14.5 |
| NZDUSD | HVF | 33 | 70% | 1.64 | +255 | 28.2 | 39.5 |
| NZDUSD | KZ_HUNT | 1,194 | 66% | 1.90 | +4,445 | 11.9 | 12.1 |
| EURGBP | HVF | 47 | 68% | 0.95 | -37 | 20.5 | 46.2 |
| EURGBP | KZ_HUNT | 1,285 | 65% | 1.69 | +3,191 | 9.4 | 10.2 |
| USDCHF | HVF | 33 | 73% | 1.29 | +109 | 20.3 | 41.8 |
| USDCHF | KZ_HUNT | 1,105 | 66% | 1.99 | +4,630 | 12.7 | 12.6 |
| EURAUD | HVF | 30 | 83% | 2.41 | +586 | 40.1 | 83.3 |
| EURAUD | KZ_HUNT | 1,231 | 65% | 1.82 | +8,538 | 23.5 | 24.5 |

### Pattern Totals
| Pattern | Trades | PF | Pips | WR |
|---------|--------|----|------|----|
| KZ Hunt | 5,928 | 1.81 | +24,921 | 65% |
| HVF | 179 | 1.45 | +1,052 | 74% |

### Key Findings
1. **Removing Viper was the right call** — PF 1.53→1.79, MaxDD 19.5%→10.9%
2. **60/40 partial close is better than 50/50** — locks more profit at T1
3. **MaxDD halved** — much smoother equity curve
4. **All 5 pairs profitable** with PF > 1.75
5. **USDCHF is the standout** — PF=2.34, best risk-adjusted returns
6. **EURAUD highest absolute pips** (+9,124) — volatile pair captures big moves
7. **EURGBP HVF still net negative** (-37p, PF=0.95) — consider excluding
8. **KZ Hunt PF improved** from 1.53 to 1.81 with 60/40 partial close
9. **Backtest doesn't apply PATTERN_SYMBOL_EXCLUSIONS** — EURUSD has 36 HVF trades (PF=1.32, minimal impact)

### Charts
- `backtests/charts/bt_10yr_v4_equity.png` — combined portfolio equity + drawdown
- `backtests/charts/bt_10yr_v4_pairs.png` — all 5 pairs overview with stats

---

## Run 9: 10-Year Full Backtest V3 Config (2026-03-09)

Config: 70K H1 bars (Dec 2014 — Mar 2026, 11.3 years), £700, HVF + KZ Hunt, 5 pairs
Compounding position sizing (lot size scales with equity at 2% KZ / 1% HVF risk)

### Portfolio Summary
- **£700 → £282,911** (+40,316%), CAGR 70.7%
- **6,151 trades**, +20,701 pips, PF=1.53, WR=63%
- **Max Drawdown: 19.5%** (early 2016 period)
- **548 trades/year** (~46/month)

### Per-Pair Results
| Pair | Trades | Pips | PF | WR | MaxDD | Final £ | Return |
|------|--------|------|----|----|-------|---------|--------|
| EURAUD | 1,286 | +6,620 | 1.43 | 62% | 17.6% | £88,091 | +12,484% |
| USDCHF | 1,200 | +4,086 | 1.60 | 63% | 25.7% | £45,801 | +6,443% |
| NZDUSD | 1,263 | +3,441 | 1.44 | 62% | 30.7% | £52,652 | +7,422% |
| EURUSD | 1,093 | +3,380 | 1.43 | 63% | 25.7% | £35,950 | +5,036% |
| EURGBP | 1,309 | +3,173 | 1.63 | 63% | 24.2% | £63,216 | +8,931% |

### Per-Pattern Totals
| Pattern | Trades | PF | Pips | WR |
|---------|--------|----|------|----|
| KZ Hunt | 5,971 | 1.53 | +19,584 | 62% |
| HVF | 180 | 1.47 | +1,116 | 73% |

### Per-Pair HVF Breakdown
| Pair | HVF Trades | WR | PF | Pips | Avg Win | Avg Loss |
|------|-----------|----|----|------|---------|----------|
| EURAUD | 31 | 84% | 2.32 | +623 | 42.1 | 94.5 |
| EURUSD | 36 | 78% | 1.43 | +180 | 21.4 | 52.5 |
| NZDUSD | 34 | 71% | 1.78 | +309 | 29.3 | 39.5 |
| USDCHF | 33 | 73% | 1.29 | +109 | 20.3 | 41.8 |
| EURGBP | 46 | 65% | 0.85 | -105 | 20.0 | 44.1 |

### Per-Pair KZ Hunt Breakdown
| Pair | KZ Trades | WR | PF | Pips | Avg Win | Avg Loss |
|------|----------|----|----|------|---------|----------|
| EURGBP | 1,263 | 63% | 1.66 | +3,278 | 10.3 | 10.8 |
| EURUSD | 1,057 | 62% | 1.48 | +3,200 | 14.9 | 16.5 |
| NZDUSD | 1,229 | 61% | 1.50 | +3,132 | 12.4 | 13.2 |
| USDCHF | 1,167 | 63% | 1.69 | +3,977 | 13.3 | 13.3 |
| EURAUD | 1,255 | 61% | 1.46 | +5,997 | 24.8 | 27.0 |

### Key Findings
1. **All 5 pairs profitable** — no weak links in the portfolio
2. **EURAUD is the star**: highest pips (+6,620), lowest MaxDD (17.6%), best HVF (84% WR, PF=2.32)
3. **KZ Hunt is 97% of trades** and 95% of pips — the volume engine
4. **HVF is the quality diversifier**: 180 trades, 73% WR, +1,116p. Low frequency but high accuracy
5. **EURGBP KZ Hunt best PF** (1.66) — very clean despite lower pip range
6. **EURGBP HVF is net negative** (-105p, PF=0.85) — consider excluding
7. **NZDUSD has deepest DD** (30.7%) — ~2020 era dip visible in chart
8. **Compounding drives exponential growth** — 2% KZ risk means late-period lots are ~71x larger than start

### Charts
- `backtests/charts/bt_10yr_combined_dd.png` — combined portfolio equity + drawdown
- `backtests/charts/bt_10yr_pairs_dd.png` — all 5 pairs overview with stats boxes
- `backtests/charts/bt_10yr_eurusd.png` — individual EURUSD equity + drawdown
- `backtests/charts/bt_10yr_nzdusd.png` — individual NZDUSD equity + drawdown
- `backtests/charts/bt_10yr_eurgbp.png` — individual EURGBP equity + drawdown
- `backtests/charts/bt_10yr_usdchf.png` — individual USDCHF equity + drawdown
- `backtests/charts/bt_10yr_euraud.png` — individual EURAUD equity + drawdown

---

## Run 8: Surgical Tuning — Viper EURGBP Exclusion + Aggression Bump (2026-03-07)

Config: 10K H1 bars, £700, HVF + Viper(SHORT) + KZ Hunt, 4 pairs
Changes vs Run 7: PATTERN_SYMBOL_EXCLUSIONS={"VIPER":["EURGBP"]}, Viper risk 0.75→1.0%, max concurrent 2→3

### NEW Config Results
| Pair | Trades | WR | PF | PnL (pips) | MaxDD | HVF | Viper | KZ Hunt |
|------|--------|----|----|------------|-------|-----|-------|---------|
| EURUSD | 154 | 59% | 1.37 | +450.2 | 5.1% | 11T/+43.5p | 42T/+308.0p | 101T/+98.7p |
| NZDUSD | 157 | 62% | 1.41 | +356.7 | 6.4% | 4T/+105.1p | 40T/-197.7p | 113T/+449.3p |
| EURGBP | 132 | 67% | 1.32 | +131.7 | 2.5% | 11T/+13.7p | 0T (excluded) | 121T/+118.0p |
| USDCHF | 172 | 63% | 1.72 | +840.0 | 5.4% | 7T/-43.2p | 50T/+453.2p | 115T/+430.0p |
| **TOTAL** | **615** | **63%** | | **+1778.6** | | 33T/+119.1p | 132T/+563.5p | 450T/+1096.0p |

Final equity: **£1190** (from £700)

### OLD Config (baseline) Results
| Pair | Trades | PF | PnL (pips) | Delta vs NEW |
|------|--------|----|------------|-------------|
| EURUSD | 153 | 1.36 | +449.0 | +1.2p |
| NZDUSD | 157 | 1.51 | +360.8 | -4.1p |
| EURGBP | 166 | 0.99 | +40.1 | +91.6p |
| USDCHF | 170 | 1.76 | +685.5 | +154.6p |
| **TOTAL** | **646** | | **+1535.4** | **+243.3p** |

Final equity: £1096

### Key Findings
1. **EURGBP surgical fix works**: +40p → +132p by removing 38 losing Viper trades, keeping 11 profitable HVF + 121 KZ Hunt
2. **USDCHF biggest beneficiary**: +685p → +840p from Viper 1.0% risk sizing + max concurrent 3
3. **KZ Hunt is the volume engine**: 450 of 615 trades, +1096p total — dominant pattern by trade count
4. **31 fewer trades, +£93 more profit**: less churn, better returns
5. **NZDUSD Viper still negative** (-198p) but KZ Hunt compensates massively (+449p)

### Charts
- `backtests/charts/bt_equity_comparison.png` — per-pair + combined equity OLD vs NEW
- `backtests/charts/bt_compare_breakdown.png` — per-pair per-pattern bar chart
- `backtests/charts/bt_compare_equity.png` — combined equity overlay

---

## Run 7: Viper v3 SHORT-only + HVF Portfolio (2026-03-06)

Config: 10K H1 bars (~14 months), £700 equity, HVF+Viper(SHORT-only)
Viper v3 changes: impulse 2.0x ATR, ADX>20 filter, trailing 2.5x ATR, freshness 10 bars, scan/8bars

### Viper v3 SHORT-only Results
| Pair | Trades | WR | PF | PnL (pips) | MaxDD | Notes |
|------|--------|----|----|------------|-------|-------|
| EURUSD | 24 | 50% | 1.50 | +41.7 | 3.3% | Best Viper pair |
| NZDUSD | 16 | 44% | 1.54 | +6.7 | 4.3% | Good frequency |
| EURGBP | 15 | 47% | 0.71 | -7.3 | 3.5% | Marginal, monitor |

### Combined HVF + Viper(SHORT) Portfolio
| Pair | Trades | WR | PF | PnL (pips) | HVF contrib | Viper contrib |
|------|--------|----|----|------------|-------------|---------------|
| EURUSD | 35 | 57% | 1.51 | +44.0 | 11T/+2.3p | 24T/+41.7p |
| NZDUSD | 21 | 52% | 1.77 | +78.4 | 5T/+71.7p | 16T/+6.7p |
| EURGBP | 25 | 52% | 0.75 | +3.0 | 10T/+10.3p | 15T/-7.3p |
| **TOTAL** | **81** | **54%** | **1.21** | **+125.4** | 26T/+84.3p | 55T/+41.1p |

### Key Findings
1. **SHORT-only Viper is the structural edge**: LONGs net negative across ALL pairs; SHORTs consistently profitable
2. **Frequency tripled**: 26 HVF-only → 81 HVF+Viper (~5.8 trades/month vs ~2/month)
3. **ADX filter eliminated chop**: v2 had PF 0.84-0.97, v3 SHORT-only has PF 1.50 on EURUSD
4. **Wider trailing (2.5x ATR) helps Viper**: Continuation trades need room to breathe
5. **EURGBP Viper marginal**: PF 0.71, will monitor during demo — may disable if stays negative

### Viper v2 → v3 Progression (EURUSD)
| Version | Trades | WR | PF | PnL | Changes |
|---------|--------|----|----|-----|---------|
| v2 (both dirs) | 40 | 40% | 0.84 | -113.7p | 2.5x ATR, no ADX, 1.5x trail |
| v3 (both dirs) | 50 | 46% | 0.97 | -93.5p | 2.0x ATR, ADX>20, 2.5x trail |
| v3 (SHORT-only) | 24 | 50% | 1.50 | +41.7p | Direction filter applied |

### Deployed Config
- ENABLED_PATTERNS = ["HVF", "VIPER"]
- ALLOWED_DIRECTIONS_BY_PATTERN = {"VIPER": "SHORT"}
- INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP"]
- Bot running as Windows Scheduled Task "HVF_Bot" on VPS

---

## Run 6: 7-Pair HVF Diversification Test (2026-03-06)

Config: 10K H1 bars (~14 months), HVF-only, £700 equity
Testing which pairs produce profitable HVF patterns at £700

### Results Summary
| Pair | Trades | WR | PF | PnL (pips) | L/S Split | Verdict |
|------|--------|----|----|------------|-----------|---------|
| EURUSD | 10 | 80% | 2.12 | +56.0 | 4L/6S | KEEP |
| NZDUSD | 5 | 80% | 3.25 | +71.1 | 1L/4S | ADD |
| EURGBP | 10 | 80% | 0.91 | +10.3 | 5L/5S | ADD (marginal) |
| USDCHF | 7 | 71% | 0.74 | +2.3 | 3L/4S | Borderline |
| GBPUSD | 11 | 64% | 0.46 | -119.6 | 5L/6S | REMOVE |
| USDCAD | 8 | 75% | 0.59 | -53.5 | 3L/5S | Skip |
| AUDUSD | 4 | 50% | 0.66 | -52.7 | 2L/2S | Skip |

### Selected Portfolio: EURUSD + NZDUSD + EURGBP
- Combined: 25 trades, +137.4 pips over ~14 months
- All three pairs detect both LONGs and SHORTs (SHORT fix working across pairs)

### NZDUSD Details (best PF)
- #1: SHORT +58.6p (TS), #2: SHORT +11.4p (TS), #3: LONG +31.3p (T2)
- #4: SHORT -31.4p (SL), #5: SHORT +1.2p (TS)
- SHORTs dominate (4 of 5 trades), entry prices 0.56-0.59 range

### GBPUSD Removal Rationale
- PF 0.46 at £700 (worse than at £500 where it was 0.74)
- 3 big stop losses (-44.8, -57.9, -69.3) wipe out 7 small wins
- Consistently negative across all test runs (Run 2: -10.2p, Run 5: -11.5p, Run 6: -119.6p)

### Conclusions
1. **NZDUSD is the second best instrument** — PF 3.25, even better than EURUSD per trade
2. **GBPUSD removed from live** — consistently net negative
3. **EURGBP adds volume** — 10 trades, marginal positive, good for pattern practice
4. **SHORTs working across all pairs** — Phase 0 fix confirmed multi-pair
5. **Demo updated**: EURUSD + NZDUSD + EURGBP as of 2026-03-06

---

## Run 5: Multi-Pattern Comparison (2026-03-06)

Config: 10K H1 bars (~14 months), HVF scan/4bars, others/24bars, 200-bar non-HVF window
SHORT bug fixed (Phase 0), KLOS scoring active, Viper/KZ Hunt/London Sweep coded

### EURUSD HVF-Only: 7T, 86% WR, PF 2.19, +60.4p
- LONGs: +25.8(T2), +37.4(TS), -50.6(SL), +0.7(TS)
- SHORTs: +18.6(TS), +9.7(TS), +18.8(TS) — all 3 SHORTs won

### EURUSD All Patterns: 98T, 49% WR, PF 0.94, -45.1p
- HVF: 7T/86%WR/+62.6p | Viper: 63T/44%WR/-44.4p | LS: 28T/50%WR/-63.3p | KZ: 0T
- LONG=50(-291.9p), SHORT=48(+246.8p) — SHORTs profitable, LONGs terrible

### GBPUSD HVF-Only: 5T, 80% WR, PF 0.74, -11.5p
### GBPUSD All Patterns: 69T, 51% WR, PF 0.94, -22.3p
- HVF: 5T/80%/-11.5p | Viper: 33T/45%/+7.2p | LS: 31T/52%/-18.0p

### Conclusions
1. **HVF SHORTs work** — Phase 0 fix successful
2. **Viper/LS net negative** — need tuning before live use
3. **KZ Hunt zero trades** — detector broken
4. **Run HVF-only on demo** until others tuned

---

## Run 4: HVF-Only 20K bars with SHORT fix (2026-03-05)
EURUSD: 18T, 78% WR, PF 1.22, +42.4p — 10 LONGs, 8 SHORTs detected

---

## Run 3: 4-Pair Diversification Test (2026-03-05)

Added AUDUSD and USDJPY to test whether diversification improves returns at £500.

### Full Backtest (20,000 bars H1, ~2+ years)

| Symbol | Trades | Win Rate | PF | PnL (pips) | Max DD | Notes |
|--------|--------|----------|----|------------|--------|-------|
| EURUSD | 11 | 91% | 3.16 | +109.0 | 1.0% | Unchanged from Run 2 |
| GBPUSD | 6 | 83% | 0.76 | -10.2 | 0.8% | Unchanged from Run 2 |
| AUDUSD | 1 | 100% | inf | +25.4 | 0.0% | Only ~1yr data available |
| USDJPY | 0 | - | - | 0.0 | 0.0% | All lots floor to 0.00 |

#### AUDUSD Trade Detail
- #1: LONG entry=0.62982 exit=0.63169 pips=+25.4 (TRAILING_STOP, score=53)

#### USDJPY Sizing Problem
- pip_value_per_lot=1000 for JPY pairs (vs 10 for USD pairs)
- At £500 / 1% risk / ~60-190 pip stops → raw_lots = 0.0000-0.0001, all floor to 0.00
- Needs ~£3,000+ to trade minimum 0.01 lots

### Walk-Forward (6-month train / 2-month test)

| Symbol | OOS Trades | OOS WR | OOS PF | Positive Windows |
|--------|-----------|--------|--------|-----------------|
| EURUSD | 7 | 57% | 0.48 | 1/16 (6%) |
| GBPUSD | 3 | 33% | 0.13 | 1/16 (6%) |
| AUDUSD | 0 | - | - | 0/4 (0%) |
| USDJPY | 0 | - | - | 0/16 (0%) |

### Conclusion
Diversification does not help at £500. EURUSD is the only viable instrument.
Scaling roadmap: GBPUSD at ~£750, AUDUSD at £1,000+, USDJPY at £3,000+.

---

## Run 2: After Filter Relaxation (2026-03-05)

Changes: convergence 1.5×→1.2×, EMA200 hard gate→soft scorer, RRR 1.5→1.0

### Full Backtest (20,000 bars H1, ~2+ years)

#### EURUSD
- Trades: 11
- Win Rate: 90.9%
- Profit Factor: 3.16
- Total PnL: +109.0 pips
- Max Drawdown: 1.0%
- Avg Score: 50
- All trades LONG
- Trade details:
  - #1: LONG +10.6 pips (TRAILING_STOP, score=55)
  - #2: LONG +10.5 pips (TRAILING_STOP, score=41)
  - #3: LONG +37.8 pips (TRAILING_STOP, score=60)
  - #4: LONG +4.0 pips (TRAILING_STOP, score=44)
  - #5: LONG +12.7 pips (TRAILING_STOP, score=54)
  - #6: LONG +17.7 pips (TARGET_2, score=41)
  - #7: LONG +0.8 pips (TRAILING_STOP, score=53)
  - #8: LONG +25.8 pips (TARGET_2, score=56)
  - #9: LONG +37.4 pips (TRAILING_STOP, score=54)
  - #10: LONG -50.6 pips (STOP_LOSS, score=50)
  - #11: LONG +2.1 pips (TRAILING_STOP, score=43)

#### GBPUSD
- Trades: 6
- Win Rate: 83.3%
- Profit Factor: 0.76
- Total PnL: -10.2 pips
- Max Drawdown: 0.8%
- Trade details:
  - #1: LONG +1.7 pips (TRAILING_STOP, score=43)
  - #2: LONG +6.9 pips (TRAILING_STOP, score=57)
  - #3: LONG +3.8 pips (TRAILING_STOP, score=49)
  - #4: LONG +6.8 pips (TRAILING_STOP, score=45)
  - #5: LONG -42.2 pips (STOP_LOSS, score=44)
  - #6: LONG +12.8 pips (TRAILING_STOP, score=44)

### Walk-Forward (6-month train / 2-month test)

#### EURUSD
- OOS Trades: 7
- Win Rate: 57.1%
- Profit Factor: 0.48
- OOS PnL: -62.0 pips
- Positive windows: 1/16 (6%)
- Active windows: 4/16 (Window 1: -32.4, Window 6: -16.7, Window 7: +26.6, Window 14: -39.6)

#### GBPUSD
- OOS Trades: 3
- Win Rate: 33.3%
- Profit Factor: 0.12
- OOS PnL: -52.1 pips
- Positive windows: 1/16 (6%)
- Active windows: 2/16 (Window 5: +6.9, Window 14: -59.0)

---

## Run 1: Initial Working Backtest (2026-03-05, earlier)

Config at the time: convergence 1.5×, EMA200 hard gate, RRR 1.5

### Full Backtest
- EURUSD: 4 trades, 100% WR, PF=inf, +86.7 pips, 0% DD
- GBPUSD: 1 trade, 100% WR, PF=inf, +6.9 pips, 0% DD

### Walk-Forward
- EURUSD: 2 OOS trades, 50% WR, PF=0.03
- GBPUSD: 1 OOS trade, 100% WR, PF=inf

---

## Key Observations
- **Viper SHORT-only is the breakthrough**: +41.1 pips from 55 trades, tripling frequency from HVF-only
- **Portfolio now 81 trades / 14 months**: ~5.8/month vs ~2/month HVF-only
- Forex downside momentum is structurally sharper — Viper LONGs net negative across ALL pairs
- ADX>20 filter + 2.5x ATR trailing were key v3 improvements over v2
- HVF SHORTs working post-Phase 0 fix: detected across EURUSD, NZDUSD, EURGBP
- GBPUSD removed (Run 6): consistently net negative across all test runs
- Walk-forward PF < 1 for HVF-only — sample sizes too small, monitoring in demo
- **Capital scaling**: 3-pair portfolio at £700, add GBPUSD if profitable patterns emerge

## Bugs Fixed Before Run 1
1. RRR scoring formula: rrr/10 → rrr/4 (full marks at 4:1 not 10:1)
2. Score threshold: 70 → 40
3. Volume spike multiplier: 1.5 → 1.2
4. Trade clustering: added triggered_pattern_keys set
5. Entry sanity check: skip if price already past target_1
6. Stop distance uses actual bar close, not theoretical entry
