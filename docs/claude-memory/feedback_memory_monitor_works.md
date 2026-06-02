---
name: Memory monitor proven useful in production
description: User confirmed the VPS memory alert (added 2026-04-29) caught a low-memory situation on day one and prompted a successful VPS restart.
type: feedback
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
The Telegram memory alert + per-minute heartbeat memory log shipped 2026-04-29 paid off immediately — same day, the user got an alert and restarted the VPS to recover.

**Concrete data from the first firing (2026-04-29):**
- Pre-reboot: 70-80% memory used (~900-1500 MB used of 3 GB).
- Post-reboot: below 50% used (~1500+ MB free).
- The reboot roughly doubled available memory, confirming a real leak somewhere (likely MT5 terminal — Windows MT5 desktop is known to creep over hours/days).
- The 500 MB free threshold fired near the right moment — late enough to avoid false positives, early enough to give recovery margin before OOM.

**Why:** The 3 GB VPS sits at ~900 MB free in steady state, leaving small margin. Without the monitor, low-memory degradation only surfaced when something actually broke. With it, the user gets advance warning and can decide whether to restart MT5 (cheap) or reboot the VPS (full reset) before anything fails.

**How to apply:**
- Keep `MEMORY_ALERT_THRESHOLD_MB = 500` as the default. The user has confirmed 500 MB threshold gives enough lead time without false alarms.
- Don't remove the per-minute memory line from `Scanner heartbeat` — it lets the user (or future debugging) reconstruct memory trends from logs after the fact.
- If MT5 leaks become more frequent, the playbook the user followed (alert → manual VPS restart) is the right floor. Automating MT5 restart is harder; ask before adding that.
- Watch for false alarms during news spikes (when MT5 might briefly balloon). If it fires too often, the threshold should drop to 400 MB before increasing it — i.e. err on the side of more warnings rather than missing the real one.
