# HVF Auto-Trader Project Memory

## Project Overview
- HVF (Hunt Volatility Funnel) + KZ Hunt automated forex trading bot
- Deployed to VPS: 198.244.245.3 (SSH alias: `hvf-vps`, Windows Server, PowerShell)
- MT5 demo: IC Markets, login 52774919, account currency USD
- Instruments: EURUSD, NZDUSD, EURGBP, USDCHF, EURAUD
- **Live patterns**: KZ Hunt only (all 5 pairs). HVF DISABLED 2026-03-25 (PF=0.06 live, 27T). Viper DISABLED (net -160p/10yr)
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

## Current LIVE Config — V8 (deployed 2026-03-25, perf window reset 2026-03-25)
```
ENABLED_PATTERNS = ["KZ_HUNT"]  # HVF disabled (PF=0.06 live), Viper disabled
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
MIN_RRR_BY_PATTERN = {"KZ_HUNT": 1.0}
RISK_PCT_BY_PATTERN = {"KZ_HUNT": 1.0}
MAX_CONCURRENT_TRADES = 6, PARTIAL_CLOSE_PCT = 0.60
MIN_STOP_PIPS_BY_PATTERN = {"KZ_HUNT": 8}
TRAILING: KZ 1.0x ATR
DAILY/WEEKLY/MONTHLY LIMITS: 5%/8%/15%
PERF_GO_LIVE_DATE = "2026-03-25"  # reset from 03-13 due to corrupted trade data
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
- **SQLite WAL mode + busy_timeout=5s**: concurrent access across scanner/monitor/health threads
- **Thread-local DB sessions**: each thread gets its own SQLAlchemy session via scoped_session property
- **Double-close guard**: `log_trade_close` skips already-CLOSED records to prevent PnL overwrite
- **Commit rollback**: all DB commits wrapped in try/except with session.rollback()
- **Armed patterns thread lock**: `threading.Lock` protects shared list across scanner/telegram threads
- **Startup reconciliation**: DB vs MT5 position cross-check with Telegram alerts on mismatch
- **Telegram commands**: Interactive bot via polling — /status, /health, /trades, /equity, /balance, /closeall, /help (authorized chat_id only). See `hvf_trader/alerts/telegram_commands.py`
- **Daily recap**: Equity chart (matplotlib) sent as photo, skips weekends (Mon-Fri only)
- **Backtest invalidation**: backtest_engine.py now supports KZ_HUNT invalidation exits (H3/L3 revisit with 2-bar grace period), matching live behavior
- **Non-blocking Telegram**: send_message/send_photo queued to background thread — never blocks scanner/monitor
- **ATR cache**: trailing stop ATR fetches cached per symbol (120s TTL) — avoids redundant data pulls
- **Actual fill prices**: close_position and partial_close both return real MT5 fill price, used in PnL calculation

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

## Bugs Fixed (2026-03-25)
- **Ghost close prevention**: Retry + symbol scan + 2 consecutive misses required before marking closed. Final safety check in `_handle_server_close` skips close if position still alive. See `trade_monitor.py:94-115, 399-408`.
- **Deal misattribution**: Close deal validation — checks deal type (SELL for LONG close, BUY for SHORT) and timestamp (must be after trade open). See `trade_monitor.py:432-458`.
- **Reconciliation re-adopt**: Falsely-closed trades automatically reopened when MT5 position still exists. See `reconciliation.py:87-135`.
- **Trailing stop debug logging**: `[TRAIL_DEBUG]` on every evaluation for visibility.
- **HVF disabled**: Removed from ENABLED_PATTERNS after 27 live trades at PF=0.06.
- **`/closeall` command**: Telegram command to close all open trades + expire armed patterns with confirmation. Two-step: shows summary, requires "yes" reply.
- **pattern_type not saved**: `log_trade_open` dict was missing `pattern_type` — all trade_records stored NULL. Fixed by adding the field to the dict in `main.py:818`.

## Bugs Fixed (2026-03-26)
- **DetachedInstanceError crash loop**: Scanner completely dead since 2026-03-25 deploy. `PatternRecord` ORM objects stored in `_armed_patterns` became expired after `session.commit()` calls (SQLAlchemy `expire_on_commit=True` default). Accessing `record.symbol` triggered lazy reload on detached instance → crash every 60s. Fix: snapshot records into `types.SimpleNamespace` via `_detach_record()` helper at storage time. See `main.py:54-78`. **Impact**: ~24h with no trade entries possible.

## Bugs Fixed (2026-03-27)
- **Rejected patterns blocking new entries for 24h**: When `_attempt_entry` confirmed a pattern but risk check rejected it (RRR too low, lot size=0, SL too close), pattern stayed ARMED in DB. Dedup guard checks DB for ARMED/TRIGGERED in last 24h → one rejection per pair locked that pair out for a full day. Fix: mark patterns as REJECTED on risk/SL/order failure. REJECTED not in dedup filter so fresh patterns arm immediately. See `main.py` `_attempt_entry`.
- **Trade monitor session error** (one-off): `InvalidRequestError: session in 'prepared' state` at 01:14 UTC. Fixed in 2026-03-30 thread safety overhaul (thread-local sessions).

## Bugs Fixed (2026-03-30) — Full System Audit & Fix (10 bugs, 9 files)
### Phase 1 — Stop the bleeding:
- **Double-close guard**: `log_trade_close` now skips if trade already CLOSED. Prevents reconciliation from overwriting real PnL with stale 0.0 data. Was root cause of 4/8 trades showing 0.0 PnL (reconciliation raced trade monitor).
- **Reconciliation PnL**: `reconciliation.py` now looks up MT5 deal history for close price/PnL (same logic as trade_monitor). Falls back to trailing SL estimate. Previously recorded 0.0 PnL on all reconciliation closes.
- **SQLite busy_timeout=5000**: Prevents instant SQLITE_BUSY on write contention (was returning immediately).
- **Entry exception safety**: `_attempt_entry` wrapped in try/except — marks pattern REJECTED on crash instead of retrying every 60s.
### Phase 2 — Thread safety:
- **Thread-local sessions**: `TradeLogger._session` is now a property calling `get_session()` per access. Each thread (scanner, monitor, health, telegram) gets its own SQLAlchemy session. Root cause of `prepared` state errors and potential data corruption.
- **Armed patterns lock**: `threading.Lock` protects all mutations/iterations of `_armed_patterns` across scanner and telegram threads.
- **Removed session.close()**: Trade monitor and telegram_bot no longer call `session.close()` which was killing shared scoped_session state.
- **Actual fill price on close**: `close_position` returns `{"success": True, "fill_price": ...}`. `_close_trade` uses real fill price, not pre-close snapshot.
### Phase 3 — Robustness:
- **Commit rollback**: All 10 `session.commit()` calls in TradeLogger wrapped with try/except/rollback.
- **Magic number check**: `_find_position_for_trade` validates `pos.magic == 20250305` to avoid matching manual positions.
- **Period-start equity**: Circuit breaker captures equity at start of each period (daily/weekly/monthly). Loss% calculated against that, not current shrinking balance.
- **Repaired trades 45-48**: Used MT5 deal history to fix PnL on 4 reconciliation-closed trades. Trades 46 (+5.6p) and 48 (+2.2p) were actually winners recorded as 0.0.

## Bugs Fixed (2026-03-31) — Reconciliation still recording 0.0 PnL
- **Reconciliation racing trade monitor**: Reconciliation closed trades on first miss (60s), before trade monitor's 2nd miss (2x30s). Fix: reconciliation now requires 3 consecutive misses, giving trade monitor priority. See `reconciliation.py:62-73`.
- **IC Markets deal lookup broken**: `mt5.history_deals_get(position=ticket)` returns empty on IC Markets. Both reconciliation AND trade monitor now fall back to broad search (`history_deals_get(from, to)` filtered by symbol). See `reconciliation.py:216-227`, `trade_monitor.py:412-421`.
- **Fallback used entry price = 0.0 PnL**: When no deals found, both systems used `trade.entry_price` as close price. Now uses priority chain: `trailing_sl > stop_loss > entry_price`. Also estimates dollar PnL from pips instead of hardcoding 0.0. See `reconciliation.py:281-327`, `trade_monitor.py:435-452`.

## Live Performance (2026-03-13 to 2026-03-27)
- Starting balance ~$620, current ~$560.91 (-9.5% drawdown)
- 44 trades total. First 27 have unreliable pattern_type (all NULL/HVF).
- **pattern_type bug fixed** 2026-03-25: `main.py:log_trade_open` now includes `pattern_type` field
- PnL data corrupted on several trades due to deal misattribution bug (now fixed)
- **Performance window reset** to 2026-03-25 (corrupted data was inflating/crashing Sharpe calculation)
- Clean KZ_HUNT-only evaluation period starts 2026-03-25
- **Scanner was dead 2026-03-25 evening to 2026-03-26 ~19:47 UTC** due to DetachedInstanceError (now fixed)
- **No new entries 2026-03-26 19:47 to 2026-03-27 09:00** due to dedup blockade from rejected patterns (now fixed)
- Trade #44 EURAUD LONG opened 2026-03-27 09:00 after fix deployed — invalidated same day (KZ low revisit)
- **System fully stable from 2026-03-27 ~09:00** — first truly clean operational period

## Invalidation A/B Backtest (2026-03-27) — 10yr, 5 pairs, KZ_HUNT
**WITH invalidation**: PF=1.69, ~1,753 trades invalidated out of total
**WITHOUT invalidation**: PF=1.56, more trades reach SL

### Fate of invalidated trades (would they have won without invalidation?):
- **79% would have been LOSERS** (hit SL) — invalidation correctly kills bad trades
- **21% would have been WINNERS** (trailing stop or target hit)
- Pips saved by killing losers: +10,719
- Pips lost by killing winners: -12,111
- **Net pip impact: -1,392 over 10yr (-139/yr)** — small cost
- But **PF improves** (1.56→1.69) because average loss size shrinks significantly
- **Decision: keep invalidation as-is**. Don't optimize until 50+ clean live trades collected.
- Research backlog: test close-based trigger (instead of wick-based) to save more would-be-winners
- Scripts: `backtests/run_bt_invalidation_compare.py`, `backtests/analyze_invalidation_fates.py`

## Known Issues / Watch Items
1. **Spread widening risk**: SL spread compensation only at entry. Off-hours widening could clip tight stops.
2. **London Sweep**: coded but net negative, not enabled
3. **Backtest gap**: doesn't account for FX conversion in equity curves (pip metrics still valid)
4. **Historical PnL unreliable**: Trades 21,25,27,31,35,37 have corrupted close_price/pnl from deal misattribution bug
5. **Historical pattern_type unreliable**: All 27 pre-fix trades show NULL/HVF — actual pattern type unknown without cross-referencing pattern_records by pattern_id

## Remaining Audit Findings (deferred)
- M8: RRR threshold 1.0 may be too tight given spread widening — deferred until 50+ clean trades
- L1-L5: Various logging/monitoring improvements (see full audit in conversation 2026-03-30)

# currentDate
Today's date is 2026-03-31.
