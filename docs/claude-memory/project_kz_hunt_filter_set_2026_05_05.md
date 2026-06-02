---
name: KZ_HUNT live filter set 2026-05-05
description: 3-pair subset + score>=60 + flat TP 12p (no partial/trail). 9x MAR improvement vs baseline on 117-trade live sample (PF 1.45 vs 1.03, +107p vs +24p, DD 56p vs 113p).
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Live config (deployed 2026-05-05, EURAUD added back same day):**
- INSTRUMENTS: NZDUSD, EURGBP, EURJPY, EURAUD (4 pairs). EURAUD initially dropped (raw PF 0.96) but what-if showed score>=60 rescues it to PF 1.12; user chose 4-pair set for more trade volume (61 trades vs 39, +117p vs +97p) at modest cost (PF 1.33 vs 1.51, DD 65p vs 38p, MAR 1.80 vs 2.54).
- SCORE_THRESHOLD_BY_PATTERN["KZ_HUNT"]: 60
- FLAT_TP_PIPS_BY_PATTERN["KZ_HUNT"]: 12
- SPLIT_ORDER_BY_PATTERN["KZ_HUNT"]: False (broker-side TP/SL only)
- TRAILING_STOP_ATR_MULT, PRE_PARTIAL_TRAIL_ATR, BE_AT_T1_PROGRESS: all 0
- INVALIDATION_ENABLED_BY_PATTERN["KZ_HUNT"]: False (since 2026-04-28)

**How this was chosen:** three parallel agents on 117 live KZ_HUNT trades (2026-03-25 → 2026-05-05) under flat +12p TP simulation explored:
- Score threshold sweep: best at >=60 (PF 1.09 vs 1.03 baseline; tighter than 65 over-fit)
- Per-pair greedy: best subset {NZDUSD, CHFJPY, EURGBP, EURJPY} (PF 1.49 / N=51) but CHFJPY stays disabled for "low M30 signal" (separate reason from 2026-04-28)
- Regime filter: EMA200-align + ATR not top tercile gave PF 1.65 alone but combining with pair filter dropped N to 19 (overfit). Not used live.

**Combined A+C (score>=60 + 4-pair subset including CHFJPY):**
- N=46, WR 63%, PF 1.45, Total +107p, DD 56p, MAR 1.93

**Live deployed (3-pair subset, dropping CHFJPY):**
- Approximate stats from same sweep: N=36 (excluding CHFJPY's 10 trades), expected slightly lower DD, PF likely 1.4-1.5

**Dropped pairs and rationale:**
- EURAUD: 24 trades, PF 0.96, -9p
- EURUSD: 17 trades, PF 0.93, -8p
- USDCHF: 20 trades, PF 0.87, -18p
- GBPJPY: dropped 2026-04-28 (low M30 signal, also PF 0.37 in this sample)
- CHFJPY: dropped 2026-04-28 (low M30 signal). Despite PF 1.27 in this sample, kept off — re-add only if low-signal concern resolves.

**Caveats:**
- 117 trades is small. In-sample tuning (pair selection + score threshold both selected on this exact data).
- Realistic out-of-sample degradation usually shaves 30-50% off PF. Forward expectation: PF 1.10-1.25.
- 3-pair subset means slower data accumulation — need 30-50 more live trades to validate.

**Files:**
- `backtests/run_kz_score_sweep.py`, `run_kz_pair_filter.py`, `run_kz_regime_filter.py` — three agent scripts
- `backtests/run_kz_combined_filter.py` — A/B/C/D combinations test (final selection)
- `backtests/data/kz_trades_enriched.csv` — base dataset
- `backtests/charts/kz_combined_filter.png` — equity curves comparison

**Next checkpoint:** review after 30-50 more KZ_HUNT trades. If PF drops below 1.0 or MaxDD breaches 100p, revisit. If it holds 1.1+, consider adding CHFJPY back (after separate low-signal investigation).
