---
name: NSSM service must run as user account, not LocalSystem (for MT5 AutoTrading)
description: Running the bot as LocalSystem makes mt5.initialize() spawn an MT5 with a system-account profile, where AutoTrading is off by default. Orders fail with retcode 10027. Run NSSM service as a real user account to inherit MT5 settings.
type: feedback
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**The trap (encountered 2026-04-30)**:

When NSSM runs the bot as `LocalSystem`, the MT5 terminal spawned by `mt5.initialize()` runs under the LocalSystem profile (`C:\Windows\System32\config\systemprofile\AppData\Roaming\MetaQuotes\Terminal\<hash>\`). That profile is fresh — no saved AutoTrading=enabled setting. Every order returns `retcode=10027 "AutoTrading disabled by client"`.

The user's RDP-session MT5 with AutoTrading enabled lives in a different user profile (`C:\Users\Administrator\AppData\Roaming\MetaQuotes\...`). The bot can't reach it because it's in a different user's data directory.

**Fix**: reconfigure NSSM to run as a real user account (Administrator on this VPS).

```bash
# From local Mac:
ssh hvf-vps "C:\nssm\nssm.exe stop HVF_Bot"

# User runs themselves (password not exposed):
ssh hvf-vps 'C:\nssm\nssm.exe set HVF_Bot ObjectName ".\administrator" "PASSWORD"'

ssh hvf-vps "C:\nssm\nssm.exe start HVF_Bot"
```

Once running as Administrator, mt5.initialize() spawns MT5 using `C:\Users\Administrator\AppData\...` profile, which inherits AutoTrading=enabled from prior user sessions. Verified: `mt5.terminal_info().trade_allowed = True`.

**Watch out for**:
- After switching to user-account, kill any leftover Session 0 terminals from when service was LocalSystem (they have wrong profile and bot may attach to one of them on restart instead of spawning fresh).
- The `terminal_info()` check `trade_allowed=True` should be added to the bot's startup as a Telegram-alerted sanity check — currently we discover AutoTrading is off only when an order fails. Future improvement.
- `query session` command on VPS shows session structure: `services` (Session 0) for LocalSystem services, named per-user sessions for RDP logins. The bot service still runs in its own session even when configured as a user account, but uses that user's profile (which is what matters for MT5).

**Repository setup docs need updating**: `README.md` step 8 (NSSM register) currently doesn't specify `ObjectName`. Should add a step: "Set NSSM service to run as Administrator with `nssm set HVF_Bot ObjectName .\Administrator <password>` so MT5 inherits user profile + AutoTrading toggle."
