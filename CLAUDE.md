# HVF Auto-Trader — Project Guide

## What This Is
Automated forex trading bot running KZ Hunt (Kill Zone Hunt) strategy on 5 pairs via MetaTrader 5. Deployed to a Windows VPS, managed as an NSSM service. Python, SQLAlchemy, Telegram alerts.

## Current State (as of 2026-04-01)
- **Active strategy**: KZ_HUNT only (all 8 pairs)
- **Disabled**: HVF (PF=0.06 live after 27 trades), Viper (net negative 10yr), London Sweep (net negative)
- **Account**: IC Markets Demo, ~$10.5k balance, 1% risk per trade
- **Account history**: Started $700 (2026-03-06), $10k deposit added 2026-03-31
- **Phase**: Data collection — need 50+ clean trades before changing any parameters
- **Go-live date**: 2026-03-25 (performance stats ignore trades before this)

## DO NOT
- Enable HVF or Viper patterns — both are proven unprofitable live
- Change KZ_HUNT parameters (RRR threshold, risk %, trailing ATR mult) until 50+ clean trades collected
- Skip `./deploy.sh` and manually copy files — it handles cache clearing and service restart
- Use `&&` in PowerShell commands on the VPS — use `;` instead
- Call `session.close()` anywhere — thread-local scoped sessions manage their own lifecycle
- Store SQLAlchemy ORM objects in long-lived state — use `_detach_record()` to snapshot into SimpleNamespace
- Trust `mt5.history_deals_get(position=ticket)` on IC Markets — it returns empty. Always fall back to broad search

---

## Architecture

### 4 Threads
| Thread | File | Interval | Purpose |
|--------|------|----------|---------|
| Scanner (main) | `main.py:_scanner_loop` | 60s | Detect patterns, arm, confirm entries, execute |
| Trade Monitor | `trade_monitor.py` | 30s | Partials at T1, trailing stops, invalidation, server-close detection |
| Health Check | `health_check.py` | 60s | MT5 heartbeat, reconnection with exponential backoff |
| Telegram Commands | `telegram_commands.py` | polling | /status, /health, /trades, /equity, /balance, /closeall |

### Pipeline: Detection to Execution
```
fetch_and_prepare (H1 OHLCV + ATR/EMA/ADX)
  → KillZoneTracker.update (track session highs/lows)
  → detect_kz_hunt_patterns (rejection candle at KZ extreme)
  → score_kz_hunt (0-100: rejection quality, KZ range, EMA200, volume, timing)
  → score >= 50 → prioritize_signals (best signal per symbol)
  → dedup check (no open trade, no armed pattern, no recent trigger for same symbol+direction)
  → ARM pattern (log to DB + Telegram alert)
  → next cycle: check_entry_confirmation (close past entry price)
  → pre_trade_check (8 risk gates: circuit breaker, margin, spread, RRR, news, lot size)
  → place_market_order (MT5) → recalculate SL from fill → log trade
```

### Trade Management (after entry)
```
Every 30s (trade_monitor):
  1. Check invalidation (KZ extreme revisit, 2hr grace period)
  2. Check T2 hit → full close
  3. Check T1 hit → close 60%, move SL to breakeven
  4. After partial: trail remaining 40% at 1.0x ATR (KZ_HUNT)
```

### Key Files
| File | Role |
|------|------|
| `config.py` | Single source of truth for all parameters |
| `main.py` | Orchestrator — scanner loop, arming, entry execution |
| `trade_monitor.py` | Post-entry management — partials, trailing, closes |
| `order_manager.py` | MT5 order execution — market orders, modify SL, close |
| `reconciliation.py` | DB vs MT5 position sync (3-miss counter before closing) |
| `trade_logger.py` | All DB writes — thread-local sessions via property accessor |
| `models.py` | SQLAlchemy models + engine init with WAL mode + busy_timeout |
| `telegram_bot.py` | Alerts + daily summary with equity chart |
| `circuit_breaker.py` | Daily 5% / weekly 8% / monthly 15% loss limits |
| `risk_manager.py` | 8 pre-trade gates (sequential, all must pass) |
| `kz_hunt_detector.py` | Pattern detection — rejection candles at KZ extremes |
| `kz_hunt_scorer.py` | 5-component scorer (rejection, range, EMA, volume, timing) |
| `killzone_tracker.py` | Tracks session highs/lows per kill zone period |

