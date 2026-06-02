---
name: Split-order orphaned partial after main close — fixed 2026-04-30
description: When the main ticket of a split KZ_HUNT order closes first (e.g. BE SL hit after BE_PROGRESS), the partial ticket can become orphaned if reconciliation/trade_monitor closes the trade in DB while the partial is still alive on MT5. Real loss appears in account balance but not the trade record.
type: feedback
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**The trap (encountered 2026-04-30 with trade 163 KZ_HUNT EURUSD SHORT 0.39 lots):**

KZ_HUNT split orders place TWO MT5 tickets:
- 60% partial with broker TP at T1
- 40% remainder, no TP (trailing SL managed by trade_monitor)

When BE_PROGRESS fires (price reaches 50% of T1 distance), it moves SL to entry on the **main (remainder) ticket only** — partial keeps its original wide SL. If price then reverses to entry, the main hits BE SL and closes. The partial is still alive but now alone.

Old behavior:
- Reconciliation/trade_monitor sees main missing → marks trade CLOSED with `find_close_deal`-fallback PnL ($0 because IC Markets `history_deals_get(position=ticket)` returns empty).
- Partial keeps running, eventually closes (TP, SL, swap-out, etc).
- Real account balance reflects the loss; trade record says $0; reconciliation reports it as orphaned MT5 position with no DB trade attached.

For trade 163: real balance change -$47.86, DB recorded $0.

**Fix shipped 2026-04-30 (commit 14d5739):**

`reconciliation.py:cross_check_positions` and `trade_monitor.py:_check_trade` both check: if main ticket is missing AND `mt5_ticket_partial` is still in MT5 positions, defer the close (max 30 cycles ≈ 30 min). After defer cap, force-close the partial via `order_manager.close_position` so the trade can finalize cleanly with combined PnL.

**How to apply:**
- Don't add new "missing main ticket → close trade" paths without the same defer-if-partial-alive guard.
- The defer cap (30 cycles) is a safety net for the (rare) case where a broker leaves the partial dangling. In practice the partial should hit TP or SL within minutes of the main closing.
- For backfilling old wrongly-closed trades: don't auto-correct historical PnL records. The account balance is the source of truth; per-trade PnL is best-effort. Cross-check via equity_snapshots when investigating.
