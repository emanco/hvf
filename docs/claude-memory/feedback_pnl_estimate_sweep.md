---
name: Estimated PnL sweep finding 2026-05-26
description: 11 of 11 estimated-PnL trades had wrong values in the DB; net swing $432. Multiple "losers" were real winners. Implications for any strategy P&L analysis or breaker counts.
type: feedback
originSessionId: d108d06f-19a6-4a24-b018-ab64afebd75e
---
On 2026-05-26 a sweep of all `pnl_estimated=1` trades since 2026-05-01 against MT5 deal history found that **every single one was wrong** — net delta to DB PnL was **+$432.17**. The account balance had always been correct (equity_snapshots reconcile from MT5 directly) but `trade_records.pnl` had been systematically misleading for weeks.

**Most-affected pairs:**
- QL/EURCHF: trades 170, 171, 177, 182, 186 — DB showed losses of −$103/−$163/−$96/−$78/−$78, reality was −$7/−$79/+$27/+$23/+$24. Three of these were WINNERS that tripped the per-pattern breaker as fake losses.
- KZ_HUNT/EURAUD: trades 166, 173, 180 — DB showed +$251/−$109/−$109, reality was −$2/+$66/+$53.
- Smaller swings on NZDUSD/EURJPY/GBPUSD trades.

**Why:** Reconciliation's late-update schedule was (60s, 180s, 600s, 1800s) = 30 minutes total. When MT5 deal history takes longer than that to propagate (over weekends, during broker maintenance windows, or just slow), the SL-estimate gets locked in. Schedule was extended 2026-05-26 (commit b6c23f8) to 10 retries spanning 7 days.

**How to apply:**
- Never trust `trade_records.pnl` for strategy P&L analysis without first checking `pnl_estimated` is 0.
- When a per-pattern circuit breaker trips, sanity-check the trades that triggered it — if any were `pnl_estimated=1`, the count may be on fake data.
- Use `equity_snapshots` for true balance history; the DB's per-trade PnL can lag or be wrong.
- If a sweep is ever needed, the pattern is in `scripts/sweep_estimated_pnl.py` on the VPS.