---

## KZ Hunt Strategy

### What It Is
Session-reversal strategy. Price reaches a Kill Zone extreme (session high/low), prints a rejection candle (wick > 2x body), and reverses. Not a Francis Hunt original — it's a composite of his KZ timing concepts, ICT/Smart Money session theory, and TradingView community work. Trade management (partial close + trail) borrowed from Hunt's HVF approach.

### Entry Rules
1. Kill Zone session completes (London 8-11, NY morning 13-15, NY evening 16-20, Asian 0-4 UTC)
2. Price approaches the completed KZ high or low within 0.3x ATR
3. Rejection candle forms: wick > 2x body (bullish rejection at low, bearish at high)
4. Score >= 50/100 (rejection quality + KZ range + EMA200 alignment + volume + session timing)
5. Confirmation: next bar closes past entry price
6. All 8 risk checks pass

### Levels
- **Entry**: Rejection candle close price
- **Stop Loss**: Beyond KZ extreme + 0.5x ATR (widened by spread at execution)
- **Target 1**: Opposite KZ extreme (partial close 60%)
- **Target 2**: 1.5x KZ range from entry (full close)
- **Minimum RRR**: 1.0 (calculated against T2)
- **Minimum stop**: 8 pips (filters noise)

### Invalidation
- If price revisits the KZ extreme we're fading (LONG: KZ low revisit, SHORT: KZ high revisit)
- 2-hour grace period before checking
- Backtested: improves PF from 1.56 to 1.69 (79% of invalidated trades would have been losers)

### Walk-Forward Validation (12m train / 3m test / 3m step, 11.3 years)
| Metric | Value |
|--------|-------|
| OOS trades | 4,656 |
| OOS Win Rate | 61% |
| OOS Profit Factor | 1.53 |
| OOS Total Pips | +13,483 |
| Positive windows | 162/205 (79%) |

Per-pair: EURUSD PF=1.68, NZDUSD PF=1.69, EURGBP PF=1.47, USDCHF PF=1.52, EURAUD PF=1.33.

### Expert Panel Expectations (live vs backtest)
- Expected live PF: 1.15-1.30 (40-60% degradation from backtest 1.53)
- Realistic MaxDD: 28-35%
- 1 pip slippage/trade consumes 31% of edge
- Effective independent bets: 2.5-3.0 (not 6) due to EUR/USD correlation
- Breakeven stop hit rate: 30-40% on trades that reached T1

---

## Deployment

### From Mac (repo root)
```bash
./deploy.sh    # stops bot, uploads, clears __pycache__, restarts
```

