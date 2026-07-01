---
name: monitoring-reporting-kill-switch-state-2026-07-01
description: "Telegram reporting overhaul + kill-switch decisions. Routine perf alerts silenced (flag), Daily Review merged into Daily Summary, reports filtered to active pairs, kill switch kept dormant with decoupled baseline. Rationale for each."
metadata: 
  node_type: memory
  type: project
  originSessionId: 3a71573c-5c8d-4e28-8192-fc7a3d01af45
---

State + decisions from the 2026-06-30/07-01 session (Telegram/monitoring cleanup). These are config/decision facts not obvious from the code alone.

**Routine performance alerts SILENCED (by choice).** `config.PERF_ROUTINE_ALERTS_ENABLED = False`. The PerformanceMonitor still runs all checks, but only the kill-switch alert is sent to Telegram — the routine nags (rolling PF/WR "Performance Alert", Sharpe warning, loss streak, WR decay) were noise for strategies we're already actively managing. Flip the flag to True to restore. (commit f72b5d8)

**Kill switch KEPT but intentionally DORMANT.** Decision: on a DEMO account in an active build/test phase, with manual oversight + finer breakers (daily/weekly/monthly loss limits, per-pattern 3-loss pause), an aggregate auto-halt is low value and more nuisance than save. NOT removed — it's cheap dormant and is the pre-live safety net (its real value is real-capital + unattended operation; build/tune it BEFORE going live, don't bolt on later). Re-evaluate before funding real money.
- Decoupled baseline: `PERF_KILL_SWITCH_SINCE = "2026-07-01"` (separate from reporting's PERF_GO_LIVE_DATE 2026-03-25). It was counting trades since 2026-03-25 → at 179/200 it was ~21 trades from evaluating live PF over the whole PRE-CLEANUP history (KZ/QL/HVF/EURJPY losses) and would have tripped the auto-halt on the clean forward book. Reset the count 179→0. Needs 200 trades since 2026-07-01 + PF<1.2 to fire (months out). (commit ba86234)

**Daily Review MERGED into Daily Summary** (one Telegram report, 21:00 UTC). `daily_review.build_execution_report` → replaced by `build_ops_health()` (dict of errors/reconnects/rejections+reasons/CB/pnl-estimated/paused + headline). `telegram_bot.send_daily_summary` renders a headline triage line (✅ ALL GREEN / ⚠️ issues) + one compact "🔧 Ops (24h)" line, on top of PnL/per-pair/balance/equity-chart. The separate 21:30 review send was removed; `/review` command now triggers the merged summary on demand. (commit d35cc1e)

**Reports filtered to currently-traded pairs.** Daily summary per-pair list shows only `config.active_traded_symbols()` (∪ symbols with an open position) — abandoned pairs (EURJPY and the retired KZ/QL universe) no longer clutter it. `active_traded_symbols()` (in config.py) is the SINGLE SOURCE OF TRUTH: it assembles the tradeable set from each ENABLED strategy's instrument config (handles instruments/instrument/instances shapes; KZ universe only if ENABLED_PATTERNS non-empty), so reports self-maintain as the book changes. Reuse it for any future report filtering. (commit e42cb09)

**Reporting baseline unchanged:** PERF_GO_LIVE_DATE stays 2026-03-25 → equity chart / total PnL / per-pair keep full history. Only the kill switch uses the newer 2026-07-01 baseline.

See [[project_backtest_harness_hardened]], [[feedback_order_placement_false_failure]].
