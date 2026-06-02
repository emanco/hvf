# HVF Auto-Trader

Automated forex (+ crypto) trading bot running on a Windows VPS via MetaTrader 5.

**Active strategies (as of 2026-06-02):**

| Strategy | Pattern type | Instruments | Timeframe | Edge profile |
|---|---|---|---|---|
| Quantum London | `QUANTUM_LONDON` | EURGBP, EURCHF | M5 (capture at 22:00 UTC) | Mean reversion |
| London Breakout | `LONDON_BO` | GBPUSD | H1 (Asian range, London open) | Breakout |
| Night Tide | `NIGHT_TIDE` | AUDNZD, AUDCAD, NZDCAD, EURCHF | M15 (22-01 UTC) | BB+RSI scalper |
| Asian Session Breakout | `ASIAN_SESSION_BREAKOUT` | GBPJPY, EURJPY | H1 (range at 07:00 UTC) | Breakout |
| BTC Daily Donchian | `BTC_DONCHIAN` | BTCUSD, ETHUSD | D1 (55/20 lookback) | Trend following |

**Disabled** (kept in repo, not running live): KZ_HUNT, HVF.

For deeper architecture, strategy details, and pipeline internals see [CLAUDE.md](./CLAUDE.md).

---

## Continuing on another machine (handoff checklist)

If you're picking up this project on a fresh laptop, work through this in order. Pre-reqs assume macOS but the steps map cleanly to Linux.

```bash
# 1. Clone
git clone https://github.com/emanco/hvf.git ~/dev/hvf
cd ~/dev/hvf

# 2. Python env + deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Local env file (for ad-hoc scripts that hit MT5 — not strictly needed for backtests)
cp .env.example .env
# edit .env with the real credentials (kept in your password manager; never committed)

# 4. SSH alias for the VPS — add to ~/.ssh/config:
cat >> ~/.ssh/config <<'EOF'
Host hvf-vps
    HostName <VPS_IP>
    User Administrator
    IdentityFile ~/.ssh/id_ed25519
EOF
# Copy your existing SSH private key into ~/.ssh/id_ed25519 (or generate a
# new one and add the public key to C:\Users\Administrator\.ssh\authorized_keys
# on the VPS — see "Initial VPS access" below).

# 5. Verify VPS is reachable
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot"
# Expect: SERVICE_RUNNING

# 6. Restore Claude Code memory (so the next AI session has prior context)
mkdir -p ~/.claude/projects/-Users-$(whoami)-dev-hvf/memory
cp docs/claude-memory/*.md \
   ~/.claude/projects/-Users-$(whoami)-dev-hvf/memory/
# The directory name encodes the dev path — if your repo lives somewhere
# other than ~/dev/hvf, adjust accordingly (replace dashes with hyphens in
# the path).

# 7. Verify backtests run locally (no MT5 needed)
python3 backtests/run_crypto_donchian.py | tail -20
# Should print the multi-crypto Donchian results table.
```

If all six steps pass, you're set up to continue work. The bot is the source of truth — your dev machine just edits code, runs backtests, and pushes via `./deploy.sh`.

**What to bring with you (not in the repo):**

| Asset | Where it lives | How to recover |
|---|---|---|
| MT5 broker credentials | Your password manager | Re-issue from broker portal if lost |
| Telegram bot token | Your password manager | Re-create via @BotFather if lost |
| SSH private key for VPS | `~/.ssh/id_ed25519` on old machine | Generate new keypair, add pub to VPS `authorized_keys` |
| VPS Administrator password | Your password manager | Reset via VPS provider console |

**First thing to do on the new machine:**

Read the [CLAUDE.md](./CLAUDE.md) "Current State" section to get up to speed on what the bot is currently doing. Then check the live bot:

```bash
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot; Get-Content 'C:/hvf_trader/logs/main.log' -Tail 20"
```

---

## Setup from a fresh machine

The bot has two parts: **dev machine** (your Mac, where you edit code and run backtests) and **VPS** (Windows Server, where MT5 and the live bot run). `deploy.sh` from the dev machine pushes code to the VPS.

### Prerequisites — accounts you need first

These take ~30 minutes total to set up. Get them BEFORE following the rest of this guide.

