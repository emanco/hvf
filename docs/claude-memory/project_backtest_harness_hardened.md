---
name: backtest-harness-hardened-2026-06-23
description: "Backtest engine now defaults to realistic spread + $7/lot round-trip commission. KZ calibration confirms it reproduces live \"no edge\" (honest 0.44 / hardened 0.38 vs optimistic 1.29). Old backtest PF numbers were inflated."
metadata: 
  node_type: memory
  type: project
  originSessionId: 3a71573c-5c8d-4e28-8192-fc7a3d01af45
---

**Why this exists:** investigated why backtests never reflected live (KZ live PF ~0.44-0.66 vs backtest 1.53; QL live 0.28 vs backtest 2.52). Root cause was NOT "live is harder" — it was optimistic/invalid backtests. Two fixable things: (1) a validity bug, (2) uncosted friction.

**Harness changes (commit 877930b):** in `hvf_trader/backtesting/backtest_engine.py`:
- `use_realistic_spread` default flipped `False → True` (was flat 1.5p; now per-symbol/hour `spread_model.py`).
- New `commission_per_lot_roundtrip` param, default **$7.0** (IC Markets Raw ≈ $3.50/side). Subtracted in `_calc_pnl` from BOTH `pnl_currency` (drives PF) and `pnl_pips` (drives win/loss classification). Threaded through `run_walk_forward`.
- To reproduce OLD optimistic numbers for A/B: pass `use_realistic_spread=False, commission_per_lot_roundtrip=0.0`.

**Calibration (`backtests/run_kz_harness_calibration.py`, KZ_HUNT EURGBP M30, 3yr WF):**
- A optimistic + geometry-bug-OFF: PF **1.29**, WR 50.6% (the inflated number we wrongly trusted)
- B honest (realistic spread+slip, geometry ON, no commission): PF **0.44**, WR 25.4% (reproduces the geometric-ablation memory exactly)
- C hardened (+commission): PF **0.38**, WR 25.4% (new honest baseline)
- Live KZ reference: ~0.66 clean / ~0.44 honest — all sub-1.0.

**Key insight:** the inflation was MOSTLY the geometric-validity bug (`KZ_HUNT_ENFORCE_VALID_GEOMETRY`), not friction — turning it off doubled the WR (25→50%) and flipped pips (−413 → +324), because SL-on-profit-side created fake instant wins. Commission was a smaller secondary drag (~0.06 PF, ~90 pips). See [[project_kz_hunt_filter_set_2026_05_05]], [[project_quantum_london]].

**How to apply:**
- Treat ALL pre-2026-06-23 backtest PF figures as inflated — re-run before believing them.
- The hardened harness is honest-to-slightly-conservative (gave 0.38 vs live 0.44-0.66) — the correct bias. A strategy that backtests >1.0 here is more trustworthy than one that did under the old defaults.

**NR7 / BTC_DONCHIAN re-validation (2026-06-23):** these are NOT on the central `backtest_engine.py` — they're standalone sims (`backtests/run_nr7_indices.py`, `run_crypto_donchian.py`) with their OWN cost models. Verified honest:
- **NR7_BREAKOUT is the most robust strategy in the book.** ~1560 trades across 4 indices/13.8yr, WR 66-68%, PF 4-5.7. Survives every test that killed the others: built-in cost stress (PF 3.92 at 10x cost), NEW gap-fill stop-entry slippage (PF only 5.46→5.26 on US500), cross-market (4 indices all strong), cross-time (every 3yr window positive incl. 2022 bear). Added `gap_fill` param (default True) in commit b4cb869.
- **BTC_DONCHIAN** second: BTC PF 5.09/WF 2.94, ETH 3.22/WF 4.69 (incl. costs). Structurally sound but tiny sample (BTC 47 trades/9yr), fat-tail-dependent, inconsistent across assets (DOGE PF 0.57, LTC 1.22 fail).
- **BOTH have ZERO live closed trades** — all backtest. NR7 is the genuine frontrunner for an eventual live-money discussion, but needs ~6-9mo to accumulate a real live sample (~56 trades/yr across US500+DE40). Go-live criteria still apply: don't convert on backtest alone.
- Still missing from central harness (future work): limit-order non-fill modeling, multiple-testing haircut on parameter sweeps.

