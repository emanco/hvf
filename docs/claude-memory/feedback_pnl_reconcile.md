---
name: DB trade PnL can be silently wrong
description: When evaluating strategy performance, never trust trade_records.pnl alone — cross-check against equity_snapshots balance delta
type: feedback
originSessionId: aa1ced9c-762c-495d-b4b5-27d6d7d82083
---
`trade_records.pnl` in the DB is set to 0 when `mt5.history_deals_get` returns empty for a closed position (an IC Markets quirk already in CLAUDE.md). The bug: `pnl_estimated` stays False even though the 0 is an estimation failure, not a real breakeven. Real stop-out losses get silently hidden.

**Why:** First observed on 2026-04-20 when reviewing last week's KZ_HUNT performance. Headline DB sum showed +$361 net for the week with PF 1.50 (near backtest). Reconciling against equity_snapshots balance deltas around each trade's close time revealed 4 of 28 trades (96, 98, 99, 101 — all IDs close together, same day 4/13) with PnL=0 in DB but real losses of ~$410 combined. True week was +$40 (essentially flat), PF ~0.96. Tracked as TODO H1.

**How to apply:** When asked about recent performance or evaluating whether a fix helped, don't just sum `trade_records.pnl` — compute balance delta from `equity_snapshots` across the period as the source of truth, and spot-check any trade with `pnl=0` and a negative `pnl_pips` or STOP_LOSS close_reason against the balance snapshot at that timestamp.
