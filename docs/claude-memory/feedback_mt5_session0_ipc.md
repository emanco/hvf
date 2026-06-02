---
name: MT5 IPC timeout in NSSM Session 0
description: After VPS reboot or NSSM-launched bot tries to spawn its own MT5 terminal, mt5.initialize() can hit IPC timeout (-10005) because the spawned terminal sits without a logged-in account. Always pass credentials to initialize() — don't rely on a separate mt5.login() call.
type: feedback
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**The trap**: NSSM runs the HVF bot as `LocalSystem` in Windows Session 0 (service session). When `mt5.initialize(path=...)` spawns a fresh MT5 terminal there, that terminal has no GUI desktop attached and no saved credentials (LocalSystem doesn't share the user profile where MT5 saves logins). It sits at the login screen, waiting. The IPC connection between the python MetaTrader5 module and that terminal can't establish, hits the 60s timeout, returns -10005.

The bot then exits, NSSM restarts it (5s delay), repeats the loop forever. Service status shows `SERVICE_RUNNING` because NSSM is alive, but the actual python process keeps dying.

Symptoms:
- Log spam: `MT5 initialize failed: (-10005, 'IPC timeout')` → `Failed to connect to MT5. Exiting.` repeating every ~70s.
- Multiple `terminal64.exe` processes accumulating in Session 0 (each restart spawns one before failing).
- User sees nothing on RDP because Session 0 terminals are headless.

**Fix**: pass credentials directly to `mt5.initialize()`:

```python
mt5.initialize(
    path=config.MT5_PATH,
    login=config.MT5_LOGIN,
    password=config.MT5_PASSWORD,
    server=config.MT5_SERVER,
    timeout=60000,
)
```

This makes spawn + login a single atomic step — the spawned terminal authenticates immediately and IPC works.

**Why:** With separate `initialize()` then `login()` calls, the python module's `initialize()` blocks waiting for the terminal to be in a "ready" state — which a credentialless terminal in Session 0 can never reach.

**How to apply:**
- Already shipped (commit `edc195d`, 2026-04-29) in `hvf_trader/execution/mt5_connector.py`.
- If similar pattern appears in other connector code (e.g. test scripts), apply the same fix.
- Diagnostic: when "MT5 initialize failed: IPC timeout" appears repeatedly, check `Get-Process terminal64 | Format-Table Id,SessionId` — if Session 0 terminals are accumulating, this is the bug.
- Recovery without code change: kill all Session 0 `terminal64.exe` processes (`Stop-Process`), let the next bot restart spawn one with credentials baked in. The `edc195d` fix removes the need for this manual step.

**Side benefit of the fix**: bot now self-recovers from VPS reboots without manual RDP-in to start MT5.
