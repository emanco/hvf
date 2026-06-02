---
name: Never deploy at night
description: No bot deploys during night hours. Deploys disrupt active strategies (QL trading window 22:00→21:00 UTC, NIGHT_TIDE 22:00–01:00 UTC), and the user isn't awake to react if something breaks. Bunch config changes into daytime windows.
type: feedback
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
Never deploy at night.

**Why:** night-hour deploys are disruptive on multiple fronts:
- Quantum London trading window runs 22:00 UTC capture → 21:00 UTC next day. A redeploy mid-window resets the QL tracker from TRADING back to IDLE, killing the captured daily open and the entire session's trading opportunity. Today (2026-05-06) we burned a QL session this way.
- NIGHT_TIDE runs 22:00–01:00 UTC actively scanning 4 cross pairs.
- The user is asleep and not available to validate the deploy succeeded or roll back.
- Reduced log triage / response time if the deploy crashes the service.

**How to apply:**
- Batch all config changes for daytime windows. Roughly: deploy ONLY between ~07:00 UTC (well into European morning) and ~20:00 UTC (before QL's 22:00 capture window).
- If multiple changes are queued, ship them together once not individually.
- If a change is genuinely urgent at night (e.g. preventing live financial loss), ask first before deploying.
- After the QL 22:00 UTC capture, treat the bot as "in flight" until the 21:00 UTC force-exit the next day. Same applies to NIGHT_TIDE active window.
