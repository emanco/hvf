---
name: Telegram summary must match MT5 broker figures
description: User wants Telegram daily summary PnL/balance/equity to match the MT5 daily confirmation email exactly
type: feedback
originSessionId: f501baf1-25a0-4127-bd25-05baff95b8a7
---
Telegram daily summary must show PnL, balance, and equity that match the MT5 broker email.

**Why:** The bot's DB-tracked PnL diverges from MT5 because it misses swaps, commissions, and the T1 partial leg of split orders (60% position closed broker-side via TP). This caused a -$67.43 vs -$17.31 discrepancy on a single day.

**How to apply:** Always derive financial figures (PnL, balance, equity) from MT5 directly or from EquitySnapshot data — never from summing DB trade PnL. Per-pair trade stats (count, win rate, pips) can still come from the bot DB since those are the bot's analytical view.
