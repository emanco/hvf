---
name: Multi-expert assessment completed 2026-04-15
description: 4-expert bot review done — 17 fixes shipped, remaining work is post-200-trades
type: project
originSessionId: f501baf1-25a0-4127-bd25-05baff95b8a7
---
Ran a 4-expert panel (Trader, Data Analyst, SWE, Quant) on 2026-04-15. Full report at `TEAM_ASSESSMENT_2026-04-15.md`.

**Fixes shipped in this session (17 total):**
- News filter: added EURJPY/CHFJPY
- Entry confirmation: aligned to use completed bars (was using forming bar)
- Rolling Sharpe: rewritten with daily equity returns
- pattern_metadata: now populated with KZ data
- pnl_estimated flag: new column on TradeRecord
- Perf monitor alerts: re-enabled
- Thread watchdog: auto-restarts dead trade monitor
- Volume scorer fallback: 0 instead of 7.5
- time.sleep(10): replaced with deferred retry
- Deal utils: extracted shared module (DRY fix for trade_monitor + reconciliation)
- Daily DB backup: GZip compressed, 7-day retention, Task Scheduler on VPS
- Daily summary: PnL now from MT5 balance change (not DB), equity chart from snapshots
- /equity command: updated to use snapshot-based chart
- _detach_record: added pattern_metadata (missing attr caused orphaned positions)
- Closed 4 orphaned EURUSD positions (+$59.74) caused by the above bug
- CLAUDE.md: updated instrument list from 5 to 8 pairs

**Known design risk:** Orders are placed in MT5 before DB write. If anything crashes between, positions become orphans. Reconciliation logs warnings but doesn't auto-adopt. Low priority fix.

**Key remaining items (after 200+ trades):**
- Regime filter (20-day ATR percentile)
- Portfolio-level backtest (all 8 pairs concurrent)
- Monte Carlo ruin probability
- Scoring weight re-evaluation using pattern_metadata
- Correlation-aware position sizing

**How to apply:** Check TODO.md for the full backlog. Don't suggest parameter changes until 200+ trades collected.
