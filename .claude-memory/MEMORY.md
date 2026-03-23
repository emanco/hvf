# HVF Auto-Trader Project Memory

## Project Overview
- HVF (Hunt Volatility Funnel) + KZ Hunt automated forex trading bot
- Deployed to VPS: 198.244.245.3 (SSH alias: `hvf-vps`, Windows Server, PowerShell)
- MT5 demo: IC Markets, login 52774919, account currency USD
- Instruments: EURUSD, NZDUSD, EURGBP, USDCHF, EURAUD
- **Live patterns**: HVF (excl EURUSD, EURGBP) + KZ Hunt (all 5 pairs). Viper DISABLED (net -160p/10yr)
- Tech: Python, MetaTrader5 lib, SQLAlchemy, Telegram alerts
- Repo: https://github.com/emanco/hvf.git (branch: main)
- **Go-live date**: 2026-03-13 (test trades before this deleted from DB)

## Key Files
- See [architecture.md](architecture.md) for full file structure
- Core pipeline: zigzag -> detect_hvf -> score -> arm -> confirm entry -> execute
- Backtest engine reuses same detector/risk code

## VPS Operations
- SSH: `ssh hvf-vps` (alias configured locally)
- Project path: `C:\hvf_trader\` — entry point is `C:\hvf_trader\main.py`
- Python venv at `C:\hvf_trader\venv\`
- **PowerShell**: `&&` invalid, use `;` for chaining commands
- Open trades survive restarts — trade monitor loads from DB every 30s.

### Deploy
```bash
./deploy.sh    # from repo root — uploads, clears __pycache__, restarts bot
```

### Bot Control (NSSM service)
```powershell
# On VPS (or prefix with: ssh hvf-vps)
C:\nssm\nssm.exe start HVF_Bot
C:\nssm\nssm.exe stop HVF_Bot
C:\nssm\nssm.exe restart HVF_Bot
C:\nssm\nssm.exe status HVF_Bot
```
- Auto-starts on boot, auto-restarts on failure (5s delay)
- Runs headless (no console window) — monitor via logs

### Logs
```powershell
Get-Content C:\hvf_trader\logs\main.log -Tail 20       # all activity
Get-Content C:\hvf_trader\logs\trades.log -Tail 20      # trade events only
Get-Content C:\hvf_trader\logs\errors.log -Tail 20      # warnings/errors
Get-Content C:\hvf_trader\logs\service_stdout.log -Tail 20  # NSSM stdout
```

### Quick Health Check (from Mac)
```bash
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/main.log' -Tail 10 -ErrorAction SilentlyContinue; exit 0"
```

---

## Current LIVE Config — V7 (deployed 2026-03-13)
```
ENABLED_PATTERNS = ["HVF", "KZ_HUNT"]  # Viper DISABLED
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
PATTERN_SYMBOL_EXCLUSIONS = {"HVF": ["EURUSD", "EURGBP"]}
MIN_RRR_BY_PATTERN = {"HVF": 1.5, "KZ_HUNT": 1.0}
RISK_PCT_BY_PATTERN = {"HVF": 1.0, "KZ_HUNT": 1.0}
MAX_CONCURRENT_TRADES = 6, PARTIAL_CLOSE_PCT = 0.60
MIN_STOP_PIPS_BY_PATTERN = {"KZ_HUNT": 8, "HVF": 5}  # KZ lowered from 15 on 2026-03-23
TRAILING: KZ 1.0x ATR, HVF 1.5x ATR
DAILY/WEEKLY/MONTHLY LIMITS: 5%/8%/15%
```

## Key Features
- **SL from actual fill**: recalculates stop distance after MT5 fill, modifies if needed
- **Live vs backtest tracking**: slippage, intended_entry/sl stored per trade, weekly Telegram report
- **Rolling Sharpe**: 60-day window, alert at <0.5 (reduce size), <0.0 (halt)
- **WR decay**: alerts if recent WR drops >15pp below all-time
- **Kill switch**: auto-halt if PF < 1.2 after 200+ trades (trips circuit breaker, manual restart needed)
- **Performance Monitor**: hourly health checks with Telegram alerts + 24h cooldown
- **Weekly Summary**: Telegram digest on Sundays 21:00 UTC with per-pattern breakdown + slippage + invalidation stats
- **Stale pattern cleanup**: armed patterns where price moved >2x stop-distance immediately expired
- **Dedup Guard**: checks open trades, armed patterns, recently triggered (24h) before arming
- **News Filter**: ForexFactory calendar, blocks 30min before/after high-impact events
- **Spread compensation**: SL widened by current spread at entry
- **Min stop guard**: reject if < max(5x spread, pattern min pips)
- **SQLite WAL mode**: better concurrent access across scanner/monitor/health threads
- **Startup reconciliation**: DB vs MT5 position cross-check with Telegram alerts on mismatch
- **Telegram commands**: Interactive bot via polling — /status, /health, /trades, /equity, /balance, /help (authorized chat_id only). See `hvf_trader/alerts/telegram_commands.py`
- **Daily recap**: Equity chart (matplotlib) sent as photo, skips weekends (Mon-Fri only)

## Expert Panel TODO — see [expert-panel-findings.md](expert-panel-findings.md)
### Done (2026-03-13)
Deploy script, NSSM service, WAL mode, SL from fill price, live vs backtest tracking, rolling Sharpe + WR decay, kill switch, go-live date cutoff

### Remaining (Over Time)
1. Portfolio correlation guard (3+ same-direction USD/EUR exposure)
2. Backtest alternative SL (0.3x ATR trail)
3. Regime filter (20-day vol percentile)
4. Monte Carlo simulation (10K runs)
5. Per-pair daily trade limit (max 2 KZ per pair)

## Walk-Forward Validation (2026-03-23) — 12m train / 3m test / 3m step
All 5 pairs, HVF+KZ_HUNT, 11.3 years data, $700 starting equity.

| Metric | Value |
|--------|-------|
| Total OOS trades | 4,718 |
| OOS Win Rate | 61.0% |
| OOS Profit Factor | **1.50** |
| OOS Total Pips | +13,483 |
| Positive OOS windows | **162/205 (79%)** — robust |

Per-pair OOS: EURUSD PF=1.68 (37/41 windows), NZDUSD PF=1.69 (36/41), EURGBP PF=1.47 (31/41), USDCHF PF=1.52 (30/41), EURAUD PF=1.33 (28/41).
KZ_HUNT dominates: 4,656 trades PF=1.53. HVF: only 62 trades PF=0.91 (very selective).
Chart: `backtests/charts/bt_walkforward.png`

## 10-Day Demo Review & Fixes (2026-03-23)
- **P0 Fixed**: KZ_HUNT MIN_STOP_PIPS 15->8. Was blocking ALL KZ entries (28 armed, 0 executed).
- **P1 Fixed**: Invalidation grace period — 2hr delay before checking H3/L3 revisit. Was killing 7/11 trades prematurely.
- **P2 Fixed**: Server-close tracking — 7-day deal history, ticket update after partial close, breakeven fallback instead of 0.0.
- **P3 Fixed**: SQLAlchemy scoped_session for thread-safe DB access.
- **SL recalc fix**: Was using `abs(pattern.entry_price - pattern.stop_loss)` (stale detection-time geometry) producing 2-5 pip stops. Now uses `abs(live_entry - adjusted_sl)` (validated pre-order distance). Added post-fill min-stop guard fallback. See main.py:748-765.
- **FX lookup warning fix**: `get_symbol_info(quiet=True)` for expected FX pair misses (e.g. CHFUSD).
- **KZ ATR buffer tested**: 1.0x ATR backtested worse than 0.5x (PF 1.30 vs 1.51). Kept 0.5x.
- **XAUUSD ruled out**: 0 HVF patterns on any timeframe (H1/H4/D1) at any zigzag sensitivity over 28 years.

## Known Issues / Watch Items
1. **Spread widening risk**: SL spread compensation only at entry. Off-hours widening could clip tight stops.
2. **London Sweep**: coded but net negative, not enabled
3. **Backtest gap**: doesn't account for FX conversion in equity curves (pip metrics still valid)
4. **HVF low volume**: Only 62 OOS trades in 11yr — consider if HVF adds value or just complexity

# currentDate
Today's date is 2026-03-23.
