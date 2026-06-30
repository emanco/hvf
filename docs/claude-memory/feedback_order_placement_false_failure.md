---
name: order-placement-can-report-failure-while-the-broker-filled-it
description: "place_market_order returned None on order_send=None / non-DONE retcode; if the broker actually executed, the position orphaned (untracked, unmanaged). Now self-recovers via before/after position diff. Fixed 2026-06-30 (commit 1f934a4)."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3a71573c-5c8d-4e28-8192-fc7a3d01af45
---

**What happened (2026-06-29):** a LONDON_BO GBPUSD trade logged `ERROR: [LONDON_BO] Order placement failed` (main.py:789) — `place_market_order` returned None — but the order **actually executed on the broker** (filled ~08:21 UTC, hit TP, +$85.56). Because the bot thought it failed, it never created a trade_record → orphan: reconciliation warned "MT5 position not found in internal records" for ~a day, the trade ran **unmanaged** (the bot's 13:00 EOD force-close never fired), and only the broker-side TP saved it. The win was invisible to the DB and `/strategies` scorecard.

**Root cause:** `place_market_order` treated `order_send=None` or any non-`TRADE_RETCODE_DONE` retcode (TIMEOUT / lost response / ambiguous) as definitive failure and returned None. Classic "order succeeded but the client thinks it failed."

**Fix (commit 1f934a4, centralized in `order_manager.place_market_order`):** snapshot matching open positions (symbol+magic) BEFORE `order_send`; on a reported failure, `_recover_orphan_fill()` polls MT5 (3× 0.5s) for a NEW position matching symbol+magic+direction and adopts it (returns ticket+fill_price) so the caller logs it normally. The intended limit-style skip (REQUOTE/REJECT/PRICE_OFF when `limit_price` set) still returns None — no false recovery. Benefits ALL callers (LONDON_BO, NIGHT_TIDE, ASB, KZ).

**How to apply:** when a strategy's order "fails", don't trust it blindly — verify against MT5 (positions_get by symbol/magic). This is the same orphan class as [[feedback_disable_limit_strategy_orphans]] and [[feedback_split_order_orphan]]: broker state and DB state diverge. The 2026-06-29 orphan was reconciled into the DB manually as trade 218 (GBPUSD LONDON_BO, +$85.56, pnl_estimated=0).