1. **Windows VPS** — minimum spec: 3 GB RAM, 30 GB disk, Windows Server 2019+, persistent IP. Providers: Vultr, Contabo, Hetzner Cloud, AWS EC2 (t3.medium+), DigitalOcean. Look for "forex VPS" hosts with low-latency to your broker (London or NY datacenter typically). Cost: ~$15-30/month.
2. **MT5 broker account** — a broker that supports MT5 algorithmic trading. We use IC Markets Demo (`ICMarketsSC-Demo` server). Sign up → you'll receive `MT5_LOGIN` (account number) and `MT5_PASSWORD` by email. Note the server name shown in your account portal.
3. **Telegram bot + chat ID** — open Telegram, message `@BotFather`, send `/newbot`, follow prompts. Save the bot token (`TELEGRAM_BOT_TOKEN`). Then start a chat with your new bot, send any message, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser — find your `chat_id` in the JSON response. That's `TELEGRAM_CHAT_ID`.

### Credential storage (do this once, before anything else)

You'll be juggling 4 sensitive credentials. Store them somewhere recoverable:

| Credential | What it is | Where to store it |
|---|---|---|
| VPS Administrator password | Set by your VPS provider on creation; you change it on first RDP login | Password manager (1Password, Bitwarden, etc.) |
| MT5 login + password | From your broker email | `.env` file on VPS (gitignored) + password manager backup |
| Telegram bot token + chat_id | From @BotFather and getUpdates | `.env` file on VPS (gitignored) + password manager backup |
| SSH private key | Generated by you locally | `~/.ssh/` on dev machine; the corresponding public key goes on the VPS |

**Never** commit credentials to git. **Never** paste them into chat/Telegram/Slack. The `.env` file is gitignored — keep it that way.

### Initial VPS access (one-time)

Most providers give you Administrator credentials and an RDP connection on creation. First login flow:

1. **RDP into the VPS** with the credentials your provider sent. Use Microsoft Remote Desktop (Mac/Windows) or any RDP client.
2. **Change the default Administrator password** on first login (Windows will usually prompt).
3. **Set up SSH access** (so you can manage from your Mac without RDP each time):
   - Install OpenSSH server: PowerShell as Admin →
     `Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0`
   - Start the service: `Start-Service sshd`
   - Set to auto-start: `Set-Service -Name sshd -StartupType 'Automatic'`
   - Open firewall: `New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22`
