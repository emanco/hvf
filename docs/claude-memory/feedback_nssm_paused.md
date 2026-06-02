---
name: NSSM service can stick in PAUSED state after startup crash loop
description: When the bot crashes during startup (e.g. unhandled exception in __init__), NSSM can interpret the rapid exit as a pause condition and leave the service in SERVICE_PAUSED. `nssm stop/start` doesn't recover it.
type: feedback
originSessionId: aa1ced9c-762c-495d-b4b5-27d6d7d82083
---
If the bot crashes early in startup (before the main loop enters steady state), NSSM's restart-on-exit policy triggers rapid exits that it can interpret as pause signals. The service ends up stuck in `SERVICE_PAUSED` — `nssm.exe status HVF_Bot` shows PAUSED, `nssm continue`/`start`/`stop` all fail to move it.

**Why:** NSSM wraps the application as a Windows service. Windows service states include PAUSED as a legitimate state. On certain exit conditions NSSM parks the service in PAUSED rather than STOPPED, and its own `start`/`continue` commands don't always clear it.

**How to apply:** When you see `SERVICE_PAUSED` persisting through `nssm stop/start`, fall back to Windows' `sc.exe`:

```
sc.exe stop HVF_Bot       # Forces state to STOPPED
sc.exe start HVF_Bot      # Fresh start from STOPPED (not PAUSED)
```

Then fix the actual startup crash. Identify it by running the Python process directly (bypassing NSSM) with stderr redirected so you can see the traceback:

```powershell
Start-Process -FilePath C:\hvf_trader\venv\Scripts\python.exe `
  -ArgumentList "-u C:\hvf_trader\main.py" `
  -WorkingDirectory C:\hvf_trader `
  -RedirectStandardError C:\hvf_trader\logs\manual_stderr.txt `
  -NoNewWindow
```

The bot's own file logging doesn't capture pre-init crashes — only the redirected stderr does.

**Surfaced on 2026-04-22** when a tzinfo TypeError in `circuit_breaker._load_state()` (comparing naive DB datetime to aware `datetime.now(tz=utc)`) surfaced for the first time because the MONTHLY breaker had actually tripped the day before.
