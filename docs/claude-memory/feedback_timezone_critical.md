---
name: Timezone is critical for Asian session strategies
description: Using 00:00 UTC vs 22:00 UTC (GMT+2) as daily open completely changes strategy results. Always verify timezone assumptions.
type: feedback
originSessionId: 0be8ebfc-c3f1-483c-92eb-9f4a3c668a41
---
The Quantum London strategy went from negative (-37 pips) to 95% WR (+415 pips) by changing the daily open reference from 00:00 UTC to 22:00 UTC (00:00 GMT+2).

**Why:** IC Markets and the ForexFactory community use GMT+2 as the daily candle start (22:00 UTC). The 2-hour difference gives extra drift time before the Asian trading window, creating more reliable mean-reversion setups.

**How to apply:** For any strategy that references "daily open" or "session open," always check whether it means UTC, GMT+2 (broker server time), or local time. Test both before assuming. The IC Markets MT5 server runs on UTC+2 (UTC+3 during European summer/DST).