**Honest scorecard — all 5 live strategies now have re-runnable honest backtests (2026-06-23):**
- **NR7_BREAKOUT** — PF ~5 (4 indices, ~1560 trades), robust to 10x cost + gap-fill. Strongest. `run_nr7_indices.py`.
- **NIGHT_TIDE** — PF **2.13** @ realistic 3p spread (N≈1230, 4 pairs all positive), but turns NEGATIVE by 7p (more spread-sensitive than once thought → live max-spread filter matters). Was 2.39 before the short-TP spread-bug fix (2026-06-26). `run_night_tide_realistic_spread.py`. (Earlier "one lucky night" was a LIVE-sample-size artifact; spread filter rejects ~80% of signals live → tiny live N.)
- **BTC_DONCHIAN** — BTC PF 5.09/WF 2.94, ETH 3.22/WF 4.69. Sound but tiny sample (47 trades/9yr), fat-tail-dependent.
- **LONDON_BO** — honest PF 1.37 (8y, 139 trades); thin, most friction-sensitive (marginal 1.06 under stress). `run_london_breakout.py` (built 2026-06-23, reuses live LondonBreakoutTracker).
- **ASIAN_SESSION_BREAKOUT** — now **GBPJPY-only (PF 1.79)**; EURJPY dropped 2026-06-26 (spread-correct PF 1.06 ≈ breakeven, no edge). `run_asb_validation.py`.

**Short-TP spread bug (found + fixed 2026-06-26):** standalone sims (ASB, NIGHT_TIDE) triggered SHORT TP on raw bid (`low<=tp`) — but a short closes by BUYING at the ask, so it needs `ask<=tp` (`bid<=tp-spread`); SL likewise (`ask>=sl`). The bug booked near-miss shorts as wins (e.g. live ASB trade 217: bid kissed TP, ask never did). **Lesson: the bug bites THIN edges hard (ASB EURJPY 1.11→1.06, killed it) and FAT edges lightly (NIGHT_TIDE 2.39→2.13, survived).** Investigation trigger: user noticed a EURJPY trade "should have hit TP."

**Full sweep of all short-capable sims (2026-06-26):**
- FIXED (live, fixed-TP): ASB (`run_asb_validation`), NIGHT_TIDE (`run_night_tide_realistic_spread`), LONDON_BO (`run_london_breakout`, 1.37→1.32). All survived except ASB-EURJPY (killed).
- CLEAN (no fix): **central engine `backtest_engine.py`** resolves short TP (target_2) on bar CLOSE (`close<=T2`), stricter than a wick — no phantom wins (this is why KZ calibrated to live 0.38). Donchian/NR7 = short STOP only (no fixed TP), wide stops + rt_cost → spread is noise.
- KNOWN-BUT-LEFT (dead/non-live, documented in commit 9877f13): QL sims (`run_ql_*`,`run_smr_*`, retired), KZ aux sims (`run_kz_flat_tp_compare/regime_filter/exit_giveback/mfe`, KZ off — real validation was the correct central engine), `run_asb_threshold_compare`/`run_asb_trend_filter` (ASB analysis tooling), `run_news_fade`/`run_bt_wedge_*`/`run_rsi2` (not live). NOTE: the ASB trend-filter "PF 1.40→1.89" memory result came from a buggy sim — discount it; ASB is GBPJPY-only now anyway.
- **Conclusion:** none are dead; backtests are honest+positive. Binding constraint everywhere is tiny LIVE samples (1-12 trades each). Collect-and-wait; NR7 the frontrunner. NR7/NIGHT_TIDE/Donchian use standalone sims, NOT the central engine.
