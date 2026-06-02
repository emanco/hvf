---
name: Quantum London — current state 2026-05-05
description: Rebuilt as faithful FF mean-reversion (#743125). EURGBP 40/12.5/40, capture 22:00 UTC, force-exit 21:00 UTC next day. Validated PF 2.52 on M5 8mo. M5 fidelity confirmed against M1.
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Identity (2026-05-05 rebuild):** Quantum London is now the FF Simple Mean Reversion strategy (thread #743125 by Alphaomega). The prior 7p/5p/18p grid-EA-derivative version is gone — disabled then replaced wholesale. Code lives in `hvf_trader/quantum_london_scanner.py` (class `QuantumLondonScanner`) and `hvf_trader/detector/quantum_london.py` (`QLTracker`, `QLSignal`). DB pattern_type stays `QUANTUM_LONDON`.

**Why the rename:** the original FF strategy is *called* "Simple Mean Reversion" but the project's naming/DB history was already `QUANTUM_LONDON`. Kept the project name; the mechanics are the canonical FF mean-reversion ones.

**Live config (multi-instance as of 2026-05-06):**
- TWO instances, each its own scanner thread:
  - EURGBP: 40/12.5/40 (PF 2.52 IC backtest, 15% fire rate — IC-Markets-tuned)
  - EURCHF: 20/5/20 (PF 1.23 / 4yr backtest, 90% fire rate, 85% WR — close to FF canonical, EURCHF was Alphaomega's primary pair)
- Both: M5 capture timeframe, 1Hz tick polling
- Capture daily open at 22:00 UTC
- Trigger ±40p from open (limit-order at trigger price — *not* market at ask/bid)
- TP 12.5p, SL 40p (asymmetric R:R per FF design)
- Force-exit at 21:00 UTC next day (~22hr hold, FF daily cycle)
- Days [6,0,1,2,3] = Sun-Thu capture nights → Mon-Fri trading (fixed 2026-05-06; was [0,1,2,3,4] which missed Mon and wasted Fri)
- 1% risk per trade, no filters

**Why limit-order entry matters:** the prior implementation entered at broker ask via market order, so TP was actually `trigger + spread + TP_pips` away from fill — halving win probability. Limit at trigger ensures TP/SL geometry matches backtest assumptions exactly. Trade-off: occasional REQUOTEs when price gaps past trigger; that's the correct behaviour.

**Validation:**
- IC Markets EURGBP M5, Aug 2025 → Apr 2026 (8 months, 174 sessions): N=26 trades, WR 69%, PF 2.52, +107p, MaxDD 22p, 0 SLs hit (all losses were TIME exits at 21:00 UTC). 15% fire rate per session.
- M1 vs M5 fidelity check on overlap window (2026-01-27 → 2026-04-16): IDENTICAL results — same 10 trades, same PnL, PF 9.86. Within-bar ordering ambiguity is a non-issue at M5 grain for this strategy. M5 backtest is structurally accurate.
- M30 3-year backtest gave PF 1.04 — bar-grain artifact, not informative (52.5p TP+SL span is commonly traversed inside a 30-min bar).
- Sweep showed 40-trigger row is a robust plateau across TP 10–20p: PF 1.99–2.52. 35-trigger drops to ~1.0 — narrow plateau on trigger axis.

**Open risks:**
- N=26 sample size is the genuine concern, not data fidelity.
- IC Markets M5 history is capped at ~8 months without manual chart-scrolling on the VPS terminal. Strategy Tester hits the same wall (EURUSD M1 timeout on USD account conversion).
- User chose to forward-test on demo rather than disable. No kill switch wired (demo, no real capital).

**Lifecycle (kept from prior version, both bugs fixed):**
- Open-trade monitoring runs whenever `_open_trade_id` is set, regardless of tracker state (DONE state after `mark_traded()` doesn't gate it out).
- Idle-window reset happens between force-exit and next capture; the previous strict `>` vs `>=` midnight-wrap bug is no longer relevant under the new state machine but kept in mind for any future state additions.
- Heartbeat per minute with state + open_trade in the log line.

**Files:**
- `hvf_trader/quantum_london_scanner.py` — scanner thread, ~450 lines
- `hvf_trader/detector/quantum_london.py` — QLTracker state machine, ~100 lines
- `hvf_trader/config.py` — `QUANTUM_LONDON` dict ~line 376
- `hvf_trader/main.py` — single QL spawn block (no longer aliased to `AsianGravityScanner`)
- `mql5/SMR_FF.mq5` — MQL5 EA mirror for MT5 Strategy Tester (broke on EURUSD M1 history timeout, kept for future re-attempt)
- `backtests/run_smr_chart.py`, `run_smr_sweep.py`, `run_smr_3yr.py`, `run_smr_m1_vs_m5.py` — backtest tooling (filenames retain "smr" prefix; rename later if confusing)
