---
name: Log timestamps are local time, not UTC
description: HVF bot logs use BST (UTC+1) timestamps on VPS, but config/code references are UTC — easy to misread cause/effect when correlating events.
type: feedback
originSessionId: d108d06f-19a6-4a24-b018-ab64afebd75e
---
`logging.Formatter` uses `time.localtime()` by default. VPS is on Europe/London (BST = UTC+1 in summer), so a log timestamp like `2026-05-22 22:00:00` is **21:00 UTC**. Burned an hour debugging "force-exit fires at hour=22" on 2026-05-22 before realizing this — it was firing at 21:00 UTC on time, just printed in BST.

**Why:** Every hour-comparison in the code uses `datetime.now(timezone.utc).hour`, but every log timestamp prints in local time. When correlating log events to config hours, you must subtract 1 (or 0 in winter, since UK observes DST).

**How to apply:** When reading bot logs:
- Strategy hour comparisons (`capture_utc_hour`, `force_exit_utc_hour`, `exit_hour_utc`, ASB session hours, NIGHT_TIDE windows) are in **UTC**.
- Log timestamps are in **VPS local time (BST/GMT)** — currently +1 hour ahead of UTC in summer.
- Telegram bot timestamps follow whatever the alert code formatted them as (mixed).

Worth fixing properly someday — either format logger to UTC explicitly (`formatter.converter = time.gmtime`), or set VPS to UTC system clock. Until then: when in doubt, subtract one.
