---
name: Midnight-crossing sessions need special hour comparison logic
description: Simple hour >= X checks break when a session spans midnight (e.g., 22:00 → 05:00 UTC). Always add upper bound guard.
type: feedback
originSessionId: 0be8ebfc-c3f1-483c-92eb-9f4a3c668a41
---
Quantum London's force exit (`hour >= 5`) fired at 22:00 because 22 >= 5. The session runs 22:00-05:00 crossing midnight.

**Why:** Standard hour comparisons assume a single contiguous range within one day. Sessions that cross midnight (22:00 → 05:00) need two-sided bounds: `hour >= exit AND hour < session_start`.

**How to apply:** For any session crossing midnight, use `hour >= exit_hour and hour < open_hour` instead of just `hour >= exit_hour`. This ensures the check only fires in the post-midnight portion (00:00-04:59) not the pre-midnight portion (22:00-23:59).
