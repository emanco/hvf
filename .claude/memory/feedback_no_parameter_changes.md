---
name: No parameter changes during stabilization
description: Don't suggest parameter tweaks or optimizations until system has collected enough clean live data (50+ trades)
type: feedback
---

Don't propose parameter changes, invalidation tweaks, or config optimizations while the system is still stabilizing after bug fixes.

**Why:** The bot spent its first 2 weeks (2026-03-13 to 2026-03-27) in a constant bug-fix cycle — scanner crashes, dedup blockades, corrupted data, dead periods. The system only became fully operational on 2026-03-27. User explicitly agreed to leave invalidation as-is despite backtest showing marginal pip cost, because there's no clean live data to validate against yet.

**How to apply:** When backtest results suggest a possible improvement, present the finding but recommend collecting live data first before making changes. Don't suggest deploying parameter tweaks until at least 50 clean KZ_HUNT trades have been recorded (from 2026-03-25 onward). The priority is stability and data collection, not optimization.