### VPS Details
- **Host**: 198.244.245.3 (SSH alias: `hvf-vps`)
- **OS**: Windows Server, PowerShell
- **Path**: `C:\hvf_trader\` (entry point: `main.py`)
- **Python**: `C:\hvf_trader\venv\Scripts\python.exe`
- **Service**: NSSM (`C:\nssm\nssm.exe`) — auto-start on boot, auto-restart on failure (5s delay)

### Bot Control
```powershell
C:\nssm\nssm.exe start HVF_Bot
C:\nssm\nssm.exe stop HVF_Bot
C:\nssm\nssm.exe restart HVF_Bot
C:\nssm\nssm.exe status HVF_Bot
```

### Logs
```powershell
Get-Content C:\hvf_trader\logs\main.log -Tail 20        # all activity
Get-Content C:\hvf_trader\logs\trades.log -Tail 20       # trade events
Get-Content C:\hvf_trader\logs\errors.log -Tail 20       # warnings/errors
Get-Content C:\hvf_trader\logs\service_stdout.log -Tail 20  # NSSM stdout
```

### Quick Health Check (from Mac)
```bash
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/main.log' -Tail 10 -ErrorAction SilentlyContinue; exit 0"
```

### DB Queries (from VPS)
```powershell
C:\hvf_trader\venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect(r'C:\hvf_trader\hvf_trader.db'); cur = conn.cursor(); cur.execute('SELECT id, symbol, direction, pattern_type, status, pnl, pnl_pips FROM trade_records ORDER BY id DESC LIMIT 10'); [print(r) for r in cur.fetchall()]; conn.close()"
```

---

## Known Gotchas

### IC Markets MT5
- `mt5.history_deals_get(position=ticket)` returns empty — always fall back to broad search (`history_deals_get(from_date, now)`) filtered by symbol
- Spread widens significantly outside London/NY sessions — SL spread compensation only applied at entry

### SQLAlchemy / Threading
- **Thread-local sessions**: `TradeLogger._session` is a property calling `get_session()` per access. Never cache the session object.
- **DetachedInstanceError**: ORM objects expire after `session.commit()`. Use `_detach_record()` (main.py:54) to snapshot into SimpleNamespace before storing in long-lived state.
- **Double-close guard**: `log_trade_close` skips if trade already CLOSED — prevents reconciliation overwriting real PnL.
- **WAL mode + busy_timeout=5s**: Set via engine event listener in models.py. Required for concurrent writes from 4 threads.
- **Armed patterns lock**: `threading.Lock` protects `_armed_patterns` list — always acquire before mutation or iteration.

### Reconciliation vs Trade Monitor
- Both detect missing MT5 positions. Trade monitor runs every 30s (2 misses = close). Reconciliation runs every 60s (3 misses = close).
- Trade monitor gets priority by design — it has better deal history lookup.
- Reconciliation is the safety net for anything trade monitor misses.

### Position Sizing
- Risk manager calculates lots from equity, risk%, and stop distance
- FX conversion for non-USD quoted pairs handled by `_get_quote_to_account_rate()`
- Minimum lot rounding can distort small accounts — $10k+ recommended

---

## Configuration Quick Reference (config.py)

```
ENABLED_PATTERNS = ["KZ_HUNT"]
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]
RISK_PCT_BY_PATTERN = {"KZ_HUNT": 1.0}          # 1% equity per trade
MIN_RRR_BY_PATTERN = {"KZ_HUNT": 1.0}            # minimum reward:risk
SCORE_THRESHOLD_BY_PATTERN = {"KZ_HUNT": 50}     # minimum score to arm
PARTIAL_CLOSE_PCT = 0.60                          # close 60% at T1
TRAILING_STOP_ATR_MULT_BY_PATTERN = {"KZ_HUNT": 1.0}  # trail at 1x ATR
MIN_STOP_PIPS_BY_PATTERN = {"KZ_HUNT": 8}        # reject < 8 pip stops
PATTERN_FRESHNESS_BARS = {"KZ_HUNT": 24}          # expires after 24 H1 bars
MAX_CONCURRENT_TRADES = 6
MAX_SPREAD_PCT_OF_STOP = 0.10                     # 10% of stop distance
DAILY_LOSS_LIMIT_PCT = 5.0
WEEKLY_LOSS_LIMIT_PCT = 8.0
MONTHLY_LOSS_LIMIT_PCT = 15.0
PERF_GO_LIVE_DATE = "2026-03-25"
```

## Deferred Work (see TODO.md)
- **M8**: RRR 1.0 threshold may be too tight with spread — revisit after 50+ trades
- **L1-L5**: Logging/monitoring polish — low priority
- **Feature backlog**: Correlation guard, alternative SL backtest, regime filter, Monte Carlo, per-pair daily limit

## Backtesting
```bash
# Single pair backtest
python -m hvf_trader.backtesting.run_backtest

# Walk-forward validation
python -m hvf_trader.backtesting.walk_forward

# Invalidation A/B comparison
python backtests/run_bt_invalidation_compare.py
python backtests/analyze_invalidation_fates.py
```

Charts output to `backtests/charts/`.
