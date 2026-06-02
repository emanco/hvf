---
name: QL force-exit orphan trap
description: QL _force_exit_open_trade used to clear _open_trade_id even when close_position failed, orphaning live broker positions. Fixed; do not regress.
type: feedback
originSessionId: d108d06f-19a6-4a24-b018-ab64afebd75e
---
QL `_force_exit_open_trade` (quantum_london_scanner.py:979) must NEVER clear `_open_trade_id` unless `order_manager.close_position` returned a truthy result. Fixed 2026-05-22 (commit adcf46e) after trade 181 (EURGBP LONG) was orphaned for 4 days when its close attempt collided with IC Markets' 22:00 UTC daily-rollover halt (retcode 10018 "Market closed").

**Why:** Broker SL/TP stay active during a close-rejection, so the position is still risk-bounded — but if the bot loses its reference, no further force-exit retry happens, swap accrues, and PnL drifts silently. Trade 181 cost ~$99 (price + swap) over 4 days as a result.

**How to apply:** Any close/exit primitive in QL (or analog strategies — NIGHT_TIDE, ASB, LB) that's gated on a result check must `return` on failure, not fall through to `_open_trade_id = None`. If introducing a similar exit path elsewhere, mirror this pattern: log WARN, send Telegram alert, return to allow retry on next tick.

**Related: IC Markets rollover halt at 21:00 UTC** — Updated 2026-05-22. The "force-exit fires at 22 not 21" mystery turned out to be a logging-timezone illusion (logs use local BST = UTC+1, not UTC). Force-exit was on time at 21:00 UTC all along, but 21:00 UTC is IC Markets' daily server rollover (23:00 GMT+2) so close orders return retcode 10018 every single day. Fixed by moving `force_exit_utc_hour` to 20 (config.py:459, commit 34df14c). The retry-on-failure fix above is still the safety net — keep both.

**Related: state file destroyed on fill** — Found 2026-05-26 via trade 188 EURCHF (orphaned across 5 deploys). `_clear_pending_state()` was calling `_state_file.unlink()` after a LIMIT filled — wiping the only on-disk record of `_open_trade_id` the instant the trade existed. Any restart between fill and exit = orphan. Compounded by the fill path never calling `_save_state()` and `_try_re_adopt_from_state` having no open-trade branch. Fixed in commit 7cfafc0: state file is now written (not deleted) on every transition, `_save_state()` runs immediately after `_open_trade_id` set, and re-adopt now handles the "saved open_trade_id but no pendings" case by looking up the trade in DB + verifying position alive at broker.
