---
name: disabling-a-limit-order-strategy-orphans-broker-side-artifacts
description: Setting a QL-style scanner enabled=False mid-cycle orphans its filled limit fills AND resting pending orders — reconciliation never adopts MT5→DB. Flatten manually after retiring.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3a71573c-5c8d-4e28-8192-fc7a3d01af45
---

When retiring a limit-order strategy like [[project_quantum_london]] (QL places resting limit orders at trigger ±Np at the 22:00 capture, force-exits at 20:00 UTC), just flipping `enabled: False` and deploying is NOT clean. The scanner thread that placed and managed the orders is gone, but the broker still holds:
1. **Any limit order that already filled** — becomes a live position that is NOT in `trade_records` (it was a pending-order ticket, never logged as an OPEN trade). Reconciliation only CLOSES DB trades missing from MT5; it never adopts an MT5 position into the DB. So the fill is a true orphan: untracked, and its eventual PnL never lands in `trade_records` (balance just steps down with no matching row).
2. **Any still-resting pending order** — nothing cancels it, so it can fill *later* into a fresh unmanaged position.
3. The position keeps its broker-side SL/TP, so it won't run away — but it loses the strategy's time-exit (QL's actual edge: backtest had 0 SLs hit, all losses were 20:00 time exits), so the risk profile worsens.

**Why:** disabling a scanner kills the only thing managing its orders; the bot's DB-driven management/reconciliation has no hook for orders the DB never knew about.

**How to apply:** after disabling a limit-order strategy, check `mt5.positions_get()` AND `mt5.orders_get()` for that strategy's symbols/comment, and manually flatten (`TRADE_ACTION_REMOVE` for pending, `TRADE_ACTION_DEAL` opposite-side for the position). Done 2026-06-22 when retiring QL: cancelled EURGBP sell-limit 1718412436, closed orphaned EURGBP long 1718412061 for -$34.21.
