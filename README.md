# HVF Auto-Trader

Automated forex trading bot running on a Windows VPS via MetaTrader 5.
Active strategies: **KZ_HUNT**, **Quantum London**, **London Breakout**, **Night Tide**.

For deeper architecture, strategy details, and pipeline internals see [CLAUDE.md](./CLAUDE.md).

---

## Setup from a fresh machine

The bot has two parts: **dev machine** (your Mac, where you edit code and run backtests) and **VPS** (Windows Server, where MT5 and the live bot run). `deploy.sh` from the dev machine pushes code to the VPS.

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

# 4. Add SSH alias for the VPS in ~/.ssh/config
# Host hvf-vps
#     HostName <VPS_IP>
#     User Administrator
#     IdentityFile ~/.ssh/<your-key>
```

Backtests run locally with no MT5 connection — they read CSVs from `backtests/data/`. The VPS only matters for live trading and pulling fresh OHLC.

### VPS (Windows Server)

One-time bootstrap. Detailed steps:

1. **Python 3.11+** — install from python.org (NOT the Microsoft Store version; ctypes/MT5 ABI compatibility).
2. **MetaTrader 5 terminal** — install, log in once manually, accept any auth/2FA. Note the install path (default `C:\Program Files\MetaTrader 5\terminal64.exe`).
3. **NSSM** — download from nssm.cc, drop `nssm.exe` at `C:\nssm\nssm.exe`.
4. **Clone repo** to `C:\hvf_trader\`:
   ```powershell
   git clone <repo-url> C:\hvf_trader
   cd C:\hvf_trader
   ```
5. **Python venv + deps**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\pip install -r requirements.txt
   ```
6. **Environment file**: copy `.env.example` to `C:\hvf_trader\.env` and fill in MT5 credentials, Telegram tokens, etc. The bot loads from `C:\hvf_trader\.env` directly.
7. **Database init**: tables auto-create on first run via `init_db()`. No manual schema setup needed.
8. **Register the NSSM service** (one time):
   ```powershell
   C:\nssm\nssm.exe install HVF_Bot C:\hvf_trader\venv\Scripts\python.exe C:\hvf_trader\main.py
   C:\nssm\nssm.exe set HVF_Bot AppDirectory C:\hvf_trader
   C:\nssm\nssm.exe set HVF_Bot AppStdout C:\hvf_trader\logs\service_stdout.log
   C:\nssm\nssm.exe set HVF_Bot AppStderr C:\hvf_trader\logs\service_stderr.log
   C:\nssm\nssm.exe set HVF_Bot AppExit Default Restart
   C:\nssm\nssm.exe set HVF_Bot AppRestartDelay 5000
   C:\nssm\nssm.exe set HVF_Bot Start SERVICE_AUTO_START
   C:\nssm\nssm.exe start HVF_Bot
   ```
9. **Telegram check**: send `/status` to your bot — should reply with account state.

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
├── data/               # H1/M30/M15/M5 CSVs per pair
└── charts/             # PNG outputs from backtest scripts

scripts/                # Backtest + analysis scripts
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