4. **Add your SSH public key** to the VPS for password-less SSH:
   - On your Mac, copy your public key: `cat ~/.ssh/id_ed25519.pub` (or generate one with `ssh-keygen -t ed25519` if you don't have it).
   - On the VPS: paste it into `C:\Users\Administrator\.ssh\authorized_keys` (create the directory and file if missing).
   - Make sure permissions are tight: only Administrator should be able to read.
5. **Add SSH alias on your Mac** (`~/.ssh/config`):
   ```
   Host hvf-vps
       HostName <VPS_IP>
       User Administrator
       IdentityFile ~/.ssh/id_ed25519
   ```
6. **Test**: `ssh hvf-vps "whoami"` should return `<vps-name>\administrator` without prompting for a password.

### Dev machine (Mac/Linux)

```bash
# 1. Clone
git clone <repo-url> hvf
cd hvf

# 2. Create venv + install deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Add your env vars (only needed if running scripts that hit MT5 from local)
cp .env.example .env
# edit .env with real credentials

# 4. SSH alias should already be set up (see "Initial VPS access" above).
#    Verify with: ssh hvf-vps "whoami"
```

Backtests run locally with no MT5 connection — they read CSVs from `backtests/data/`. The VPS only matters for live trading and pulling fresh OHLC.

### VPS (Windows Server)

One-time bootstrap. Detailed steps:

1. **Verify VPS time zone is UTC** — most providers default to it, but check:
   ```powershell
   Get-TimeZone
   ```
   If not UTC, set it: `Set-TimeZone -Id "UTC"`. The bot uses UTC internally; mismatched system time can confuse log timestamps and Windows Task Scheduler triggers (e.g. the monthly auto-reboot).
2. **Python 3.11+** — install from python.org (NOT the Microsoft Store version; ctypes/MT5 ABI compatibility). Tick "Add Python to PATH" during install.
3. **Install Git** — download from git-scm.com. Default options are fine.
4. **MetaTrader 5 terminal** — install, log in once manually, accept any auth/2FA. Note the install path (default `C:\Program Files\MetaTrader 5\terminal64.exe`). **Do NOT close the terminal yet** — you'll need it open in step 12.
5. **NSSM** — download from nssm.cc, drop `nssm.exe` at `C:\nssm\nssm.exe`.
6. **GitHub auth on VPS** (only if your repo is private). Two options:
   - **Personal Access Token (simplest)**: GitHub → Settings → Developer settings → Tokens → Generate (classic, with `repo` scope). Then `git clone https://<TOKEN>@github.com/<user>/<repo>.git`.
   - **SSH key**: `ssh-keygen -t ed25519` on the VPS, paste the public key into GitHub → Settings → SSH keys, then clone with the SSH URL.
7. **Clone repo** to `C:\hvf_trader\`:
   ```powershell
   git clone <repo-url> C:\hvf_trader
   cd C:\hvf_trader
   ```
8. **Create the logs directory** (NSSM won't create it automatically and will fail to start without it):
   ```powershell
   New-Item -ItemType Directory -Force -Path C:\hvf_trader\logs
   ```
9. **Python venv + deps**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\pip install -r requirements.txt
   ```
10. **Environment file**: copy `.env.example` to `C:\hvf_trader\.env` and fill in MT5 credentials, Telegram tokens, etc. The bot loads from `C:\hvf_trader\.env` directly.
11. **Smoke-test MT5 connection from venv** before installing the service. This catches credential typos and broker connectivity issues before they manifest as service crash loops:
    ```powershell
    C:\hvf_trader\venv\Scripts\python.exe -c "import os; from dotenv import load_dotenv; load_dotenv(r'C:/hvf_trader/.env'); import MetaTrader5 as mt5; ok = mt5.initialize(path=os.getenv('MT5_PATH'), login=int(os.getenv('MT5_LOGIN')), password=os.getenv('MT5_PASSWORD'), server=os.getenv('MT5_SERVER')); print('initialize:', ok); print('account:', mt5.account_info()); mt5.shutdown()"
    ```
    Should print `initialize: True` and a populated AccountInfo struct (balance, login, currency). If it fails, fix `.env` before continuing.
12. **Verify all 6 KZ_HUNT instruments are available** (some demo brokers limit symbol lists):
    ```powershell
    C:\hvf_trader\venv\Scripts\python.exe -c "import os; from dotenv import load_dotenv; load_dotenv(r'C:/hvf_trader/.env'); import MetaTrader5 as mt5; mt5.initialize(path=os.getenv('MT5_PATH'), login=int(os.getenv('MT5_LOGIN')), password=os.getenv('MT5_PASSWORD'), server=os.getenv('MT5_SERVER')); [print(s, mt5.symbol_info(s) is not None) for s in ['EURUSD','NZDUSD','EURGBP','USDCHF','EURAUD','EURJPY','AUDNZD','NZDCAD','AUDCAD','EURCHF','GBPUSD']]; mt5.shutdown()"
    ```
    Each line should print `True`. Any `False` means that symbol isn't enabled on your account — contact your broker or remove that symbol from `INSTRUMENTS` in `config.py`.
13. **Database init**: tables auto-create on first run via `init_db()`. No manual schema setup needed.
14. **Register the NSSM service**:
    ```powershell
    C:\nssm\nssm.exe install HVF_Bot C:\hvf_trader\venv\Scripts\python.exe C:\hvf_trader\main.py
    C:\nssm\nssm.exe set HVF_Bot AppDirectory C:\hvf_trader
    C:\nssm\nssm.exe set HVF_Bot AppStdout C:\hvf_trader\logs\service_stdout.log
    C:\nssm\nssm.exe set HVF_Bot AppStderr C:\hvf_trader\logs\service_stderr.log
    C:\nssm\nssm.exe set HVF_Bot AppExit Default Restart
    C:\nssm\nssm.exe set HVF_Bot AppRestartDelay 5000
    C:\nssm\nssm.exe set HVF_Bot Start SERVICE_AUTO_START
    ```
15. **Critical: set service to run as user account, NOT LocalSystem**.
    When NSSM runs as `LocalSystem` (the default), the MT5 terminal it
    spawns uses a system profile where AutoTrading is OFF by default —
    every order will fail with `retcode 10027 "AutoTrading disabled"`.
    Run as your user instead so MT5 inherits the user's saved settings:
    ```powershell
    C:\nssm\nssm.exe set HVF_Bot ObjectName ".\Administrator" "<password>"
    ```
16. **Enable AutoTrading on the user's MT5** (one time, via the open MT5 from step 4):
    Click the "Algo Trading" toggle in the MT5 toolbar (or Tools → Options → Expert Advisors → "Allow algorithmic trading"). This setting saves to the user's MT5 profile and is inherited by every future bot-spawned terminal.
17. **Start the service**:
    ```powershell
    C:\nssm\nssm.exe start HVF_Bot
    ```
18. **Verify AutoTrading is on** (sanity check via a fresh terminal init):
    ```powershell
    C:\hvf_trader\venv\Scripts\python.exe -c "import os; from dotenv import load_dotenv; load_dotenv(r'C:/hvf_trader/.env'); import MetaTrader5 as mt5; mt5.initialize(path=os.getenv('MT5_PATH'), login=int(os.getenv('MT5_LOGIN')), password=os.getenv('MT5_PASSWORD'), server=os.getenv('MT5_SERVER')); ti = mt5.terminal_info(); print(f'trade_allowed={ti.trade_allowed}'); mt5.shutdown()"
    ```
    Expect `trade_allowed=True`. If False, repeat step 16 then restart the service.
19. **First-run validation** (watch the bot for ~3 minutes):
    ```powershell
    Get-Content C:\hvf_trader\logs\main.log -Wait -Tail 30
    ```
    What you should see, in order:
    - `MT5 connected: login=... server=... balance=... USD` (within 30s of start)
    - `Loaded N armed patterns from DB` (probably 0 on first run)
    - `Trade monitor started (poll=1s, ...)`
    - `[QUANTUM_LONDON] Scanner thread started`
    - `Starting scanner loop...`
    - One full scan cycle across all instruments (`Scan EURUSD: ... candidates`)
    - `Scanner heartbeat: cycle=1 armed=N mem=XXX/3071MB (XX%used)` — the first per-minute heartbeat
    - A `✅ Bot online` Telegram alert on your phone

    Press Ctrl-C to exit `-Wait` mode once you've seen the heartbeat.
20. **Verify nothing in errors.log** during the first 5 minutes:
    ```powershell
    Get-Content C:\hvf_trader\logs\errors.log -Tail 20
    ```
    Some `Risk check FAILED [rrr_check]` warnings are normal — those are armed patterns that didn't pass risk gates. Other ERROR lines should be investigated.
21. **Telegram sanity**: send `/status` to your bot — should reply with account state.

Going forward, all code changes go through `./deploy.sh` from the dev machine.

### Required environment variables

See `.env.example` for the full list. Minimum required:

| Variable | Purpose |
|---|---|
| `MT5_LOGIN` | MT5 account number |
| `MT5_PASSWORD` | MT5 account password |
| `MT5_SERVER` | Broker server (e.g. `ICMarketsSC-Demo`) |
| `MT5_PATH` | Path to `terminal64.exe` |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID for alerts |

---

## Bot operations from your Mac

Your SSH config has the alias `hvf-vps` — these run remotely from your Mac terminal.

### One-liner restart

```bash
ssh hvf-vps "C:\nssm\nssm.exe restart HVF_Bot"
```

### Common commands

```bash
# Check if bot is running
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot"

# Stop the bot
ssh hvf-vps "C:\nssm\nssm.exe stop HVF_Bot"

# Start the bot
ssh hvf-vps "C:\nssm\nssm.exe start HVF_Bot"

# See last 20 log lines
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/main.log' -Tail 20"

# See errors only
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/errors.log' -Tail 20"

# See trade events only
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/trades.log' -Tail 20"
```

### Telegram-only (no SSH needed)

The bot exposes these Telegram commands directly in chat:

- `/status` — open trades + balance
- `/health` — MT5 connection state
- `/trades` — recent trade history
- `/equity` — equity chart
- `/balance` — account balance
- `/closeall` — emergency close everything

### When to use what

| Situation | Action |
|---|---|
| Bot acting weird, want a clean slate | `restart` |
| Memory alert from Telegram | Restart MT5 terminal first (via VPS RDP). Only restart the bot if that doesn't help. |
| Bot service stuck in `PAUSED` state (rare) | `ssh hvf-vps "sc.exe stop HVF_Bot; sc.exe start HVF_Bot"` — NSSM occasionally gets wedged after crash loops. |
| Need to deploy new code | `./deploy.sh` from this repo — stops bot, uploads, clears `__pycache__`, restarts. |
| Anything destructive (closing positions, modifying DB) | Pause and check first. |

### Troubleshooting

**Symptom: orders fail with `retcode=10027 "AutoTrading disabled by client"`**
The MT5 terminal the bot is talking to has AutoTrading off. Two possible
causes:
1. NSSM service is running as `LocalSystem` instead of a user account →
   bot spawned its own MT5 with system profile (fresh, AutoTrading off
   by default). Fix: `nssm set HVF_Bot ObjectName ".\Administrator" "<pw>"`
   then restart bot.
2. The user's MT5 profile doesn't have AutoTrading enabled → enable it
   manually once via RDP (toolbar toggle or Tools → Options).

**Symptom: bot crash-loops with `MT5 initialize failed: (-10005, IPC timeout)`**
Stale MT5 terminals from a different user session are blocking the
bot's spawn. Find them:
```bash
ssh hvf-vps "Get-Process terminal64 | Format-Table Id,SessionId"
```
Kill any in `Session 0` from a previous LocalSystem run, then restart
the bot — it'll spawn a fresh one in the user account's session.

**Symptom: every KZ_HUNT pattern rejected with `entry drift Xp > max 3p`**
Drift gate is too tight for the timeframe. Default values in
`config.py`:
- `MAX_ENTRY_DRIFT_PIPS = 6.0` (non-JPY)
- `MAX_ENTRY_DRIFT_PIPS_JPY = 12.0` (JPY crosses)
On M30 these are right; on a slower timeframe you might widen further,
on a faster one tighten. Watch the `Skipping ... entry drift Xp` logs to
calibrate.

**Symptom: QL Telegram says "Session ended — execution failed"**
The trigger crossed and the bot tried to fire, but the order was
rejected. Almost always AutoTrading off (see first symptom above), or
broker margin / lot-size limits. Check `logs/main.log` for the exact
`Order failed: retcode=...` line.

### Memory monitoring

The bot logs system memory in every minute's heartbeat:

```
Scanner heartbeat: cycle=3 armed=2 mem=951/3071MB (69%used)
```

If free physical memory drops below 500 MB, you'll get a Telegram alert (throttled to once per 6 hours). Standard recovery:

1. **First**: log into VPS via RDP, close & reopen the MT5 terminal — most memory leaks come from MT5 itself, not the bot.
2. **If memory stays low after that**: reboot the VPS. The bot will auto-restart on boot via NSSM.
3. **Adjust threshold** in `hvf_trader/config.py`: `MEMORY_ALERT_THRESHOLD_MB = 500`.

---

## Repository layout

```
hvf_trader/             # Bot package
├── main.py             # Scanner loop + entry orchestration
├── config.py           # All strategy + system parameters
├── detector/           # Pattern detectors (KZ Hunt, Night Tide, etc.)
├── execution/          # Order manager, trade monitor, MT5 connector
├── risk/               # Circuit breaker, position sizer, risk gates
├── monitoring/         # Health check, reconciliation, memory monitor
├── alerts/             # Telegram bot + commands
└── data/               # OHLC fetcher, indicators, news filter

backtests/              # Local backtest data + chart outputs
├── data/               # H1/M30/M15/M5 CSVs per pair (incl. BTCUSD, ETHUSD, US500)
├── charts/             # PNG outputs from backtest scripts
├── run_daily_donchian*.py   # Donchian backtests (FX, BTC+US500, walk-forward)
├── run_crypto_donchian.py   # Multi-crypto Donchian sweep
├── run_ql_news_filter.py    # News filter overlay test on QL EURCHF
└── run_asb_threshold_compare.py  # ASB 0.4 vs 0.3 threshold test

docs/                   # Project documentation
└── claude-memory/      # Snapshot of Claude Code auto-memory (see README inside)

scripts/                # Operational + analysis scripts
├── spread_snapshot.py        # On-demand broker spread capture (replaces old continuous sampler)
└── (various deploy/inspect helpers run from VPS)

deploy.sh               # Stop bot, upload, clear cache, restart
CLAUDE.md               # Detailed project guide for AI / new contributors
```

---

## Quick health check

```bash
# Two commands cover 90% of operations
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot; Get-Content 'C:/hvf_trader/logs/main.log' -Tail 20"
```

If status is `SERVICE_RUNNING` and the recent log shows scanner/trade-monitor heartbeats, all good.
